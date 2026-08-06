"""
Compliance calculation checks — runs after every extraction.

13 checks total:
  1  wrong_item_code
  2  mass_balance_error
  3  tank_capacity_exceeded
  4  combined_capacity_threshold
  5  sludge_generation_rate            (sludge-tank drop pattern)
  6  bilge_increasing_rate
  7  sludge_vs_fuel_consumption        (Actual Generation vs Scraped Fuel)
  8  bilge_transfer_vs_soundings
  9  bilge_pump_capacity               (Pump output vs duration)
  10 bunker_mismatch / bunker_quantity_mismatch
  11 missing_master_signature          (Aggregated: One alert per upload)
  12 non_chronological_entry / erasure_detected
  13 gap_between_entries               (blank full line before an entry)
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
BUNKER_ITEMS = ["26.3", "26.4"]

# Valid item numbers per ORB code, per IMO MEPC.1/Circ.736/Rev.1. Code I
# carries no item number at all, so it's checked separately (any item number
# on a Code I row is itself the violation).
_VALID_ITEMS_BY_CODE = {
    "C": {"11.1", "11.2", "11.3", "11.4", "12.1", "12.2", "12.3", "12.4"},
    "D": {"13", "14", "15.1", "15.2", "15.3"},
    "E": {"16", "17", "18"},
    "F": {"19", "20", "21"},
    "G": {"22", "23", "24", "25"},
    "H": {"26.1", "26.2", "26.3", "26.4"},
}

# Qualifier words that handwritten/extracted tank names inconsistently
# include, omit, or misspell relative to the registered vessel_tanks.tank_name
# ("Bilge Tank" vs "Bilge Holding Tank", "Bilge Sep/Seperated Oil Tank" vs
# "Bilge Separated Oil Tank", "Waste Oil Tank No.1" vs "Waste Oil Settling
# Tank No.1"). Stripped before comparing so the tank's core identity
# (BILGE/SLUDGE/WASTE OIL + any No.1/No.2 ordinal) still matches -- these
# words are never load-bearing for telling two DIFFERENT registered tanks
# apart, only ordinals and the OIL/type tokens are, and those are untouched.
_TANK_NAME_STOPWORDS = {"TANK", "HOLDING", "SETTLING", "SEPARATED", "SEPARATION", "SEPERATED", "SEP"}

def _norm_tank(name: str | None, protect: frozenset[str] = frozenset()) -> str:
    """Normalise a tank name for comparison.

    `protect` excludes specific words from being stripped -- see
    _compute_protected_tank_words for why this is needed per-vessel.
    """
    if not name:
        return "unknown"
    cleaned = re.sub(r"[#.\-]", " ", name)
    cleaned = re.sub(r"\s+", " ", cleaned.upper().strip())
    tokens = [t for t in cleaned.split(" ") if t not in _TANK_NAME_STOPWORDS or t in protect]
    return " ".join(tokens) or cleaned


def _compute_protected_tank_words(tanks: list[VesselTank]) -> frozenset[str]:
    """Words that must NOT be stripped by _norm_tank for THIS vessel.

    The stopword list exists to unify formatting variants of the SAME
    physical tank ("Bilge Tank" == "Bilge Holding Tank"). But on a vessel
    that has TWO genuinely distinct registered tanks whose names differ only
    by one of those stopwords -- confirmed in production: "Bilge Water Tank"
    (28.1 m3) and "Bilge Water Settling Tank" (19.44 m3) both strip down to
    "BILGE WATER" -- the same stripping silently conflates them, comparing
    one tank's real readings against the other's certified capacity.

    Detects any such collision among this vessel's OWN registered tanks and
    protects exactly the word(s) that distinguish the colliding pair, so
    normalisation stays aggressive everywhere it's safe and only backs off
    where it would otherwise merge two real, different tanks.
    """
    from collections import defaultdict

    def _tokens(name: str) -> set[str]:
        cleaned = re.sub(r"[#.\-]", " ", name or "")
        cleaned = re.sub(r"\s+", " ", cleaned.upper().strip())
        return set(cleaned.split(" "))

    by_key: dict[str, list[VesselTank]] = defaultdict(list)
    for t in tanks:
        by_key[_norm_tank(t.tank_name)].append(t)

    protected: set[str] = set()
    for group in by_key.values():
        distinct_names = {t.tank_name.strip().upper() for t in group}
        if len(distinct_names) < 2:
            continue
        token_sets = [_tokens(t.tank_name) for t in group]
        for i in range(len(token_sets)):
            for j in range(i + 1, len(token_sets)):
                protected |= (token_sets[i] ^ token_sets[j]) & _TANK_NAME_STOPWORDS
    return frozenset(protected)

def _get_effective_group(tank: VesselTank) -> str:
    """Returns the tank's functional group: SLUDGE, BILGE, or OTHER.

    Prefers the registered tank_group over guessing from the tank name, but
    matches it by keyword rather than exact equality -- real vessel setups
    use free text here ("SLUDGE OIL", "BILGE WATER", "L.O. & Cyl. Oil"),
    never necessarily the bare word "SLUDGE"/"BILGE" that callers compare
    against. An exact-match comparison silently treats every such tank as
    "OTHER": sludge/bilge-specific checks (5, 6, 9) then find no tanks to
    run on at all, and mass_balance_error (which is supposed to exempt
    bilge/sludge tanks) runs on them anyway since they never match
    EXCLUDED_MASS_BALANCE_GROUPS either. Only fall back to the tank's own
    name when tank_group is unset entirely.
    """
    source = tank.tank_group.strip().upper() if tank.tank_group and tank.tank_group.strip() else tank.tank_name.upper()
    if "SLUDGE" in source or "WASTE OIL" in source or "OIL RESIDUE" in source:
        return "SLUDGE"
    if "BILGE" in source:
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
    await check_entry_gaps(vessel_id, upload_id, db)                         # 13
    await db.commit()

# ─────────────────────────────────────────────────────────────────────────
# Check 1 — Wrong Item Code
# ─────────────────────────────────────────────────────────────────────────
async def check_wrong_item_code(vessel_id: uuid.UUID, upload_id: uuid.UUID | None, db: AsyncSession):
    q = select(OrbEntry).where(OrbEntry.vessel_id == vessel_id)
    if upload_id:
        q = q.where(OrbEntry.upload_id == upload_id)

    result = await db.execute(q)
    for entry in result.scalars().all():
        item = (entry.item_number or "").strip()
        code = entry.orb_code
        if code == "I":
            is_wrong = bool(item)  # Code I entries must carry no item number
        else:
            valid_items = _VALID_ITEMS_BY_CODE.get(code)
            is_wrong = valid_items is None or item not in valid_items
        if is_wrong:
            msg = f"[{entry.entry_date}] Invalid Item/Code combination ({code or '?'} {item or '-'})."
            await create_alert_if_new(db, vessel_id, entry.id, "wrong_item_code", "major", msg)

# ─────────────────────────────────────────────────────────────────────────
# Shared helper — real-world handwritten tank names rarely match the
# registered vessel_tanks.tank_name character-for-character ("BILGE TANK" vs
# "Bilge Holding Tank", "WASTE OIL SETTLING TANK NO#1" vs "...No.1", etc).
# Fetch broadly and match tank-by-tank in Python using _norm_tank() instead
# of relying on exact SQL equality, which silently drops most real entries.
# ─────────────────────────────────────────────────────────────────────────
async def _fetch_vessel_qty_rows(db: AsyncSession, vessel_id: uuid.UUID, upload_id: uuid.UUID | None, extra_filters=None):
    q = select(OrbEntry, OrbEntryQuantity).join(OrbEntryQuantity).where(OrbEntry.vessel_id == vessel_id)
    if upload_id:
        q = q.where(OrbEntry.upload_id == upload_id)
    if extra_filters:
        q = q.where(and_(*extra_filters))
    rows = (await db.execute(q)).all()
    # Sort in Python (stable) rather than via SQL ORDER BY: Postgres does not
    # guarantee tie order for rows sharing an entry_date, and a single
    # physical ORB line commonly produces a "transferred" row immediately
    # followed by the "retained" figure it results in (e.g. "3.0 m3
    # transferred to X, 12.5 m3 retained"). An unstable sort can silently
    # swap that pair, so the balance walk below applies the transfer AGAIN
    # on top of a retained figure that already reflects it -- double
    # counting it and flagging the next real reading as a mass-balance
    # error that never happened. A stable Python sort keyed only on
    # entry_date preserves the query's natural row order for every tie,
    # which keeps a single entry's own quantity rows in their true
    # written sequence.
    rows.sort(key=lambda r: r[0].entry_date)
    return rows

def _order_within_entry(matched: list, tn: str, protect: frozenset[str]) -> list:
    """Reorder same-entry quantity rows so a "retained" reading that is the
    OPENING balance of a same-entry "transferred" quantity is applied to the
    running balance walk BEFORE that transfer, and a "retained" reading that
    is the CLOSING balance is applied AFTER it.

    Every balance-walk check (mass_balance_error, bilge_transfer_vs_soundings,
    sludge_generation_rate) processes rows in whatever order the DB query
    happens to return them for ties on the same entry_date -- which is not
    guaranteed to match the physical opening-then-transfer-then-closing order
    a single ORB block states. Confirmed in production (AM KIRTI,
    10-Mar-2026): a bilge entry stated "7.2 m3 retained [before pumping] ...
    21.5 m3 transferred ... 28.7 m3 retained [after pumping]" -- a perfectly
    consistent operation (7.2 + 21.5 = 28.7) -- but the opening 7.2 reading
    got compared against the running balance AFTER the 21.5 transfer had
    already been applied to it, manufacturing a ~39 m3 "mismatch" that never
    happened. Only kicks in when an entry has two or more "retained" rows for
    the SAME tank alongside a "transferred" row connecting to it -- the
    overwhelmingly common case of a single retained reading per entry is
    completely untouched.

    A second, related case: an entry with only ONE retained reading for this
    tank alongside a disposed/evaporated/incinerated reading (no transfer).
    Every IMO guidance example for this shape (e.g. Annex Example #12/#14:
    "13 xx m3 bilge water from tank... Capacity xx m3, xx m3 retained")
    states the retained figure as the CLOSING balance, after the disposal --
    never an opening one, since there is no second retained reading to be an
    opening figure in the first place. Confirmed in production (AM KIRTI,
    22-May-2026): an entry stated "19.5 m3 disposed ... 9.0 m3 retained"
    (9.0 being the balance AFTER disposing 19.5), but the retained figure was
    processed before the disposal in the balance walk -- adopting 9.0 as a
    checkpoint and THEN subtracting 19.5 from it a second time, manufacturing
    a physically impossible NEGATIVE "expected" balance (-10.5 m3) for the
    next real sounding to be compared against. Reorder so any disposal-type
    reading for this tank is applied to the running balance BEFORE this
    entry's own retained figure is compared/adopted.
    """
    from collections import OrderedDict

    disposal_types = {"disposed", "evaporated", "incinerated"}

    groups: "OrderedDict" = OrderedDict()
    for e, qy in matched:
        groups.setdefault(e.id, []).append((e, qy))

    ordered: list = []
    for group in groups.values():
        same_tank_retained = [
            (e, qy) for e, qy in group
            if qy.qty_type == "retained" and _norm_tank(qy.from_tank, protect) == tn
        ]
        transfer_item = next(
            (
                (e, qy) for e, qy in group
                if qy.qty_type == "transferred"
                and tn in (_norm_tank(qy.from_tank, protect), _norm_tank(qy.to_tank, protect))
            ),
            None,
        )
        if len(same_tank_retained) < 2 or transfer_item is None:
            disposal_items = [
                (e, qy) for e, qy in group
                if qy.qty_type in disposal_types and _norm_tank(qy.from_tank, protect) == tn
            ]
            if same_tank_retained and disposal_items and transfer_item is None:
                retained_ids = {id(qy) for _, qy in same_tank_retained}
                disposal_ids = {id(qy) for _, qy in disposal_items}
                rest = [item for item in group if id(item[1]) not in retained_ids and id(item[1]) not in disposal_ids]
                ordered.extend(rest + disposal_items + same_tank_retained)
            else:
                ordered.extend(group)
            continue

        # Inflow (transfer INTO this tank) -> opening balance is the SMALLER
        # figure, closing is larger. Outflow -> the reverse.
        inflow = _norm_tank(transfer_item[1].to_tank, protect) == tn
        same_tank_retained.sort(key=lambda item: item[1].qty_value, reverse=not inflow)
        opening, closing = same_tank_retained[0], same_tank_retained[-1]
        excluded_ids = {id(opening[1]), id(closing[1]), id(transfer_item[1])}
        rest = [item for item in group if id(item[1]) not in excluded_ids]
        ordered.extend([opening, transfer_item] + rest + [closing])
    return ordered


def _rows_for_tank(rows, tn: str, protect: frozenset[str] = frozenset()):
    matched = [(e, qy) for e, qy in rows if _norm_tank(qy.from_tank, protect) == tn or _norm_tank(qy.to_tank, protect) == tn]
    return _order_within_entry(matched, tn, protect)

# ─────────────────────────────────────────────────────────────────────────
# Check 2 — Mass Balance Error
# ─────────────────────────────────────────────────────────────────────────
async def check_mass_balance_error(vessel_id: uuid.UUID, upload_id: uuid.UUID | None, db: AsyncSession):
    tanks_all = (await db.execute(select(VesselTank).where(VesselTank.vessel_id == vessel_id, VesselTank.is_active == True))).scalars().all()
    protect = _compute_protected_tank_words(tanks_all)
    tanks = [t for t in tanks_all if _get_effective_group(t) not in EXCLUDED_MASS_BALANCE_GROUPS]
    if not tanks: return
    all_rows = await _fetch_vessel_qty_rows(db, vessel_id, upload_id)

    for tank in tanks:
        tn = _norm_tank(tank.tank_name, protect)
        rows = _rows_for_tank(all_rows, tn, protect)
        balance = None
        for entry, qty in rows:
            if qty.qty_type == "retained":
                if balance is not None and abs(balance - qty.qty_value) > 0.15:
                    msg = f"[{entry.entry_date}] Tank {tank.tank_name} mass balance error."
                    await create_alert_if_new(db, vessel_id, entry.id, "mass_balance_error", "major", msg)
                balance = qty.qty_value
            elif qty.qty_type == "transferred":
                if balance is not None: balance += qty.qty_value if _norm_tank(qty.to_tank, protect) == tn else -qty.qty_value
            elif qty.qty_type in ("disposed", "evaporated") and _norm_tank(qty.from_tank, protect) == tn:
                if balance is not None: balance -= qty.qty_value

# ─────────────────────────────────────────────────────────────────────────
# Check 3 — Tank Capacity Exceeded (+ capacity-reading transcription check)
# ─────────────────────────────────────────────────────────────────────────
async def check_tank_capacity_exceeded(vessel_id: uuid.UUID, upload_id: uuid.UUID | None, db: AsyncSession):
    tanks = (await db.execute(select(VesselTank).where(VesselTank.vessel_id == vessel_id, VesselTank.is_active == True))).scalars().all()
    if not tanks: return
    protect = _compute_protected_tank_words(tanks)
    all_rows = await _fetch_vessel_qty_rows(db, vessel_id, upload_id, [OrbEntryQuantity.qty_type.in_(["retained", "capacity"])])

    for tank in tanks:
        tn = _norm_tank(tank.tank_name, protect)
        rows = _rows_for_tank(all_rows, tn, protect)
        if not tank.capacity_m3:
            continue

        retained_rows = [(e, qy) for e, qy in rows if qy.qty_type == "retained"]
        for entry, qy in retained_rows:
            if qy.qty_value > tank.capacity_m3:
                msg = f"[{entry.entry_date}] Tank {tank.tank_name} exceeds certified capacity."
                await create_alert_if_new(db, vessel_id, entry.id, "tank_capacity_exceeded", "critical", msg)

        # "Tank quantities exceeding certified capacity: Transcription error or
        # fabricated figure" — a tank's capacity is a fixed physical property,
        # so an extracted "capacity" reading that deviates from the registered
        # certified capacity is itself a red flag, regardless of direction.
        tol = max(0.1, tank.capacity_m3 * 0.05)
        for entry, qy in rows:
            if qy.qty_type == "capacity" and abs(qy.qty_value - tank.capacity_m3) > tol:
                msg = (f"[{entry.entry_date}] Tank {tank.tank_name} capacity reading {qy.qty_value}m³ "
                       f"does not match certified capacity {tank.capacity_m3}m³ — possible transcription error.")
                await create_alert_if_new(db, vessel_id, entry.id, "capacity_reading_mismatch", "minor", msg)

# ─────────────────────────────────────────────────────────────────────────
# Check 4 — Combined Capacity Threshold
# ─────────────────────────────────────────────────────────────────────────
async def check_combined_capacity_threshold(vessel_id: uuid.UUID, db: AsyncSession):
    tanks = (await db.execute(select(VesselTank).where(VesselTank.vessel_id == vessel_id, VesselTank.is_active == True))).scalars().all()
    if not tanks: return
    protect = _compute_protected_tank_words(tanks)
    total_cap = sum(t.capacity_m3 for t in tanks if t.capacity_m3)
    all_rows = await _fetch_vessel_qty_rows(db, vessel_id, None, [OrbEntryQuantity.qty_type == "retained"])

    total_ret = 0.0
    for tank in tanks:
        tn = _norm_tank(tank.tank_name, protect)
        matches = _rows_for_tank(all_rows, tn, protect)
        if matches: total_ret += matches[-1][1].qty_value
    if total_cap > 0 and (total_ret / total_cap) > 0.85:
        await create_alert_if_new(db, vessel_id, None, "combined_capacity_threshold", "major", "Combined tank fill exceeds 85% threshold limit.")

# ─────────────────────────────────────────────────────────────────────────
# Check 5 — Sludge Generation Rate (Pattern Tracking)
# ─────────────────────────────────────────────────────────────────────────
async def check_sludge_generation_rate(vessel_id: uuid.UUID, upload_id: uuid.UUID | None, db: AsyncSession):
    tanks_all = (await db.execute(select(VesselTank).where(VesselTank.vessel_id == vessel_id, VesselTank.is_active == True))).scalars().all()
    protect = _compute_protected_tank_words(tanks_all)
    sludge_tanks = [t for t in tanks_all if _get_effective_group(t) == "SLUDGE"]
    if not sludge_tanks: return
    all_rows = await _fetch_vessel_qty_rows(db, vessel_id, upload_id)

    for tank in sludge_tanks:
        tn = _norm_tank(tank.tank_name, protect)
        rows = _rows_for_tank(all_rows, tn, protect)
        prev_ret, prev_ent = None, None
        for entry, qty in rows:
            if qty.qty_type == "retained":
                if prev_ret is not None:
                    diff = prev_ret - qty.qty_value
                    # An unchanged level between two soundings is completely
                    # normal (the tank simply wasn't touched) -- this used to
                    # raise an "observation" alert every single time, which
                    # produced no actionable signal and, in practice, drowned
                    # out every other check: on one real upload this single
                    # branch alone accounted for 72 of 101 total alerts (71%)
                    # raised for the vessel. Only a genuine unexplained DROP
                    # is worth surfacing.
                    if diff > 0.01:
                        has_mov = any(e2.entry_date >= prev_ent.entry_date and e2.entry_date <= entry.entry_date and q2.qty_type in ("transferred", "disposed", "incinerated", "evaporated") for e2, q2 in rows)
                        if not has_mov:
                            msg = f"[{entry.entry_date}] Sludge drop in {tank.tank_name} without matching log entry."
                            await create_alert_if_new(db, vessel_id, entry.id, "sludge_generation_rate", "minor", msg)
                prev_ret, prev_ent = qty.qty_value, entry

# ─────────────────────────────────────────────────────────────────────────
# Check 6 — Bilge Increasing Rate
# ─────────────────────────────────────────────────────────────────────────
async def check_bilge_increasing_rate(vessel_id: uuid.UUID, upload_id: uuid.UUID | None, db: AsyncSession):
    tanks_all = (await db.execute(select(VesselTank).where(VesselTank.vessel_id == vessel_id, VesselTank.is_active == True))).scalars().all()
    protect = _compute_protected_tank_words(tanks_all)
    bilge_tanks = [t for t in tanks_all if _get_effective_group(t) == "BILGE"]
    if not bilge_tanks: return
    discharge_dates = [e.entry_date for e in (await db.execute(select(OrbEntry).where(OrbEntry.vessel_id == vessel_id, OrbEntry.orb_code.in_(["D", "E"])))).scalars().all()]
    all_rows = await _fetch_vessel_qty_rows(db, vessel_id, upload_id, [OrbEntryQuantity.qty_type == "retained"])

    for tank in bilge_tanks:
        tn = _norm_tank(tank.tank_name, protect)
        rows = _rows_for_tank(all_rows, tn, protect)
        prev_v, prev_d, prev_entry_id = None, None, None
        for entry, qty in rows:
            # Any single rise from the last figure with no D/E discharge logged
            # in between is itself the violation -- "Bilge tank increasing from
            # last figure ... combined into one figure as error" describes a
            # per-instance trigger, not a streak. (Previously required two
            # consecutive unexplained rises, which silently let a lone
            # unexplained increase through with no alert at all.)
            #
            # Skip the comparison when both readings belong to the SAME entry
            # (an opening balance and closing balance either side of that
            # entry's own logged transfer, per _order_within_entry) -- that
            # rise is already explained by the transfer recorded right there
            # in the entry, but the discharge_dates window below only looks
            # at STRICTLY LATER dates, so a same-day pair would otherwise
            # never find its own entry as the explaining discharge.
            if prev_v is not None and qty.qty_value > prev_v and entry.id != prev_entry_id:
                if not any(prev_d < d <= entry.entry_date for d in discharge_dates):
                    msg = f"[{entry.entry_date}] Bilge rising in {tank.tank_name} from {prev_v}m³ to {qty.qty_value}m³ without a discharge logged in between."
                    await create_alert_if_new(db, vessel_id, entry.id, "bilge_increasing_rate", "major", msg)
            prev_v, prev_d, prev_entry_id = qty.qty_value, entry.entry_date, entry.id

# ─────────────────────────────────────────────────────────────────────────
# Check 7 — Sludge vs Fuel Consumption
# ─────────────────────────────────────────────────────────────────────────
async def check_sludge_vs_fuel_consumption(vessel_id: uuid.UUID, upload_id: uuid.UUID | None, db: AsyncSession):
    """Sludge generated must stay under ~1% of fuel consumed over the SAME
    period; >=1.5% is a warning, >=2% is critical.

    Both sides of the ratio must cover the same window. Comparing a
    lifetime-cumulative sludge total against a single day's fuel figure (the
    previous approach) produces a meaningless, inflated ratio on any
    multi-day document -- e.g. a 5-month ORB batch would compare ~5 months
    of sludge generation against one day of fuel burn. Instead, sum fuel
    consumption over the exact date range spanned by the entries being
    evaluated here.
    """
    vessel = await db.get(Vessel, vessel_id)
    if not vessel: return

    date_filter = [OrbEntry.vessel_id == vessel_id]
    if upload_id:
        date_filter.append(OrbEntry.upload_id == upload_id)
    date_range = (await db.execute(
        select(func.min(OrbEntry.entry_date), func.max(OrbEntry.entry_date)).where(*date_filter)
    )).one_or_none()
    if not date_range or not date_range[0]:
        return
    start_date, end_date = date_range

    total_fuel = (await db.execute(
        select(func.sum(FuelConsumption.total_fuel_consumption)).where(
            FuelConsumption.vessel_name == vessel.name,
            FuelConsumption.report_date >= start_date,
            FuelConsumption.report_date <= end_date,
        )
    )).scalar_one_or_none()

    if not total_fuel or total_fuel <= 0:
        return

    tanks_all = (await db.execute(select(VesselTank).where(VesselTank.vessel_id == vessel_id, VesselTank.is_active == True))).scalars().all()
    protect = _compute_protected_tank_words(tanks_all)
    sludge_tanks = [t for t in tanks_all if _get_effective_group(t) == "SLUDGE"]
    if not sludge_tanks: return

    all_rows = await _fetch_vessel_qty_rows(db, vessel_id, upload_id, [OrbEntry.orb_code == "C"])

    total_sludge_generated = 0.0

    for tank in sludge_tanks:
        tn = _norm_tank(tank.tank_name, protect)
        rows = _rows_for_tank(all_rows, tn, protect)

        # A. Get Opening and Closing Quantities
        soundings = [qy for e, qy in rows if qy.qty_type == "retained"]
        net_sounding_change = 0.0
        if len(soundings) >= 2:
            net_sounding_change = soundings[-1].qty_value - soundings[0].qty_value

        # B. Get Total Removals
        total_removals = sum(
            qy.qty_value for e, qy in rows
            if qy.qty_type in ("disposed", "incinerated", "transferred") and _norm_tank(qy.from_tank, protect) == tn
        )

        total_sludge_generated += (net_sounding_change + total_removals)

    if total_sludge_generated <= 0: return

    ratio_pct = (total_sludge_generated / total_fuel) * 100

    if ratio_pct >= 2.0:
        severity = "critical"
    elif ratio_pct >= 1.5:
        severity = "major"
    else:
        return

    msg = (f"[{start_date} to {end_date}] Sludge generation rate is {ratio_pct:.2f}% of fuel consumed "
           f"over this period ({total_fuel:.2f} MT). Total generated: {total_sludge_generated:.2f} m³.")
    await create_alert_if_new(db, vessel_id, None, "sludge_vs_fuel_consumption", severity, msg)

# ─────────────────────────────────────────────────────────────────────────
# Check 8 — Bilge Transfer vs Soundings
# ─────────────────────────────────────────────────────────────────────────
async def check_bilge_transfer_vs_soundings(vessel_id: uuid.UUID, upload_id: uuid.UUID | None, db: AsyncSession):
    tanks_all = (await db.execute(select(VesselTank).where(VesselTank.vessel_id == vessel_id, VesselTank.is_active == True))).scalars().all()
    protect = _compute_protected_tank_words(tanks_all)
    bilge_tanks = [t for t in tanks_all if _get_effective_group(t) == "BILGE"]
    if not bilge_tanks: return
    # Fetch broadly and match tank-by-tank via _norm_tank(), same as every
    # other tank-scoped check in this file -- an exact SQL-level name match
    # (the previous approach) never matches real handwritten ORB entries
    # against the registered vessel_tanks.tank_name ("BILGE TANK" vs
    # "Bilge Holding Tank"), so this check found zero rows in practice.
    all_rows = await _fetch_vessel_qty_rows(db, vessel_id, upload_id)
    for tank in bilge_tanks:
        tn = _norm_tank(tank.tank_name, protect)
        rows = _rows_for_tank(all_rows, tn, protect)
        # Track a single running balance, adjusted immediately as each movement
        # is encountered, then checked/reset against the next actual sounding.
        # (Previously only counted transfers INTO the tank and disposals tagged
        # with code D/E -- so a normal outgoing transfer to another tank, or a
        # residue disposal logged under Code C (as this vessel does for item
        # 12.1), was never subtracted, making every correctly-logged outflow
        # look like an unexplained "mismatch".)
        #
        # Tolerance: unlike a sealed sludge/residue tank, a bilge tank has
        # continuous natural water ingress between logged pump-out operations
        # -- this is exactly why bilge/sludge tanks are excluded from
        # check_mass_balance_error's strict 0.15 m3 tolerance entirely. A flat
        # 0.2 m3 tolerance here made the same mistake: traced against real
        # data, consecutive readings routinely drift ~2-3 m3 from natural
        # inflow alone (confirmed on this vessel: 30-Dec/02-Jan/04-Jan/06-Jan
        # all showed a consistent ~2.0-2.7 m3 gap), which isn't a violation --
        # it fired on almost every single sounding in the document. Scale the
        # tolerance to the tank's own capacity so only a mismatch large enough
        # to plausibly represent an unlogged operation gets flagged.
        tolerance = max(1.0, (tank.capacity_m3 or 0) * 0.15)
        balance = None
        for entry, qty in rows:
            if qty.qty_type == "retained":
                if balance is not None and abs(qty.qty_value - balance) > tolerance:
                    msg = (f"[{entry.entry_date}] Bilge sounding mismatch in {tank.tank_name}: "
                           f"expected ~{balance:.2f}m³ from prior reading + logged movements, "
                           f"but {qty.qty_value:.2f}m³ was recorded.")
                    await create_alert_if_new(db, vessel_id, entry.id, "bilge_transfer_vs_soundings", "minor", msg)
                balance = qty.qty_value
            elif qty.qty_type == "transferred" and balance is not None:
                if _norm_tank(qty.to_tank, protect) == tn: balance += qty.qty_value
                elif _norm_tank(qty.from_tank, protect) == tn: balance -= qty.qty_value
            elif qty.qty_type in ("disposed", "evaporated") and _norm_tank(qty.from_tank, protect) == tn and balance is not None:
                balance -= qty.qty_value

# ─────────────────────────────────────────────────────────────────────────
# Check 9 — Bilge Pump Capacity
# ─────────────────────────────────────────────────────────────────────────
async def check_bilge_pump_capacity(vessel_id: uuid.UUID, upload_id: uuid.UUID | None, db: AsyncSession):
    tanks_all = (await db.execute(select(VesselTank).where(VesselTank.vessel_id == vessel_id, VesselTank.is_active == True))).scalars().all()
    protect = _compute_protected_tank_words(tanks_all)
    # Keyed by normalised tank name -- qty.from_tank is the raw extracted
    # string ("BILGE TANK", "E/R BILGE WELLS", ...), which rarely matches
    # the registered vessel_tanks.tank_name verbatim, so an exact-string key
    # (the previous approach) silently missed almost every real entry.
    tanks = {
        _norm_tank(t.tank_name, protect): (t.bilge_pump_capacity_m3_per_hr or 2.0)
        for t in tanks_all if _get_effective_group(t) == "BILGE"
    }
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
        pump_cap = tanks.get(_norm_tank(qty.from_tank, protect))
        if not pump_cap: continue
        start, stop = _parse_time(entry.time_start), _parse_time(entry.time_stop)
        if start is None or stop is None: continue
        hours = ((stop - start) if stop >= start else ((1440 - start) + stop)) / 60.0
        if hours <= 0: continue
        if qty.qty_value > (pump_cap * hours + 0.05):
            msg = f"[{entry.entry_date}] Disposed quantity {qty.qty_value}m³ exceeds {pump_cap}m³/hr pump capacity limit."
            await create_alert_if_new(db, vessel_id, entry.id, "bilge_pump_capacity", "major", msg)

# ─────────────────────────────────────────────────────────────────────────
# Check 10 — Bunker Mismatch
# ─────────────────────────────────────────────────────────────────────────
async def check_bunker_mismatch(vessel_id: uuid.UUID, upload_id: uuid.UUID | None, db: AsyncSession):
    q_filter = and_(OrbEntry.vessel_id == vessel_id, OrbEntry.orb_code == BUNKER_ORB_CODE, OrbEntry.item_number.in_(BUNKER_ITEMS))
    if upload_id: q_filter = and_(q_filter, OrbEntry.upload_id == upload_id)
    res = await db.execute(select(OrbEntry).where(q_filter))
    for entry in res.scalars().all():
        qty_res = await db.execute(select(OrbEntryQuantity).where(OrbEntryQuantity.entry_id == entry.id, OrbEntryQuantity.qty_type == "bunkered"))
        bunkered = qty_res.scalars().all()

        # A bunker entry may state an overall header total (to_tank=null) plus a
        # per-tank breakdown (to_tank=<tank>) — see IMO guidance Example #18/#19.
        header_total = next((q.qty_value for q in bunkered if not q.to_tank), None)
        tank_splits = [q for q in bunkered if q.to_tank]
        split_sum = sum(q.qty_value for q in tank_splits)
        total_qty = header_total if header_total is not None else split_sum

        desc = entry.operation_description or ""
        is_lube = entry.item_number == "26.4"
        missing_grade = False if is_lube else not re.search(r"\b(VLSFO|HSFO|MGO|MDO|LSMGO|IFO|ULSFO)\b", desc, re.I)
        if total_qty <= 0 or missing_grade or not re.search(r"[A-Za-z0-9]{6,}", desc):
            msg = f"[{entry.entry_date}] Bunker entry missing essential details/specification grades."
            await create_alert_if_new(db, vessel_id, entry.id, "bunker_mismatch", "minor", msg)

        # Self-contained quantity check: does the per-tank breakdown add up to the
        # header total actually written on the page? No external reference needed.
        if header_total is not None and tank_splits and abs(split_sum - header_total) > 0.5:
            msg = (f"[{entry.entry_date}] Bunker quantity mismatch: total bunkered "
                   f"{header_total:.2f} vs per-tank breakdown sums to {split_sum:.2f}.")
            await create_alert_if_new(db, vessel_id, entry.id, "bunker_quantity_mismatch", "major", msg)

# ─────────────────────────────────────────────────────────────────────────
# Check 11 — Missing Master Signature (Aggregated)
# ─────────────────────────────────────────────────────────────────────────
async def check_missing_master_signature(vessel_id: uuid.UUID, upload_id: uuid.UUID | None, db: AsyncSession):
    if not upload_id: return
    result = await db.execute(select(OrbEntry.page_number).where(
        OrbEntry.vessel_id == vessel_id, OrbEntry.upload_id == upload_id,
        or_(OrbEntry.master_signature_present.is_(False), OrbEntry.master_signature_present.is_(None)),
    ))
    pages = sorted({p for (p,) in result.all() if p is not None})
    if not pages:
        return
    page_list = ", ".join(str(p) for p in pages)
    label = "page" if len(pages) == 1 else "pages"
    msg = f"Master/Officer signature not detected on {label} {page_list} in this upload batch."
    await create_alert_if_new(db, vessel_id, None, "missing_master_signature", "minor", msg)

# ─────────────────────────────────────────────────────────────────────────
# Check 12 — Chronology and Erasures
# ─────────────────────────────────────────────────────────────────────────
async def check_chronology_and_erasures(vessel_id: uuid.UUID, upload_id: uuid.UUID | None, db: AsyncSession):
    q_filter = OrbEntry.vessel_id == vessel_id
    if upload_id: q_filter = and_(q_filter, OrbEntry.upload_id == upload_id)
    # NOTE: order by page_number (true physical document order), not created_at.
    # All entries from one upload are inserted in the same DB transaction, so
    # Postgres' now() gives every row an identical created_at timestamp -- the
    # ORDER BY then falls back to an arbitrary tie-break that does NOT reliably
    # match page order, producing false "out of order" alerts on a perfectly
    # sequential source document. created_at is kept as the tiebreak for entries
    # that genuinely share a page_number (or have none, e.g. mock/legacy data).
    entries = (await db.execute(
        select(OrbEntry).where(q_filter).order_by(OrbEntry.page_number, OrbEntry.created_at)
    )).scalars().all()
    # Compare each entry's date against the highest date seen on any STRICTLY
    # EARLIER page, not against its immediate neighbour in this list. Entries
    # within the same physical page are not reliably returned in true
    # top-to-bottom reading order by the extractor (multiple blocks on one
    # page can legitimately come back in a different order than they were
    # written), so policing order within a page produces false positives on
    # a perfectly sequential source document. A real chronology violation --
    # a later page actually going backward in time -- is still caught, since
    # that comparison is against the running max from completed prior pages.
    max_date_prior_pages = None
    current_page = object()  # sentinel, not equal to any real page_number
    page_max_date = None
    for entry in entries:
        if entry.page_number != current_page:
            if page_max_date is not None:
                max_date_prior_pages = page_max_date if max_date_prior_pages is None else max(max_date_prior_pages, page_max_date)
            current_page = entry.page_number
            page_max_date = None

        if max_date_prior_pages and entry.entry_date < max_date_prior_pages:
            msg = f"[{entry.entry_date}] Entry out of chronological validation order (Previous: {max_date_prior_pages})."
            await create_alert_if_new(db, vessel_id, entry.id, "non_chronological_entry", "minor", msg)
        page_max_date = entry.entry_date if page_max_date is None else max(page_max_date, entry.entry_date)

        if entry.has_erasure:
            # IMO guidance permits corrections: a wrong entry struck through with a
            # single line, then signed and dated, with the corrected entry
            # following, is the COMPLIANT way to fix a mistake -- not itself a
            # violation. The extractor can only detect that a strike-through
            # exists, not whether it was separately signed/dated as required, so
            # this stays an "observation" prompting manual verification rather
            # than asserting improper correction outright.
            msg = (f"[{entry.entry_date}] Erasure or correction mark detected on physical page — "
                   f"verify it was struck through with a single line and separately signed/dated "
                   f"per IMO guidance, not left as an unexplained alteration.")
            await create_alert_if_new(db, vessel_id, entry.id, "erasure_detected", "observation", msg)

# ─────────────────────────────────────────────────────────────────────────
# Check 13 — Gap Between Entries
# ─────────────────────────────────────────────────────────────────────────
async def check_entry_gaps(vessel_id: uuid.UUID, upload_id: uuid.UUID | None, db: AsyncSession):
    """Flags entries preceded by a blank full line (IMO guidance: 'Do not leave
    any full lines empty between successive entries')."""
    q_filter = and_(OrbEntry.vessel_id == vessel_id, OrbEntry.has_gap_before.is_(True))
    if upload_id:
        q_filter = and_(q_filter, OrbEntry.upload_id == upload_id)
    result = await db.execute(select(OrbEntry).where(q_filter))
    for entry in result.scalars().all():
        page = f" (page {entry.page_number})" if entry.page_number else ""
        msg = f"[{entry.entry_date}] Blank line left before this entry{page} — successive entries must not have empty lines between them."
        await create_alert_if_new(db, vessel_id, entry.id, "gap_between_entries", "minor", msg)