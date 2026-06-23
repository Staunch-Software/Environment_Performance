"""Compliance calculation checks — runs after every extraction."""
import uuid
import re
import logging
from datetime import timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from app.models.orb_entry import OrbEntry
from app.models.orb_entry_quantity import OrbEntryQuantity
from app.models.orb_alert import OrbAlert
from app.models.vessel_tank import VesselTank

logger = logging.getLogger(__name__)


def _norm_tank(name: str | None) -> str:
    """Normalise a tank name for comparison: upper, strip, collapse spaces, remove #."""
    if not name:
        return "unknown"
    return re.sub(r"\s+", " ", name.upper().replace("#", "").strip())


async def create_alert_if_new(
    db: AsyncSession,
    vessel_id: uuid.UUID,
    entry_id,
    alert_type: str,
    severity: str,
    message: str,
):
    q = select(OrbAlert).where(
        OrbAlert.alert_type == alert_type,
        OrbAlert.vessel_id == vessel_id,
    )
    if entry_id:
        q = q.where(OrbAlert.entry_id == entry_id)
    else:
        q = q.where(OrbAlert.entry_id.is_(None))

    result = await db.execute(q)
    existing = result.scalar_one_or_none()
    if existing:
        return

    alert = OrbAlert(
        id=uuid.uuid4(),
        vessel_id=vessel_id,
        entry_id=entry_id,
        alert_type=alert_type,
        severity=severity,
        message=message,
        is_resolved=False,
    )
    db.add(alert)
    await db.flush()


async def run_all_checks(vessel_id: uuid.UUID, upload_id: uuid.UUID, db: AsyncSession):
    """Run all 9 compliance checks for the vessel."""
    await check_running_balance(vessel_id, db)
    await check_individual_tank_capacity(vessel_id, db)
    await check_combined_capacity(vessel_id, db)
    await check_overdue_sounding(vessel_id, db)
    await check_marpol_code_violations(vessel_id, db)
    await check_overdue_discharge(vessel_id, db)
    await check_missing_bdn(vessel_id, db)
    await check_sludge_generation_rate(vessel_id, upload_id, db)
    await check_low_confidence(vessel_id, upload_id, db)
    await db.commit()


async def check_running_balance(vessel_id: uuid.UUID, db: AsyncSession):
    """Check 1 — Running balance per tank."""
    tanks_result = await db.execute(
        select(VesselTank).where(VesselTank.vessel_id == vessel_id, VesselTank.is_active == True)
    )
    tanks = tanks_result.scalars().all()

    for tank in tanks:
        entries_result = await db.execute(
            select(OrbEntry, OrbEntryQuantity)
            .join(OrbEntryQuantity, OrbEntryQuantity.entry_id == OrbEntry.id)
            .where(
                OrbEntry.vessel_id == vessel_id,
                or_(
                    OrbEntryQuantity.from_tank == tank.tank_name,
                    OrbEntryQuantity.to_tank == tank.tank_name,
                ),
            )
            .order_by(OrbEntry.entry_date)
        )
        rows = entries_result.all()

        balance = None
        prev_retained = None

        tn = _norm_tank(tank.tank_name)
        for entry, qty in rows:
            if qty.qty_type == "retained" and (
                _norm_tank(qty.from_tank) == tn or _norm_tank(qty.to_tank) == tn
            ):
                if balance is None:
                    balance = qty.qty_value
                else:
                    delta = abs(balance - qty.qty_value)
                    if delta > 0.15:
                        await create_alert_if_new(
                            db, vessel_id, entry.id,
                            "mass_balance_error", "major",
                            f"Tank {tank.tank_name}: computed balance {balance:.2f} m³ vs "
                            f"logged {qty.qty_value:.2f} m³ (Δ {delta:.2f} m³) on {entry.entry_date}",
                        )
                    balance = qty.qty_value

            elif qty.qty_type == "transferred":
                if balance is not None:
                    if _norm_tank(qty.to_tank) == tn:
                        balance += qty.qty_value
                    elif _norm_tank(qty.from_tank) == tn:
                        balance -= qty.qty_value
            elif qty.qty_type in ("disposed", "evaporated") and _norm_tank(qty.from_tank) == tn:
                if balance is not None:
                    balance -= qty.qty_value


async def check_individual_tank_capacity(vessel_id: uuid.UUID, db: AsyncSession):
    """Check 2 — Individual tank > 85% capacity."""
    tanks_result = await db.execute(
        select(VesselTank).where(VesselTank.vessel_id == vessel_id, VesselTank.is_active == True)
    )
    tanks = tanks_result.scalars().all()

    for tank in tanks:
        qty_result = await db.execute(
            select(OrbEntryQuantity)
            .join(OrbEntry, OrbEntry.id == OrbEntryQuantity.entry_id)
            .where(
                OrbEntry.vessel_id == vessel_id,
                OrbEntryQuantity.qty_type == "retained",
                or_(
                    OrbEntryQuantity.from_tank.ilike(tank.tank_name.replace("#", "").strip()),
                    OrbEntryQuantity.to_tank.ilike(tank.tank_name.replace("#", "").strip()),
                    OrbEntryQuantity.from_tank == tank.tank_name,
                    OrbEntryQuantity.to_tank == tank.tank_name,
                ),
            )
            .order_by(OrbEntry.entry_date.desc())
            .limit(1)
        )
        latest = qty_result.scalar_one_or_none()
        if not latest:
            continue

        pct = (latest.qty_value / tank.capacity_m3) * 100 if tank.capacity_m3 else 0
        if pct > 85:
            await create_alert_if_new(
                db, vessel_id, None,
                "tank_capacity_threshold", "major",
                f"Tank {tank.tank_name} at {pct:.1f}% capacity "
                f"({latest.qty_value:.2f} of {tank.capacity_m3:.2f} m³)",
            )


async def check_combined_capacity(vessel_id: uuid.UUID, db: AsyncSession):
    """Check 3 — Combined tank fill > 85%."""
    tanks_result = await db.execute(
        select(VesselTank).where(VesselTank.vessel_id == vessel_id, VesselTank.is_active == True)
    )
    tanks = tanks_result.scalars().all()
    if not tanks:
        return

    total_capacity = sum(t.capacity_m3 for t in tanks)
    total_retained = 0.0

    for tank in tanks:
        qty_result = await db.execute(
            select(OrbEntryQuantity)
            .join(OrbEntry, OrbEntry.id == OrbEntryQuantity.entry_id)
            .where(
                OrbEntry.vessel_id == vessel_id,
                OrbEntryQuantity.qty_type == "retained",
                or_(
                    OrbEntryQuantity.from_tank == tank.tank_name,
                    OrbEntryQuantity.to_tank == tank.tank_name,
                ),
            )
            .order_by(OrbEntry.entry_date.desc())
            .limit(1)
        )
        latest = qty_result.scalar_one_or_none()
        if latest:
            total_retained += latest.qty_value

    if total_capacity > 0:
        pct = (total_retained / total_capacity) * 100
        if pct > 85:
            await create_alert_if_new(
                db, vessel_id, None,
                "combined_capacity_threshold", "major",
                f"Combined tank fill at {pct:.1f}% ({total_retained:.2f} m³ of {total_capacity:.2f} m³ total)",
            )


async def check_overdue_sounding(vessel_id: uuid.UUID, db: AsyncSession):
    """Check 4 — Sounding gap > 8 days."""
    result = await db.execute(
        select(OrbEntry)
        .where(
            OrbEntry.vessel_id == vessel_id,
            OrbEntry.orb_code == "C",
            OrbEntry.item_number.like("11.%"),
        )
        .order_by(OrbEntry.entry_date)
    )
    entries = result.scalars().all()

    by_tank: dict[str, list] = {}
    for entry in entries:
        key = _norm_tank(entry.tank_location)
        by_tank.setdefault(key, []).append(entry)

    for tank_name, tank_entries in by_tank.items():
        for i in range(1, len(tank_entries)):
            prev = tank_entries[i - 1]
            curr = tank_entries[i]
            gap = (curr.entry_date - prev.entry_date).days
            if gap > 8:
                await create_alert_if_new(
                    db, vessel_id, curr.id,
                    "overdue_sounding", "minor",
                    f"No sounding recorded for {tank_name} between {prev.entry_date} "
                    f"and {curr.entry_date} ({gap} days gap)",
                )


async def check_marpol_code_violations(vessel_id: uuid.UUID, db: AsyncSession):
    """Check 5 — MARPOL code violation flags."""
    # 5a: Item 12.5 used — this item does not exist in IMO MEPC.1/Circ.736/Rev.1.
    # The correct item for evaporation/boiler burn is 12.4.
    result = await db.execute(
        select(OrbEntry).where(
            OrbEntry.vessel_id == vessel_id,
            OrbEntry.item_number == "12.5",
        )
    )
    for entry in result.scalars().all():
        await create_alert_if_new(
            db, vessel_id, entry.id,
            "wrong_item_code", "major",
            f"Non-existent Item 12.5 used on {entry.entry_date}. "
            f"Correct item for evaporation/boiler burn is 12.4 per MEPC.1/Circ.736/Rev.1.",
        )

    # 5b: Code I with item_number containing 11.x
    result = await db.execute(
        select(OrbEntry).where(
            OrbEntry.vessel_id == vessel_id,
            OrbEntry.orb_code == "I",
            OrbEntry.item_number.isnot(None),
            OrbEntry.item_number.like("11.%"),
        )
    )
    for entry in result.scalars().all():
        await create_alert_if_new(
            db, vessel_id, entry.id,
            "wrong_item_code", "major",
            f"Code I entry incorrectly uses Item {entry.item_number} on {entry.entry_date}. "
            f"Code I entries must not have item numbers.",
        )

    # 5c: Item 11.4 used
    result = await db.execute(
        select(OrbEntry).where(
            OrbEntry.vessel_id == vessel_id,
            OrbEntry.item_number == "11.4",
        )
    )
    for entry in result.scalars().all():
        await create_alert_if_new(
            db, vessel_id, entry.id,
            "wrong_item_code", "major",
            f"Non-standard Item 11.4 used on {entry.entry_date}. "
            f"Transfers must use Item 12.x series.",
        )


async def check_overdue_discharge(vessel_id: uuid.UUID, db: AsyncSession):
    """Check 6 — No bilge discharge for > 14 days."""
    result = await db.execute(
        select(OrbEntry)
        .where(
            OrbEntry.vessel_id == vessel_id,
            OrbEntry.orb_code == "D",
            OrbEntry.item_number.in_(["15.1", "15.2"]),
        )
        .order_by(OrbEntry.entry_date)
    )
    discharge_entries = result.scalars().all()

    if not discharge_entries:
        return

    for i in range(1, len(discharge_entries)):
        prev = discharge_entries[i - 1]
        curr = discharge_entries[i]
        gap = (curr.entry_date - prev.entry_date).days
        if gap > 14:
            await create_alert_if_new(
                db, vessel_id, curr.id,
                "overdue_discharge", "minor",
                f"No bilge overboard discharge for {gap} days "
                f"({prev.entry_date} to {curr.entry_date}).",
            )


async def check_missing_bdn(vessel_id: uuid.UUID, db: AsyncSession):
    """Check 7 — Bunkering entry without BDN reference."""
    bdn_pattern = re.compile(r"[A-Za-z0-9]{6,}")

    result = await db.execute(
        select(OrbEntry).where(
            OrbEntry.vessel_id == vessel_id,
            OrbEntry.orb_code == "H",
            OrbEntry.item_number == "26.3",
        )
    )
    for entry in result.scalars().all():
        desc = entry.operation_description or ""
        if not bdn_pattern.search(desc):
            await create_alert_if_new(
                db, vessel_id, entry.id,
                "missing_bdn", "minor",
                f"Bunkering entry on {entry.entry_date} has no BDN reference number.",
            )


async def check_sludge_generation_rate(vessel_id: uuid.UUID, upload_id: uuid.UUID, db: AsyncSession):
    """Check 8 — Sludge generation rate 0.5–2% of fuel bunkered."""
    fuel_result = await db.execute(
        select(OrbEntryQuantity)
        .join(OrbEntry, OrbEntry.id == OrbEntryQuantity.entry_id)
        .where(
            OrbEntry.vessel_id == vessel_id,
            OrbEntry.upload_id == upload_id,
            OrbEntryQuantity.qty_type == "bunkered",
        )
    )
    fuel_total = sum(q.qty_value for q in fuel_result.scalars().all())

    if fuel_total <= 0:
        return

    sludge_result = await db.execute(
        select(OrbEntryQuantity)
        .join(OrbEntry, OrbEntry.id == OrbEntryQuantity.entry_id)
        .where(
            OrbEntry.vessel_id == vessel_id,
            OrbEntry.upload_id == upload_id,
            OrbEntryQuantity.qty_type.in_(["disposed", "incinerated"]),
            OrbEntry.orb_code == "C",
            OrbEntry.item_number.in_(["12.1", "12.3"]),
        )
    )
    sludge_total = sum(q.qty_value for q in sludge_result.scalars().all())

    ratio = sludge_total / fuel_total

    if ratio > 0.02:
        await create_alert_if_new(
            db, vessel_id, None,
            "sludge_generation_rate", "critical",
            f"Sludge generation rate {ratio*100:.2f}% exceeds 2% of fuel bunkered "
            f"({fuel_total:.1f} MT). Possible unreported discharge. PSC inspection risk.",
        )
    elif ratio < 0.005 and fuel_total > 100:
        await create_alert_if_new(
            db, vessel_id, None,
            "sludge_generation_rate", "observation",
            f"Sludge generation rate {ratio*100:.3f}% is unusually low for "
            f"fuel consumption of {fuel_total:.1f} MT. Verify sounding records.",
        )


async def check_low_confidence(vessel_id: uuid.UUID, upload_id: uuid.UUID, db: AsyncSession):
    """Check 9 — Low confidence extraction entries."""
    result = await db.execute(
        select(OrbEntry).where(
            OrbEntry.vessel_id == vessel_id,
            OrbEntry.upload_id == upload_id,
            OrbEntry.confidence_score.isnot(None),
            OrbEntry.confidence_score < 0.75,
        )
    )
    for entry in result.scalars().all():
        await create_alert_if_new(
            db, vessel_id, entry.id,
            "low_confidence_extraction", "observation",
            f"Entry on {entry.entry_date} (Code {entry.orb_code} / Item {entry.item_number}) "
            f"extracted with low confidence ({entry.confidence_score:.2f}). "
            f"Manual verification recommended.",
        )
