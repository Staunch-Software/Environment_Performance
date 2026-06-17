"""Daily log calculation service."""
import re
import uuid
from collections import defaultdict
from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.orb_entry import OrbEntry
from app.models.orb_entry_quantity import OrbEntryQuantity
from app.models.vessel_tank import VesselTank


# ── Tank name matching ──────────────────────────────────────────────────────
# Generic structural words carry no discriminating power between tanks — every
# tank is a "TANK" holding "OIL", so matching on them is what caused free-text
# names to be misrouted to the first tank in the list. They are ignored when
# scoring; distinctive words (BILGE, SLUDGE, WASTE, DRAIN, …) do the work.
_GENERIC_TOKENS = {"TANK", "TK", "OIL", "NO", "THE", "OF", "AND", "FOR"}

# Minimum match score (F1 over distinctive tokens). Below this we return None
# rather than guessing — an unmatched value is shown as "Unknown" instead of
# being silently attributed to the wrong tank/group.
_MATCH_THRESHOLD = 0.5


def _tokenize(s: str) -> list[str]:
    return [t for t in re.split(r"[^A-Z0-9]+", s.upper()) if t]


def _tokens_match(a: str, b: str) -> bool:
    """True if two tokens are equal or one is an abbreviation (prefix) of the
    other — handles SEP↔SEPARATE, COMP↔COMPARTMENT, SETT↔SETTLING, etc."""
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 3 and long.startswith(short)


def _score(text_tokens: list[str], tank_tokens: list[str]) -> float:
    """F1 score over distinctive (non-generic) tokens.

    Recall rewards covering the query's distinctive words; precision penalises
    candidate tanks that carry extra distinctive words the query lacks (so
    'BILGE TANK' beats 'BILGE SEPARATE OIL TANK' for the text 'BILGE TANK')."""
    q = [t for t in text_tokens if t not in _GENERIC_TOKENS]
    c = [t for t in tank_tokens if t not in _GENERIC_TOKENS]
    if not q or not c:
        return 0.0

    matched = 0
    used: set[int] = set()
    for qt in q:
        for i, ct in enumerate(c):
            if i in used:
                continue
            if _tokens_match(qt, ct):
                matched += 1
                used.add(i)
                break
    if matched == 0:
        return 0.0

    recall = matched / len(q)
    precision = matched / len(c)
    return 2 * recall * precision / (recall + precision)


def match_tank(free_text: str, tanks: list):
    """Match a free-text tank name to a VesselTank using abbreviation-aware
    token scoring. Returns the best tank above the threshold, else None."""
    if not free_text:
        return None
    text = free_text.upper().strip()

    # 1. Exact name / code match — cheap and unambiguous.
    for t in tanks:
        if t.tank_name.upper().strip() == text or (t.tank_code or "").upper().strip() == text:
            return t

    # 2. Best scored match over distinctive tokens.
    text_tokens = _tokenize(text)
    best, best_score = None, 0.0
    for t in tanks:
        s = _score(text_tokens, _tokenize(t.tank_name))
        if s > best_score:
            best, best_score = t, s

    return best if best_score >= _MATCH_THRESHOLD else None


# ── Operation classification ────────────────────────────────────────────────
# Column routing is driven primarily by the ORB item number, then corroborated
# /corrected by the operation description, then by qty_type — because officers
# sometimes write the wrong item code by hand.
_ASHORE_KW = ("ASHORE", "RECEPTION", "SHORE", "BARGE", "LANDED", "DISPOSAL FACILITY")
_OVERBOARD_KW = ("15 PPM", "15PPM", "OVERBOARD", "O/B", "SEPARATOR", "OWS", "ODM", "OILY WATER")
_BUNKER_GRADES = ("VLSFO", "ULSFO", "LSFO", "HFO", "MGO", "MDO", "LSMGO", "IFO")


def _is_ashore(desc: str) -> bool:
    return any(k in desc for k in _ASHORE_KW)


def _discharge_overboard(entry) -> bool:
    """Decide whether a bilge discharge went overboard via the 15 PPM separator
    (True) or to a shore reception facility (False).

    Priority: item number → description keywords → position (last resort)."""
    item = (entry.item_number or "").strip()
    desc = (entry.operation_description or "").upper()
    if item in ("15.1", "15.2"):
        return True
    if item == "15.3":
        return False
    if _is_ashore(desc):
        return False
    if any(k in desc for k in _OVERBOARD_KW):
        return True
    return bool(entry.position_start)


def detect_grade(desc: str) -> str:
    if not desc:
        return ""
    up = desc.upper()
    for g in _BUNKER_GRADES:
        if g in up:
            return g
    return ""


def classify(entry, qty, tanks):
    """Return (target_column, matched_tank) for a quantity line.

    target_column is one of: sludge_retention, sludge_incineration, evaporation,
    sludge_ashore, bilge_retention, bilge_15ppm, bilge_ashore, bunker, or None
    (capacity / internal transfer / unclassifiable)."""
    qt = (qty.qty_type or "").lower()
    item = (entry.item_number or "").strip()
    desc = (entry.operation_description or "").upper()

    # Capacity lines are reference only — never an output value.
    if qt == "capacity":
        return None, None

    # Bunkering (item 26.3) — goes into a fuel tank (to_tank), often null.
    if qt == "bunkered" or item == "26.3":
        return "bunker", match_tank(qty.to_tank, tanks)

    # Identify the source tank and its group for everything else.
    matched = match_tank(qty.from_tank or entry.tank_location, tanks)
    group = (matched.tank_group or "").upper() if matched else ""
    is_sludge = "SLUDGE" in group
    is_bilge = "BILGE" in group and not is_sludge

    # retained quantities are always a snapshot reading — route them to retention
    # BEFORE checking description keywords, so an evaporation entry's retained
    # sub-quantity doesn't accidentally land in the evaporation column.
    if qt == "retained":
        if is_sludge:
            return "sludge_retention", matched
        if is_bilge:
            return "bilge_retention", matched
        return None, matched

    # Incineration / evaporation — item or description can override a generic
    # qty_type (handles mis-keyed codes). This runs AFTER retained so that a
    # retained sub-quantity on an evaporation entry never ends up here.
    if qt == "incinerated" or item == "12.3" or "INCINERAT" in desc:
        return "sludge_incineration", matched
    # 12.4 = evaporation / boiler burn / regeneration (IMO MEPC.1/Circ.736/Rev.1)
    # 12.5 kept for backward compatibility with data extracted before the fix
    if qt == "evaporated" or item in ("12.4", "12.5") or "EVAPORAT" in desc:
        return "evaporation", matched

    # Transfers are internal movements and don't populate an output column —
    # unless the destination is a shore reception facility (item 15.3 / desc).
    if qt == "transferred":
        if item == "15.3" or _is_ashore(desc):
            if is_sludge:
                return "sludge_ashore", matched
            if is_bilge:
                return "bilge_ashore", matched
        return None, matched

    if qt == "disposed":
        if is_sludge:
            return "sludge_ashore", matched
        if is_bilge:
            return ("bilge_15ppm" if _discharge_overboard(entry) else "bilge_ashore"), matched
        # Group unknown — infer from item/description.
        if item.startswith("15") or "BILGE" in desc:
            return ("bilge_15ppm" if _discharge_overboard(entry) else "bilge_ashore"), matched
        return None, matched

    return None, matched


async def _load_tanks(vessel_id: uuid.UUID, db: AsyncSession):
    result = await db.execute(
        select(VesselTank).where(VesselTank.vessel_id == vessel_id, VesselTank.is_active == True)
    )
    return result.scalars().all()


async def _build_log_core(tanks, entries, db: AsyncSession) -> dict:
    """Shared computation — takes pre-loaded tanks and entries."""

    entry_ids = [e.id for e in entries]

    qty_map: dict[uuid.UUID, list] = defaultdict(list)
    if entry_ids:
        qty_result = await db.execute(
            select(OrbEntryQuantity).where(OrbEntryQuantity.entry_id.in_(entry_ids))
        )
        for q in qty_result.scalars().all():
            qty_map[q.entry_id].append(q)

    by_date: dict[date, list] = defaultdict(list)
    for entry in entries:
        by_date[entry.entry_date].append(entry)

    # ── Build daily rows ──────────────────────────────────────────────────────
    daily_rows = []

    # Running latest-retention per tank across the whole period.
    # These are updated as each day is processed (last write wins per tank)
    # and are used for the monthly summary so we never sum snapshot readings.
    period_sludge_iopp: dict[str, float] = {}      # tank_name -> latest m³
    period_sludge_non_iopp: dict[str, float] = {}
    period_bilge: dict[str, float] = {}

    for day in sorted(by_date.keys()):
        day_entries = by_date[day]

        # Retention is an inventory snapshot — keep the latest reading per tank
        # (dict keyed by tank name, last write wins).
        sludge_iopp: dict[str, float] = {}
        sludge_non_iopp: dict[str, float] = {}
        bilge_ret: dict[str, float] = {}

        sludge_incineration: list = []
        evaporation: list = []
        sludge_ashore: list = []
        bilge_15ppm: list = []
        bilge_ashore: list = []
        bunker_qty: list = []
        bunker_grade = ""
        equipment_failure = 0

        for entry in day_entries:
            # Code F = OWS/OCM failure (per IMO MEPC.1/Circ.736/Rev.1)
            # Code E = automatic bilge pumping (normal operation, not failure)
            if entry.orb_code == "F":
                equipment_failure += 1

            for qty in qty_map.get(entry.id, []):
                target, matched = classify(entry, qty, tanks)
                if target is None:
                    continue

                name = (
                    matched.tank_name if matched
                    else (qty.from_tank or qty.to_tank or entry.tank_location or "Unknown")
                )
                val = qty.qty_value

                if target == "sludge_retention":
                    sludge_iopp.pop(name, None)
                    sludge_non_iopp.pop(name, None)
                    if matched and matched.is_iopp:
                        sludge_iopp[name] = val
                        period_sludge_iopp[name] = val
                    else:
                        sludge_non_iopp[name] = val
                        period_sludge_non_iopp[name] = val

                elif target == "sludge_incineration":
                    sludge_incineration.append({"tank_name": name, "value": val})

                elif target == "evaporation":
                    # Only count evaporation for tanks where it is permitted.
                    if matched and matched.is_evaporation_allowed:
                        evaporation.append({"tank_name": name, "value": val})

                elif target == "sludge_ashore":
                    sludge_ashore.append({"tank_name": name, "value": val})

                elif target == "bilge_retention":
                    bilge_ret[name] = val
                    period_bilge[name] = val

                elif target == "bilge_15ppm":
                    bilge_15ppm.append({"tank_name": name, "value": val})

                elif target == "bilge_ashore":
                    bilge_ashore.append({"tank_name": name, "value": val})

                elif target == "bunker":
                    bunker_qty.append({"tank_name": name or "—", "value": val})
                    if not bunker_grade:
                        bunker_grade = detect_grade(entry.operation_description)

        iopp_list = [{"tank_name": k, "value": v} for k, v in sludge_iopp.items()]
        non_iopp_list = [{"tank_name": k, "value": v} for k, v in sludge_non_iopp.items()]

        daily_rows.append({
            "date": str(day),
            "iopp_retention":         iopp_list,
            "non_iopp_retention":     non_iopp_list,
            "total_sludge_retention": iopp_list + non_iopp_list,
            "sludge_incineration":    sludge_incineration,
            "evaporation":            evaporation,
            "sludge_ashore":          sludge_ashore,
            "bilge_retention":        [{"tank_name": k, "value": v} for k, v in bilge_ret.items()],
            "bilge_15ppm":            bilge_15ppm,
            "bilge_ashore":           bilge_ashore,
            "equipment_failure":      equipment_failure,
            "bunker_qty":             bunker_qty,
            "bunker_grade":           bunker_grade,
        })

    # ── Monthly summary ────────────────────────────────────────────────────────
    # Retention columns = latest snapshot per tank (summing daily snapshots of
    # the same tank would double-count). Event columns (incineration, ashore,
    # 15ppm, evaporation, bunker) = sum of all individual occurrences.
    def sum_events(rows, key):
        return round(sum(item["value"] for row in rows for item in row[key]), 3)

    iopp_total     = round(sum(period_sludge_iopp.values()), 3)
    non_iopp_total = round(sum(period_sludge_non_iopp.values()), 3)

    summary = {
        "date": "TOTAL",
        # Retention — latest snapshot per tank across the period
        "iopp_retention":         iopp_total,
        "non_iopp_retention":     non_iopp_total,
        "total_sludge_retention": round(iopp_total + non_iopp_total, 3),
        # Events — sum of all occurrences
        "sludge_incineration":    sum_events(daily_rows, "sludge_incineration"),
        "evaporation":            sum_events(daily_rows, "evaporation"),
        "sludge_ashore":          sum_events(daily_rows, "sludge_ashore"),
        # Bilge retention — latest snapshot per tank
        "bilge_retention":        round(sum(period_bilge.values()), 3),
        # Bilge events — sum of all occurrences
        "bilge_15ppm":            sum_events(daily_rows, "bilge_15ppm"),
        "bilge_ashore":           sum_events(daily_rows, "bilge_ashore"),
        "equipment_failure":      sum(r["equipment_failure"] for r in daily_rows),
        "bunker_qty":             sum_events(daily_rows, "bunker_qty"),
        "bunker_grade":           "—",
    }

    bunker_total = summary["bunker_qty"]
    sludge_total = summary["total_sludge_retention"]
    summary["sludge_accumulation_ratio"] = (
        round((sludge_total / bunker_total) * 100, 3) if bunker_total > 0 else 0.0
    )

    tank_capacities = {t.tank_name: t.capacity_m3 for t in tanks}

    return {
        "daily_rows": daily_rows,
        "monthly_summary": summary,
        "tank_capacities": tank_capacities,
    }


# ── Public entry points ───────────────────────────────────────────────────────

async def build_daily_log(vessel_id: uuid.UUID, upload_id: uuid.UUID, db: AsyncSession) -> dict:
    """Legacy: filter by upload_id (used by upload-detail endpoint)."""
    from datetime import date as date_type
    tanks = await _load_tanks(vessel_id, db)
    entries_result = await db.execute(
        select(OrbEntry).where(OrbEntry.upload_id == upload_id).order_by(OrbEntry.entry_date)
    )
    entries = entries_result.scalars().all()
    return await _build_log_core(tanks, entries, db)


async def build_daily_log_by_date(
    vessel_id: uuid.UUID,
    date_from,
    date_to,
    db: AsyncSession,
) -> dict:
    """Filter by vessel + optional date range across all uploads."""
    tanks = await _load_tanks(vessel_id, db)
    q = select(OrbEntry).where(OrbEntry.vessel_id == vessel_id)
    if date_from:
        q = q.where(OrbEntry.entry_date >= date_from)
    if date_to:
        q = q.where(OrbEntry.entry_date <= date_to)
    q = q.order_by(OrbEntry.entry_date)
    entries_result = await db.execute(q)
    entries = entries_result.scalars().all()
    return await _build_log_core(tanks, entries, db)
