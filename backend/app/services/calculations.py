"""
Compliance calculation checks — runs after every extraction.

12 checks total:
  1  wrong_item_code
  2  mass_balance_error
  3  tank_capacity_exceeded
  4  combined_capacity_threshold
  5  sludge_generation_rate            (sludge-tank drop pattern)
  6  bilge_increasing_rate
  7  sludge_vs_fuel_consumption        (Actual Generation vs Scraped Fuel)
  8  bilge_transfer_vs_soundings
  9  bilge_pump_capacity               (Pump output vs duration)
  10 bunker_mismatch
  11 missing_master_signature          (Aggregated: One alert per upload)
  12 non_chronological_entry / erasure_detected
"""
import uuid
import re
import logging
from datetime import timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func

from app.models.orb_entry import OrbEntry
from app.models.orb_entry_quantity import OrbEntryQuantity
from app.models.orb_alert import OrbAlert
from app.models.vessel_tank import VesselTank
from app.models.fuel_consumption import FuelConsumption
from app.models.vessel import Vessel

logger = logging.getLogger(__name__)

# Tank groups excluded from the standard mass-balance check
EXCLUDED_MASS_BALANCE_GROUPS = {"BILGE", "SLUDGE"}

BUNKER_ORB_CODE = "H"
BUNKER_ITEM = "26.3"

def _norm_tank(name: str | None) -> str:
    """Normalise a tank name for comparison."""
    if not name:
        return "unknown"
    cleaned = re.sub(r"[#.\-]", " ", name)
    return re.sub(r"\s+", " ", cleaned.upper().strip())

def _get_effective_group(tank: VesselTank) -> str:
    """Returns the tank group. If NULL in DB, attempts to guess from the name."""
    if tank.tank_group and tank.tank_group.strip():
        return tank.tank_group.strip().upper()
    
    name = tank.tank_name.upper()
    if "SLUDGE" in name or "WASTE OIL" in name or "OIL RESIDUE" in name:
        return "SLUDGE"
    if "BILGE" in name:
        return "BILGE"
    return "OTHER"

def _parse_time(t: str | None):
    """Parses time strings like '14:30' into minutes since midnight."""
    if not t:
        return None
    t = t.strip().upper().replace(".", ":")
    m = re.match(r"^(\d{1,2}):?(\d{2})\s*(AM|PM)?$", t)
    if not m:
        return None
    hh, mm, ampm = int(m.group(1)), int(m.group(2)), m.group(3)
    if ampm == "PM" and hh != 12:
        hh += 12
    if ampm == "AM" and hh == 12:
        hh = 0
    if hh > 23 or mm > 59:
        return None
    return hh * 60 + mm 

async def create_alert_if_new(
    db: AsyncSession, 
    vessel_id: uuid.UUID, 
    entry_id, 
    alert_type: str, 
    severity: str, 
    message: str
):
    """Creates a compliance alert if an identical one doesn't already exist."""
    q = select(OrbAlert).where(
        OrbAlert.alert_type == alert_type, 
        OrbAlert.vessel_id == vessel_id
    )
    if entry_id:
        q = q.where(OrbAlert.entry_id == entry_id)
    else:
        q = q.where(OrbAlert.entry_id.is_(None))

    result = await db.execute(q)
    if result.scalar_one_or_none():
        return

    alert = OrbAlert(
        id=uuid.uuid4(), 
        vessel_id=vessel_id, 
        entry_id=entry_id, 
        alert_type=alert_type, 
        severity=severity, 
        message=message, 
        is_resolved=False
    )
    db.add(alert)
    await db.flush()

async def run_all_checks(vessel_id: uuid.UUID, upload_id: uuid.UUID | None, db: AsyncSession):
    """Run all 12 compliance checks scoped closely to avoid duplication loops."""
    await check_wrong_item_code(vessel_id, upload_id, db)                    # 1
    await check_mass_balance_error(vessel_id, upload_id, db)                 # 2
    await check_tank_capacity_exceeded(vessel_id, upload_id, db)             # 3
    await check_combined_capacity_threshold(vessel_id, db)                   # 4
    await check_sludge_generation_rate(vessel_id, upload_id, db)             # 5
    await check_bilge_increasing_rate(vessel_id, upload_id, db)              # 6
    await check_sludge_vs_fuel_consumption(vessel_id, upload_id, db)         # 7
    await check_bilge_transfer_vs_soundings(vessel_id, upload_id, db)        # 8
    await check_bilge_pump_capacity(vessel_id, upload_id, db)                # 9
    await check_bunker_mismatch(vessel_id, upload_id, db)                    # 10
    await check_missing_master_signature(vessel_id, upload_id, db)           # 11
    await check_chronology_and_erasures(vessel_id, upload_id, db)            # 12
    await db.commit()

# ─────────────────────────────────────────────────────────────────────────
# Check 1 — Wrong Item Code
# ─────────────────────────────────────────────────────────────────────────
async def check_wrong_item_code(vessel_id: uuid.UUID, upload_id: uuid.UUID | None, db: AsyncSession):
    q = select(OrbEntry).where(OrbEntry.vessel_id == vessel_id)
    if upload_id:
        q = q.where(OrbEntry.upload_id == upload_id)
        
    result = await db.execute(
        q.where(
            or_(
                OrbEntry.item_number.in_(["12.5", "11.4"]), 
                and_(OrbEntry.orb_code == "I", OrbEntry.item_number.isnot(None))
            )
        )
    )
    for entry in result.scalars().all():
        msg = f"[{entry.entry_date}] Invalid Item/Code combination."
        await create_alert_if_new(db, vessel_id, entry.id, "wrong_item_code", "major", msg)

# ─────────────────────────────────────────────────────────────────────────
# Check 2 — Mass Balance Error
# ─────────────────────────────────────────────────────────────────────────
async def check_mass_balance_error(vessel_id: uuid.UUID, upload_id: uuid.UUID | None, db: AsyncSession):
    tanks = (await db.execute(select(VesselTank).where(VesselTank.vessel_id == vessel_id, VesselTank.is_active == True))).scalars().all()
    for tank in tanks:
        if _get_effective_group(tank) in EXCLUDED_MASS_BALANCE_GROUPS: continue
        
        base_q = select(OrbEntry, OrbEntryQuantity).join(OrbEntryQuantity).where(
            OrbEntry.vessel_id == vessel_id, 
            or_(func.lower(OrbEntryQuantity.from_tank) == func.lower(tank.tank_name), func.lower(OrbEntryQuantity.to_tank) == func.lower(tank.tank_name))
        )
        if upload_id:
            base_q = base_q.where(OrbEntry.upload_id == upload_id)
            
        rows = (await db.execute(base_q.order_by(OrbEntry.entry_date))).all()
        balance, tn = None, _norm_tank(tank.tank_name)
        for entry, qty in rows:
            if qty.qty_type == "retained" and (_norm_tank(qty.from_tank) == tn or _norm_tank(qty.to_tank) == tn):
                if balance is not None and (balance - qty.qty_value) > 0.15:
                    msg = f"[{entry.entry_date}] Tank {tank.tank_name} mass balance error."
                    await create_alert_if_new(db, vessel_id, entry.id, "mass_balance_error", "major", msg)
                balance = qty.qty_value
            elif qty.qty_type == "transferred":
                if balance is not None: balance += qty.qty_value if _norm_tank(qty.to_tank) == tn else -qty.qty_value
            elif qty.qty_type in ("disposed", "evaporated") and _norm_tank(qty.from_tank) == tn:
                if balance is not None: balance -= qty.qty_value

# ─────────────────────────────────────────────────────────────────────────
# Check 3 — Tank Capacity Exceeded
# ─────────────────────────────────────────────────────────────────────────
async def check_tank_capacity_exceeded(vessel_id: uuid.UUID, upload_id: uuid.UUID | None, db: AsyncSession):
    tanks = (await db.execute(select(VesselTank).where(VesselTank.vessel_id == vessel_id, VesselTank.is_active == True))).scalars().all()
    for tank in tanks:
        base_q = select(OrbEntryQuantity, OrbEntry).join(OrbEntry).where(
            OrbEntry.vessel_id == vessel_id, 
            OrbEntryQuantity.qty_type == "retained", 
            or_(func.lower(OrbEntryQuantity.from_tank) == func.lower(tank.tank_name), func.lower(OrbEntryQuantity.to_tank) == func.lower(tank.tank_name))
        )
        if upload_id:
            base_q = base_q.where(OrbEntry.upload_id == upload_id)
            
        row = (await db.execute(base_q.order_by(OrbEntry.entry_date.desc()).limit(1))).first()
        if row and tank.capacity_m3 and row[0].qty_value > tank.capacity_m3:
            msg = f"[{row[1].entry_date}] Tank {tank.tank_name} exceeds certified capacity."
            await create_alert_if_new(db, vessel_id, row[1].id, "tank_capacity_exceeded", "critical", msg)

# ─────────────────────────────────────────────────────────────────────────
# Check 4 — Combined Capacity Threshold
# ─────────────────────────────────────────────────────────────────────────
async def check_combined_capacity_threshold(vessel_id: uuid.UUID, db: AsyncSession):
    tanks = (await db.execute(select(VesselTank).where(VesselTank.vessel_id == vessel_id, VesselTank.is_active == True))).scalars().all()
    if not tanks: return
    total_cap = sum(t.capacity_m3 for t in tanks if t.capacity_m3)
    total_ret = 0.0
    for tank in tanks:
        val = (await db.execute(select(OrbEntryQuantity).join(OrbEntry).where(OrbEntry.vessel_id == vessel_id, OrbEntryQuantity.qty_type == "retained", or_(func.lower(OrbEntryQuantity.from_tank) == func.lower(tank.tank_name), func.lower(OrbEntryQuantity.to_tank) == func.lower(tank.tank_name))).order_by(OrbEntry.entry_date.desc()).limit(1))).scalar_one_or_none()
        if val: total_ret += val.qty_value
    if total_cap > 0 and (total_ret / total_cap) > 0.85:
        await create_alert_if_new(db, vessel_id, None, "combined_capacity_threshold", "major", "Combined tank fill exceeds 85% threshold limit.")

# ─────────────────────────────────────────────────────────────────────────
# Check 5 — Sludge Generation Rate (Pattern Tracking)
# ─────────────────────────────────────────────────────────────────────────
async def check_sludge_generation_rate(vessel_id: uuid.UUID, upload_id: uuid.UUID | None, db: AsyncSession):
    tanks = (await db.execute(select(VesselTank).where(VesselTank.vessel_id == vessel_id, VesselTank.is_active == True))).scalars().all()
    sludge_tanks = [t for t in tanks if _get_effective_group(t) == "SLUDGE"]
    for tank in sludge_tanks:
        base_q = select(OrbEntry, OrbEntryQuantity).join(OrbEntryQuantity).where(
            OrbEntry.vessel_id == vessel_id, 
            or_(func.lower(OrbEntryQuantity.from_tank) == func.lower(tank.tank_name), func.lower(OrbEntryQuantity.to_tank) == func.lower(tank.tank_name))
        )
        if upload_id:
            base_q = base_q.where(OrbEntry.upload_id == upload_id)
            
        rows = (await db.execute(base_q.order_by(OrbEntry.entry_date))).all()
        prev_ret, prev_ent, tn = None, None, _norm_tank(tank.tank_name)
        for entry, qty in rows:
            if qty.qty_type == "retained" and (_norm_tank(qty.from_tank) == tn or _norm_tank(qty.to_tank) == tn):
                if prev_ret is not None:
                    diff = prev_ret - qty.qty_value
                    if diff > 0.01:
                        has_mov = any(e2.entry_date >= prev_ent.entry_date and e2.entry_date <= entry.entry_date and q2.qty_type in ("transferred", "disposed", "incinerated") for e2, q2 in rows)
                        if not has_mov: 
                            msg = f"[{entry.entry_date}] Sludge drop in {tank.tank_name} without matching log entry."
                            await create_alert_if_new(db, vessel_id, entry.id, "sludge_generation_rate", "minor", msg)
                    elif abs(diff) < 0.005:
                        msg = f"[{entry.entry_date}] Sludge level in {tank.tank_name} is unchanged."
                        await create_alert_if_new(db, vessel_id, entry.id, "sludge_generation_rate", "observation", msg)
                prev_ret, prev_ent = qty.qty_value, entry

# ─────────────────────────────────────────────────────────────────────────
# Check 6 — Bilge Increasing Rate
# ─────────────────────────────────────────────────────────────────────────
async def check_bilge_increasing_rate(vessel_id: uuid.UUID, upload_id: uuid.UUID | None, db: AsyncSession):
    tanks = (await db.execute(select(VesselTank).where(VesselTank.vessel_id == vessel_id, VesselTank.is_active == True))).scalars().all()
    bilge_tanks = [t for t in tanks if _get_effective_group(t) == "BILGE"]
    discharge_dates = [e.entry_date for e in (await db.execute(select(OrbEntry).where(OrbEntry.vessel_id == vessel_id, OrbEntry.orb_code.in_(["D", "E"])))).scalars().all()]
    for tank in bilge_tanks:
        base_q = select(OrbEntry, OrbEntryQuantity).join(OrbEntryQuantity).where(
            OrbEntry.vessel_id == vessel_id, 
            OrbEntryQuantity.qty_type == "retained", 
            or_(func.lower(OrbEntryQuantity.from_tank) == func.lower(tank.tank_name), func.lower(OrbEntryQuantity.to_tank) == func.lower(tank.tank_name))
        )
        if upload_id:
            base_q = base_q.where(OrbEntry.upload_id == upload_id)
            
        rows = (await db.execute(base_q.order_by(OrbEntry.entry_date))).all()
        consecutive, prev_v, prev_d = 0, None, None
        for entry, qty in rows:
            if prev_v is not None and qty.qty_value > prev_v:
                if not any(prev_d < d <= entry.entry_date for d in discharge_dates):
                    consecutive += 1
                    if consecutive >= 2: 
                        msg = f"[{entry.entry_date}] Bilge rising consecutively in {tank.tank_name} without discharge."
                        await create_alert_if_new(db, vessel_id, entry.id, "bilge_increasing_rate", "major", msg)
                else: consecutive = 0
            else: consecutive = 0
            prev_v, prev_d = qty.qty_value, entry.entry_date

# ─────────────────────────────────────────────────────────────────────────
# Check 7 — Sludge vs Fuel Consumption
# ─────────────────────────────────────────────────────────────────────────
async def check_sludge_vs_fuel_consumption(vessel_id: uuid.UUID, upload_id: uuid.UUID | None, db: AsyncSession):
    vessel = await db.get(Vessel, vessel_id)
    if not vessel: return

    # 1. Get reference date
    date_query = select(OrbEntry.entry_date).where(OrbEntry.vessel_id == vessel_id)
    if upload_id:
        date_query = date_query.where(OrbEntry.upload_id == upload_id)
    date_query = date_query.order_by(OrbEntry.entry_date.desc()).limit(1)
    
    target_entry_date = (await db.execute(date_query)).scalar_one_or_none()
    if not target_entry_date:
        return

    fuel_record = (await db.execute(
        select(FuelConsumption).where(
            FuelConsumption.vessel_name == vessel.name,
            FuelConsumption.report_date == target_entry_date
        )
    )).scalar_one_or_none()
    
    if not fuel_record:
        fuel_record = (await db.execute(
            select(FuelConsumption).where(
                FuelConsumption.vessel_name == vessel.name,
                FuelConsumption.report_date <= target_entry_date
            ).order_by(FuelConsumption.report_date.desc()).limit(1)
        )).scalar_one_or_none()

    if not fuel_record or fuel_record.total_fuel_consumption <= 0:
        return
    daily_fuel = fuel_record.total_fuel_consumption

    tanks = (await db.execute(select(VesselTank).where(VesselTank.vessel_id == vessel_id, VesselTank.is_active == True))).scalars().all()
    sludge_tanks = [t for t in tanks if _get_effective_group(t) == "SLUDGE"]

    total_sludge_generated = 0.0

    for tank in sludge_tanks:
        tn = tank.tank_name
        
        base_query = select(OrbEntryQuantity).join(OrbEntry).where(
            OrbEntry.vessel_id == vessel_id,
            OrbEntry.orb_code == 'C'
        )
        if upload_id:
            base_query = base_query.where(OrbEntry.upload_id == upload_id)

        # A. Get Opening and Closing Quantities
        sounding_query = base_query.where(
            OrbEntryQuantity.qty_type == "retained",
            or_(func.lower(OrbEntryQuantity.from_tank) == func.lower(tn), func.lower(OrbEntryQuantity.to_tank) == func.lower(tn))
        ).order_by(OrbEntry.entry_date.asc())
        
        soundings = (await db.execute(sounding_query)).scalars().all()
        
        net_sounding_change = 0.0
        if len(soundings) >= 2:
            net_sounding_change = soundings[-1].qty_value - soundings[0].qty_value

        # B. Get Total Removals
        removal_query = base_query.where(
            OrbEntryQuantity.qty_type.in_(["disposed", "incinerated", "transferred"]),
            func.lower(OrbEntryQuantity.from_tank) == func.lower(tn)
        )
        
        removals = (await db.execute(removal_query)).scalars().all()
        total_removals = sum(r.qty_value for r in removals)

        total_sludge_generated += (net_sounding_change + total_removals)

    if total_sludge_generated <= 0: return

    ratio_pct = (total_sludge_generated / daily_fuel) * 100

    if ratio_pct >= 2.0:
        severity = "critical"
    elif ratio_pct >= 1.5:
        severity = "alert"
    else:
        return 

    msg = f"[{target_entry_date}] Sludge generation rate is {ratio_pct:.2f}% of daily fuel ({daily_fuel} MT). Total generated: {total_sludge_generated:.2f} m³."
    await create_alert_if_new(db, vessel_id, None, "sludge_vs_fuel_consumption", severity, msg)

# ─────────────────────────────────────────────────────────────────────────
# Check 8 — Bilge Transfer vs Soundings
# ─────────────────────────────────────────────────────────────────────────
async def check_bilge_transfer_vs_soundings(vessel_id: uuid.UUID, upload_id: uuid.UUID | None, db: AsyncSession):
    tanks = (await db.execute(select(VesselTank).where(VesselTank.vessel_id == vessel_id, VesselTank.is_active == True))).scalars().all()
    bilge_tanks = [t for t in tanks if _get_effective_group(t) == "BILGE"]
    for tank in bilge_tanks:
        base_q = select(OrbEntry, OrbEntryQuantity).join(OrbEntryQuantity).where(
            OrbEntry.vessel_id == vessel_id, 
            or_(func.lower(OrbEntryQuantity.from_tank) == func.lower(tank.tank_name), func.lower(OrbEntryQuantity.to_tank) == func.lower(tank.tank_name))
        )
        if upload_id:
            base_q = base_q.where(OrbEntry.upload_id == upload_id)
            
        rows = (await db.execute(base_q.order_by(OrbEntry.entry_date))).all()
        balance, t_in, disp, tn = None, 0.0, 0.0, _norm_tank(tank.tank_name)
        for entry, qty in rows:
            if qty.qty_type == "retained" and (_norm_tank(qty.from_tank) == tn or _norm_tank(qty.to_tank) == tn):
                if balance is not None and abs(qty.qty_value - (balance + t_in - disp)) > 0.2:
                    msg = f"[{entry.entry_date}] Bilge sounding mismatch in {tank.tank_name}."
                    await create_alert_if_new(db, vessel_id, entry.id, "bilge_transfer_vs_soundings", "minor", msg)
                balance, t_in, disp = qty.qty_value, 0.0, 0.0
            elif qty.qty_type == "transferred" and _norm_tank(qty.to_tank) == tn: t_in += qty.qty_value
            elif qty.qty_type == "disposed" and entry.orb_code in ("D", "E") and _norm_tank(qty.from_tank) == tn: disp += qty.qty_value

# ─────────────────────────────────────────────────────────────────────────
# Check 9 — Bilge Pump Capacity
# ─────────────────────────────────────────────────────────────────────────
async def check_bilge_pump_capacity(vessel_id: uuid.UUID, upload_id: uuid.UUID | None, db: AsyncSession):
    tanks_res = await db.execute(select(VesselTank).where(VesselTank.vessel_id == vessel_id, VesselTank.is_active == True))
    tanks = {t.tank_name: (t.bilge_pump_capacity_m3_per_hr or 2.0) for t in tanks_res.scalars().all() if _get_effective_group(t) == "BILGE"}
    if not tanks: return
    
    base_q = select(OrbEntry, OrbEntryQuantity).join(OrbEntryQuantity).where(
        OrbEntry.vessel_id == vessel_id, 
        OrbEntry.orb_code.in_(["D", "E"]), 
        OrbEntryQuantity.qty_type == "disposed"
    )
    if upload_id:
        base_q = base_q.where(OrbEntry.upload_id == upload_id)
        
    res = await db.execute(base_q)
    for entry, qty in res.all():
        pump_cap = tanks.get(qty.from_tank)
        if not pump_cap: continue
        start, stop = _parse_time(entry.time_start), _parse_time(entry.time_stop)
        if start is None or stop is None: continue
        hours = ((stop - start) if stop >= start else ((1440 - start) + stop)) / 60.0
        if hours <= 0: continue
        if qty.qty_value > (pump_cap * hours + 0.05):
            msg = f"[{entry.entry_date}] Disposed quantity {qty.qty_value}m³ exceeds 2m3/hr pump capacity limit."
            await create_alert_if_new(db, vessel_id, entry.id, "bilge_pump_capacity", "major", msg)

# ─────────────────────────────────────────────────────────────────────────
# Check 10 — Bunker Mismatch
# ─────────────────────────────────────────────────────────────────────────
async def check_bunker_mismatch(vessel_id: uuid.UUID, upload_id: uuid.UUID | None, db: AsyncSession):
    q_filter = and_(OrbEntry.vessel_id == vessel_id, OrbEntry.orb_code == BUNKER_ORB_CODE, OrbEntry.item_number == BUNKER_ITEM)
    if upload_id: q_filter = and_(q_filter, OrbEntry.upload_id == upload_id)
    res = await db.execute(select(OrbEntry).where(q_filter))
    for entry in res.scalars().all():
        qty_res = await db.execute(select(OrbEntryQuantity).where(OrbEntryQuantity.entry_id == entry.id, OrbEntryQuantity.qty_type == "bunkered"))
        total_qty = sum(q.qty_value for q in qty_res.scalars().all())
        desc = entry.operation_description or ""
        if total_qty <= 0 or not re.search(r"\b(VLSFO|HSFO|MGO|MDO|LSMGO|IFO|ULSFO)\b", desc, re.I) or not re.search(r"[A-Za-z0-9]{6,}", desc):
            msg = f"[{entry.entry_date}] Bunker entry missing essential details/specification grades."
            await create_alert_if_new(db, vessel_id, entry.id, "bunker_mismatch", "minor", msg)

# ─────────────────────────────────────────────────────────────────────────
# Check 11 — Missing Master Signature (Aggregated)
# ─────────────────────────────────────────────────────────────────────────
async def check_missing_master_signature(vessel_id: uuid.UUID, upload_id: uuid.UUID | None, db: AsyncSession):
    if not upload_id: return 
    result = await db.execute(select(OrbEntry).where(OrbEntry.vessel_id == vessel_id, OrbEntry.upload_id == upload_id, or_(OrbEntry.master_signature_present.is_(False), OrbEntry.master_signature_present.is_(None))).limit(1))
    if result.scalar_one_or_none():
        await create_alert_if_new(db, vessel_id, None, "missing_master_signature", "minor", "Master/Officer signature not detected on completed pages in this upload batch.")

# ─────────────────────────────────────────────────────────────────────────
# Check 12 — Chronology and Erasures
# ─────────────────────────────────────────────────────────────────────────
async def check_chronology_and_erasures(vessel_id: uuid.UUID, upload_id: uuid.UUID | None, db: AsyncSession):
    q_filter = OrbEntry.vessel_id == vessel_id
    if upload_id: q_filter = and_(q_filter, OrbEntry.upload_id == upload_id)
    entries = (await db.execute(select(OrbEntry).where(q_filter).order_by(OrbEntry.created_at))).scalars().all()
    prev_date = None
    for entry in entries:
        if prev_date and entry.entry_date < prev_date:
            msg = f"[{entry.entry_date}] Entry out of chronological validation order (Previous: {prev_date})."
            await create_alert_if_new(db, vessel_id, entry.id, "non_chronological_entry", "minor", msg)
        prev_date = entry.entry_date
        if entry.has_erasure:
            msg = f"[{entry.entry_date}] Erasure or editing mark detected on physical page."
            await create_alert_if_new(db, vessel_id, entry.id, "erasure_detected", "observation", msg)