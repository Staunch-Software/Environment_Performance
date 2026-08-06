"""Regression tests for the ORB extraction post-processing pipeline.

Every test case here reproduces a REAL confirmed extraction bug found by
manually auditing the "ORB SCAN COPIES.PDF" upload (AM KIRTI vessel) page by
page against the actual scanned photos, plus the fixes made in response to
each one. They exist so a future change to app/services/extraction.py can't
silently re-break any of these without a test failing.

No pytest dependency -- this project has no test infrastructure yet, so this
runs as a plain script: each test_* function is called from main() and
failures are collected and reported at the end, rather than requiring a test
runner to be installed first.

Run with:
    venv/Scripts/python.exe tests/test_extraction_pipeline.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.services.extraction as ext


# ---------------------------------------------------------------------------
# Category 1 — officer fabrication on structurally incomplete entries
# ---------------------------------------------------------------------------

def test_propagate_shared_officer_skips_truncated_entry():
    """Confirmed case: an 11-JAN-2026 Code D bilge-pumping entry was cut off
    by a page crop before its quantities/signature were ever read. The
    day's OTHER entries were all co-signed by the same officer, and the
    pipeline used to fill that officer in anyway -- masking the fact the
    entry's real operational data (how much water, how much retained) is
    missing. It must stay unfilled."""
    entries = [
        {"entry_date": "11-JAN-2026", "orb_code": "D", "item_number": "13",
         "officer_1_name": "SONU KUMAR", "officer_1_rank": "2/E",
         "officer_2_name": "RISHIKESH JAMDAR", "officer_2_rank": "C/E",
         "quantities": [{"qty_type": "transferred", "qty_value": 3.3},
                        {"qty_type": "capacity", "qty_value": 89.2},
                        {"qty_type": "retained", "qty_value": 22.4}]},
        {"entry_date": "11-JAN-2026", "orb_code": "D", "item_number": "13",
         "officer_1_name": None, "officer_1_rank": None,
         "officer_2_name": None, "officer_2_rank": None,
         "quantities": [{"qty_type": "transferred", "qty_value": 2.0}]},  # transferred w/ no retained pair
    ]
    out = ext._propagate_shared_officer(entries)
    assert out[1]["officer_2_name"] is None, "officer fabricated on an incomplete entry"


def test_propagate_shared_officer_still_fills_legitimate_gaps():
    """Sanity check the fix above didn't break the original, legitimate
    behavior: a genuinely complete entry with a blank signature (because
    the day's single shared signature landed on a neighboring row) should
    still get filled in."""
    entries = [
        {"entry_date": "03-JAN-2026", "orb_code": "C", "item_number": "11.1",
         "officer_1_name": "SONU KUMAR", "officer_1_rank": "2/E",
         "officer_2_name": "RISHIKESH JAMDAR", "officer_2_rank": "C/E",
         "quantities": [{"qty_type": "capacity", "qty_value": 5.0}, {"qty_type": "retained", "qty_value": 1.0}]},
        {"entry_date": "03-JAN-2026", "orb_code": "C", "item_number": "11.1",
         "officer_1_name": None, "officer_1_rank": None,
         "officer_2_name": None, "officer_2_rank": None,
         "quantities": [{"qty_type": "capacity", "qty_value": 3.0}, {"qty_type": "retained", "qty_value": 0.5}]},
    ]
    out = ext._propagate_shared_officer(entries)
    assert out[1]["officer_2_name"] == "RISHIKESH JAMDAR", "legitimate propagation broke"


def test_looks_structurally_incomplete_transferred_without_retained():
    """A 'transferred' quantity with no paired 'retained' figure at all
    (the QUANTITY RULES section requires both) is a truncation signal even
    when SOME quantity is present -- catches a gap the first version of
    this check (pure 'zero quantities') missed."""
    entry = {"orb_code": "D", "item_number": "13", "quantities": [{"qty_type": "transferred", "qty_value": 2.0}]}
    assert ext._looks_structurally_incomplete(entry) is True


def test_looks_structurally_incomplete_legit_disposed_overboard():
    """A genuine 15.1/15.2 overboard discharge has no retained figure at
    all -- must NOT be flagged incomplete just for lacking one."""
    entry = {"orb_code": "D", "item_number": "13", "quantities": [{"qty_type": "disposed", "qty_value": 5.0}]}
    assert ext._looks_structurally_incomplete(entry) is False


# ---------------------------------------------------------------------------
# Category 2 — officer roster hint (page-level voting, not entry-level)
# ---------------------------------------------------------------------------

def test_officer_roster_single_page_cannot_seed_itself():
    """CONFIRMED REGRESSION, now fixed: page 1 had 5 entries that all
    repeated ONE misread signature ("RAKESH JAMDAR" instead of the correct
    "RISHIKESH JAMDAR"). The first version of the roster counted each
    entry as a vote, so one bad page alone cleared the threshold and then
    dragged every later, otherwise-correct page toward the same wrong
    spelling. A single page must never be enough on its own."""
    roster = {}
    five_entries_one_page = [
        {"confidence_score": 0.9, "officer_1_name": None, "officer_1_rank": None,
         "officer_2_name": "RAKESH JAMDAR", "officer_2_rank": "C/E"}
        for _ in range(5)
    ]
    ext._update_officer_roster(roster, five_entries_one_page)
    assert ext._build_officer_roster_hint(roster) == "", "one page alone seeded the roster"


def test_officer_roster_majority_across_pages_wins():
    """Once 3 independent pages agree, the roster hint should reflect
    their (correct) consensus even if one earlier page disagreed."""
    roster = {}
    ext._update_officer_roster(roster, [{"confidence_score": 0.9, "officer_1_name": None, "officer_1_rank": None,
                                          "officer_2_name": "RAKESH JAMDAR", "officer_2_rank": "C/E"}])
    for _ in range(3):
        ext._update_officer_roster(roster, [{"confidence_score": 0.9, "officer_1_name": None, "officer_1_rank": None,
                                              "officer_2_name": "RISHIKESH JAMDAR", "officer_2_rank": "C/E"}])
    hint = ext._build_officer_roster_hint(roster)
    assert "RISHIKESH JAMDAR" in hint


# ---------------------------------------------------------------------------
# Category 2/6 — tank capacity roster + retained-exceeds-capacity sanity flag
# ---------------------------------------------------------------------------

def test_capacity_roster_hint_built_from_page_votes():
    roster = {}
    for _ in range(3):
        ext._update_capacity_roster(roster, [{"confidence_score": 0.9, "tank_location": "L.O. SLUDGE TANK",
                                               "quantities": [{"qty_type": "capacity", "qty_value": 19.1}]}])
    hint = ext._build_capacity_roster_hint(roster)
    assert "19.1" in hint and "SLUDGE" in hint


def test_retained_exceeds_capacity_is_flagged_not_corrected():
    """A tank can't retain more than its own capacity -- physically
    impossible, must lower confidence for review, never silently guess
    which figure is wrong."""
    entry = {"entry_date": "X", "orb_code": "D", "tank_location": "BILGE HOLDING TANK", "confidence_score": 0.9,
             "quantities": [{"qty_type": "capacity", "qty_value": 10.0}, {"qty_type": "retained", "qty_value": 50.0}]}
    out = ext._flag_retained_exceeds_capacity([entry])
    assert out[0]["confidence_score"] <= 0.4


def test_retained_within_capacity_is_untouched():
    entry = {"entry_date": "X", "orb_code": "D", "tank_location": "BILGE HOLDING TANK", "confidence_score": 0.9,
             "quantities": [{"qty_type": "capacity", "qty_value": 89.2}, {"qty_type": "retained", "qty_value": 16.1}]}
    out = ext._flag_retained_exceeds_capacity([entry])
    assert out[0]["confidence_score"] == 0.9


# ---------------------------------------------------------------------------
# Category 3 — entry_date vs. its own header self-consistency
# ---------------------------------------------------------------------------

def test_entry_date_corrected_when_own_text_is_self_consistent():
    """CONFIRMED CASE: header and both signatures all read 01-FEB-2026 with
    no disagreement anywhere in the entry's own text, yet the separate
    entry_date field was stuck at 31-JAN-2026 (confidence 0.9, so the
    older confidence-gated reconciliation never even looked at it). This
    is a field-sync bug, not a legibility judgment call -- must always
    correct regardless of confidence."""
    entry = {"entry_date": "31-JAN-2026", "orb_code": "C",
             "raw_text": "01 FEB 2026 C 12.2 0.4 m3 SLUDGE...\nRAKESH JAMDAR C/E 01-FEB-26\nNEERAJ SAINI 3/E 01-FEB-26"}
    out = ext._reconcile_entry_date_vs_own_header([entry])
    assert "01-FEB" in out[0]["entry_date"].upper()


def test_entry_date_left_alone_when_text_itself_disagrees():
    """Genuine ambiguity (header says one date, BOTH signatures say a
    different one) must be left to the confidence-gated majority-vote
    function instead -- this unconditional check only fires on internally
    self-consistent text."""
    entry = {"entry_date": "06-JAN-2026", "orb_code": "C",
             "raw_text": "06 JAN 2026 C 12.2 ...\nSONU KUMAR 2/E 07 JAN 2026\nRISHIKESH JAMDAR C/E 07 JAN 2026"}
    out = ext._reconcile_entry_date_vs_own_header([entry])
    assert out[0]["entry_date"] == "06-JAN-2026"


# ---------------------------------------------------------------------------
# Category 4 — capacity correction rewrites the visible text, not just a note
# ---------------------------------------------------------------------------

def test_capacity_mention_rewritten_inline():
    desc = "TO BILGE HOLDING TANK\nCAP. 18.9 m3 RETD.: 13.8 m3."
    new_desc, replaced = ext._rewrite_capacity_mention(desc, 18.9, 89.2)
    assert replaced
    assert "89.2" in new_desc
    assert "18.9" not in new_desc.split("[")[0]  # old value gone from the primary text, only in the note


def test_capacity_correction_end_to_end_updates_description():
    entries = [
        {"tank_location": "L.O. DRAIN TANK", "confidence_score": 0.9,
         "operation_description": "L.O. DRAIN TANK\nCAP: 3.3 m3", "raw_text": "CAP: 3.3 m3",
         "quantities": [{"qty_type": "capacity", "qty_value": 3.3}]},
        {"tank_location": "L.O. DRAIN TANK", "confidence_score": 0.9,
         "operation_description": "L.O. DRAIN TANK\nCAP: 3.3 m3", "raw_text": "CAP: 3.3 m3",
         "quantities": [{"qty_type": "capacity", "qty_value": 3.3}]},
        {"tank_location": "L.O. DRAIN TANK", "confidence_score": 0.9,
         "operation_description": "L.O. DRAIN TANK\nCAP: 8.2 m3", "raw_text": "CAP: 8.2 m3",
         "quantities": [{"qty_type": "capacity", "qty_value": 8.2}]},
    ]
    out = ext._reconcile_tank_capacity_readings(entries)
    assert "3.3" in out[2]["operation_description"]
    assert "8.2 m3 -- this tank's capacity" in out[2]["operation_description"]  # note still present


# ---------------------------------------------------------------------------
# Category 5 — dedup must not collapse genuinely separate same-tank-pair transfers
# ---------------------------------------------------------------------------

def test_dedupe_keeps_two_real_transfers_sharing_one_coincidental_value():
    """CONFIRMED CASE: two genuinely separate 19-JAN-2026 12.2 transfers
    between the same tank pair, both happening to move 0.9 m3 (a very
    common recurring amount on this vessel) but with different retained
    figures (6.9 vs 6.0). The old rule (any single shared qty pair = same
    block) silently dropped one of them."""
    e1 = {"entry_date": "19-JAN-2026", "orb_code": "C", "item_number": "12.2", "tank_location": "OILY BILGE TANK",
          "quantities": [{"qty_type": "transferred", "qty_value": 0.9, "to_tank": "INCINERATOR WASTE OIL SETTLING TANK"},
                         {"qty_type": "retained", "qty_value": 6.9}, {"qty_type": "retained", "qty_value": 0.9}]}
    e2 = {"entry_date": "19-JAN-2026", "orb_code": "C", "item_number": "12.2", "tank_location": "OILY BILGE TANK",
          "quantities": [{"qty_type": "transferred", "qty_value": 0.9, "to_tank": "INCINERATOR WASTE OIL SETTLING TANK"},
                         {"qty_type": "retained", "qty_value": 6.0}]}
    out = ext._dedupe_same_page_entries([e1, e2])
    assert len(out) == 2, "two genuinely distinct entries were wrongly merged"


def test_dedupe_still_merges_a_genuine_same_block_duplicate():
    """Sanity check the tightened rule still catches what it was built
    for: the SAME physical block extracted twice, one copy fuller than
    the other."""
    e1 = {"entry_date": "18-MAR-2026", "orb_code": "D", "item_number": "13", "tank_location": "E/R BILGE WELLS",
          "quantities": [{"qty_type": "transferred", "qty_value": 3.9, "to_tank": "BILGE HOLDING TANK"},
                         {"qty_type": "retained", "qty_value": 9.6}]}
    e2 = {"entry_date": "18-MAR-2026", "orb_code": "D", "item_number": "13", "tank_location": "E/R BILGE WELLS",
          "quantities": [{"qty_type": "transferred", "qty_value": 3.9, "to_tank": "BILGE HOLDING TANK"}]}
    out = ext._dedupe_same_page_entries([e1, e2])
    assert len(out) == 1, "genuine duplicate no longer merged"


# ---------------------------------------------------------------------------
# Category 1 (structural) — boundary re-check for missed continuations
# ---------------------------------------------------------------------------

def test_crop_top_strip_dimensions():
    from PIL import Image
    img = Image.new("RGB", (800, 1200), color="white")
    strip = ext._crop_top_strip(img)
    assert strip.size == (800, int(1200 * ext._BOUNDARY_STRIP_FRACTION))


def test_boundary_recheck_parses_a_found_continuation():
    from PIL import Image

    class _Resp:
        text = (
            '{"continuation": {"text": "TANK, RETAINED 2.95 M3", '
            '"tank_location": "WASTE OIL SETTLING TANK", '
            '"quantities": [{"qty_type": "retained", "qty_value": 2.95, "qty_unit": "m3"}], '
            '"officer_1_name": "NEERAJ SAINI", "officer_1_rank": "3E", '
            '"officer_2_name": null, "officer_2_rank": null, '
            '"time_start": null, "time_stop": null, "position_start": null, "position_stop": null}}'
        )

    class _Models:
        def generate_content(self, **kwargs):
            return _Resp()

    class _Client:
        models = _Models()

    result = ext._call_boundary_recheck(_Client(), Image.new("RGB", (800, 1200)))
    assert result is not None
    assert result["tank_location"] == "WASTE OIL SETTLING TANK"
    assert result["quantities"][0]["qty_value"] == 2.95


def test_boundary_recheck_returns_none_on_null_continuation():
    from PIL import Image

    class _Resp:
        text = '{"continuation": null}'

    class _Models:
        def generate_content(self, **kwargs):
            return _Resp()

    class _Client:
        models = _Models()

    assert ext._call_boundary_recheck(_Client(), Image.new("RGB", (800, 1200))) is None


def test_boundary_recheck_fails_gracefully_on_api_error():
    from PIL import Image

    class _Models:
        def generate_content(self, **kwargs):
            raise RuntimeError("simulated API failure")

    class _Client:
        models = _Models()

    assert ext._call_boundary_recheck(_Client(), Image.new("RGB", (800, 1200))) is None


# ---------------------------------------------------------------------------
# Category 1 (backstop) — fused two-operations-in-one-entry detector
# ---------------------------------------------------------------------------

def test_fused_entry_is_flagged():
    """CONFIRMED CASE: a 30-JAN-2026 Code D entry's raw_text contained its
    own genuine continuation AND a second, unrelated 31-JAN-2026 entry's
    full content, glued together -- 4 rank tokens, 2 distinct dates."""
    entry = {
        "entry_date": "30-JAN-2026", "orb_code": "D", "tank_location": "BILGE HOLDING TANK",
        "confidence_score": 0.9,
        "raw_text": (
            "2.8 m3 BILGE WATER FROM BILGE HOLDING TANK CAP: 89.2 m3 RETD.: 13.3 m3 "
            "START: 0054 HRS UTC STOP: 0152 HRS UTC THROUGH 15 PPM EQUIPMENT OVERBOARD "
            "3E NEERAJ SAINI / C/E RAKESH JAMDAR 30 JAN 26 "
            "M.E. VENKATESH 2/E 31-JAN-2026 14 START: 0545 HRS UTC STOP: 0628 HRS UTC "
            "15.1 THROUGH 15 PPM EQUIPMENT OVERBOARD C/E RAKESH JAMDAR / 2/E M.E. VENKATESH 31 JAN 26"
        ),
    }
    out = ext._flag_fused_continuation_entries([entry])
    assert out[0]["confidence_score"] <= 0.3


def test_normal_two_officer_entry_is_not_flagged():
    entry = {
        "entry_date": "03-JAN-2026", "orb_code": "C", "tank_location": "OILY BILGE TANK",
        "confidence_score": 0.9,
        "raw_text": "03 JAN 2026 C 11.1 OILY BILGE TANK\n11.2 25.6 m3\n11.3 7.2 m3\n"
                     "SONU KUMAR 2/E 03 JAN 2026\nRISHIKESH JAMDAR C/E 03 JAN 2026",
    }
    out = ext._flag_fused_continuation_entries([entry])
    assert out[0]["confidence_score"] == 0.9


def test_legitimate_lagged_signature_is_not_flagged():
    """A real entry where one officer's own signature date legitimately
    lags a day (only 2 rank tokens total) must not be treated as fused --
    that's a different, already-handled case."""
    entry = {
        "entry_date": "08-MAR-2026", "orb_code": "C", "tank_location": "X",
        "confidence_score": 0.9,
        "raw_text": "08 MAR 2026 C 11.1 X TANK\n11.2 5.0 m3\n11.3 1.0 m3\n"
                     "3E A.NAME 08 MAR 2026\nC/E B.NAME 07 MAR 2026",
    }
    out = ext._flag_fused_continuation_entries([entry])
    assert out[0]["confidence_score"] == 0.9


# ---------------------------------------------------------------------------
# Category 7 — a corrected entry must never look MORE trustworthy than it is
# ---------------------------------------------------------------------------

def test_large_capacity_correction_drops_confidence_hard():
    """CONFIRMED CASE: a capacity misread of this size (19.1 -> 40.8) was
    actually a tank-identity mix-up (L.O. Sludge Tank read as F.O. Sludge
    Tank), not a simple digit slip -- must not be left at high confidence
    just because the number now matches SOME tank's typical value."""
    entries = [
        {"tank_location": "F.O. SLUDGE TANK", "confidence_score": 0.9, "operation_description": "CAP 40.8",
         "raw_text": "CAP 40.8", "quantities": [{"qty_type": "capacity", "qty_value": 40.8}]},
        {"tank_location": "F.O. SLUDGE TANK", "confidence_score": 0.9, "operation_description": "CAP 40.8",
         "raw_text": "CAP 40.8", "quantities": [{"qty_type": "capacity", "qty_value": 40.8}]},
        {"tank_location": "F.O. SLUDGE TANK", "confidence_score": 0.9, "operation_description": "CAP 19.1",
         "raw_text": "CAP 19.1", "quantities": [{"qty_type": "capacity", "qty_value": 19.1}]},
    ]
    out = ext._reconcile_tank_capacity_readings(entries)
    assert out[2]["confidence_score"] <= 0.4


def test_small_capacity_correction_drops_confidence_mildly():
    entries = [
        {"tank_location": "L.O. SLUDGE TANK", "confidence_score": 0.9, "operation_description": "CAP 19.1",
         "raw_text": "CAP 19.1", "quantities": [{"qty_type": "capacity", "qty_value": 19.1}]},
        {"tank_location": "L.O. SLUDGE TANK", "confidence_score": 0.9, "operation_description": "CAP 19.1",
         "raw_text": "CAP 19.1", "quantities": [{"qty_type": "capacity", "qty_value": 19.1}]},
        {"tank_location": "L.O. SLUDGE TANK", "confidence_score": 0.9, "operation_description": "CAP 18.9",
         "raw_text": "CAP 18.9", "quantities": [{"qty_type": "capacity", "qty_value": 18.9}]},
    ]
    out = ext._reconcile_tank_capacity_readings(entries)
    assert out[2]["confidence_score"] == 0.7


# ---------------------------------------------------------------------------
# Crash fixes — malformed Gemini response shapes must never take down the
# whole extraction run
# ---------------------------------------------------------------------------

def test_sanitize_drops_non_dict_entries():
    """CONFIRMED PRODUCTION CRASH: a malformed item in Gemini's own
    "entries" array (not an object) propagated through a dozen+ downstream
    .get() calls with no type check anywhere, crashing the entire upload's
    extraction -- not just that one page."""
    raw = [{"entry_date": "X", "orb_code": "C", "quantities": []}, "a malformed string entry", 42]
    out = ext._sanitize_page_entries(raw, page_num=1)
    assert len(out) == 1
    assert out[0]["entry_date"] == "X"


def test_sanitize_drops_non_dict_quantities():
    raw = [{"entry_date": "X", "orb_code": "C",
            "quantities": [{"qty_type": "capacity", "qty_value": 1.0}, "bad", None, 5]}]
    out = ext._sanitize_page_entries(raw, page_num=1)
    assert len(out[0]["quantities"]) == 1
    assert out[0]["quantities"][0]["qty_type"] == "capacity"


def test_sanitize_handles_entirely_non_list_entries_field():
    """If "entries" itself isn't a list at all (e.g. Gemini returned a bare
    string for the whole field), must return an empty list, not crash."""
    out = ext._sanitize_page_entries("not a list", page_num=1)
    assert out == []


# ---------------------------------------------------------------------------
# Vessel-mismatch guard — the uploaded PDF's own "NAME OF SHIP" header must
# match the vessel selected in the upload form
# ---------------------------------------------------------------------------

def test_vessel_names_genuine_mismatch_detected():
    """CONFIRMED CASE: an AMNS POLAR document was uploaded against the AM
    KIRTI vessel record and silently extracted/stored under the wrong
    vessel -- must be detected as a real mismatch."""
    assert ext._vessel_names_plausibly_match("AMNS POLAR", "AM KIRTI") is False


def test_vessel_names_exact_and_noisy_matches_allowed():
    assert ext._vessel_names_plausibly_match("AM KIRTI", "AM KIRTI") is True
    assert ext._vessel_names_plausibly_match("am kirti", "AM KIRTI") is True
    assert ext._vessel_names_plausibly_match("AM  KIRTI ", "AM KIRTI") is True
    assert ext._vessel_names_plausibly_match("M.V. AM KIRTI", "AM KIRTI") is True


def test_vessel_names_missing_data_never_blocks():
    assert ext._vessel_names_plausibly_match("", "AM KIRTI") is True
    assert ext._vessel_names_plausibly_match("AM KIRTI", "") is True


def test_vessel_mismatch_error_message_names_both_vessels():
    err = ext.VesselMismatchError("AMNS POLAR", "AM KIRTI")
    assert "AMNS POLAR" in str(err) and "AM KIRTI" in str(err)


def test_detect_vessel_name_parses_response():
    from PIL import Image

    class _Resp:
        text = '{"ship_name": "AMNS POLAR"}'

    class _Models:
        def generate_content(self, **kwargs):
            return _Resp()

    class _Client:
        models = _Models()

    assert ext._detect_vessel_name(_Client(), Image.new("RGB", (800, 1200))) == "AMNS POLAR"


def test_detect_vessel_name_handles_null_and_failure():
    from PIL import Image

    class _RespNull:
        text = '{"ship_name": null}'

    class _ModelsNull:
        def generate_content(self, **kwargs):
            return _RespNull()

    class _ClientNull:
        models = _ModelsNull()

    assert ext._detect_vessel_name(_ClientNull(), Image.new("RGB", (800, 1200))) is None

    class _ModelsFail:
        def generate_content(self, **kwargs):
            raise RuntimeError("boom")

    class _ClientFail:
        models = _ModelsFail()

    assert ext._detect_vessel_name(_ClientFail(), Image.new("RGB", (800, 1200))) is None


# ---------------------------------------------------------------------------
# Quantity-value coercion — a unit baked into the value string must not
# take the whole entry down
# ---------------------------------------------------------------------------

def test_coerce_qty_value_strips_embedded_unit():
    """CONFIRMED CASE: Gemini returned qty_value="3.3m3" (unit inside the
    same field) instead of qty_value=3.3, qty_unit="m3". A bare float()
    call on this raised and took the ENTIRE entry down with it, not just
    this one quantity."""
    assert ext._coerce_qty_value("3.3m3") == 3.3


def test_coerce_qty_value_normal_cases():
    assert ext._coerce_qty_value(5) == 5.0
    assert ext._coerce_qty_value(2.8) == 2.8
    assert ext._coerce_qty_value("7.2") == 7.2


def test_coerce_qty_value_genuinely_unparseable_returns_none():
    assert ext._coerce_qty_value("not a number") is None
    assert ext._coerce_qty_value(None) is None


# ---------------------------------------------------------------------------

def main():
    tests = [obj for name, obj in sorted(globals().items()) if name.startswith("test_") and callable(obj)]
    passed, failed = [], []
    for t in tests:
        try:
            t()
            passed.append(t.__name__)
        except AssertionError as e:
            failed.append((t.__name__, str(e)))
        except Exception as e:
            failed.append((t.__name__, f"{type(e).__name__}: {e}"))

    print(f"\n{'='*70}\n{len(passed)} passed, {len(failed)} failed (of {len(tests)} total)\n{'='*70}")
    for name in passed:
        print(f"  PASS  {name}")
    for name, msg in failed:
        print(f"  FAIL  {name}: {msg}")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
