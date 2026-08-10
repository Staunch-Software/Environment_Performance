"""ORB PDF extraction service — mock and Claude API modes."""
import re
import uuid
import json
import base64
import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select

from sqlalchemy import select as sa_select

from app.config import get_settings
from app.models.orb_upload import OrbUpload
from app.models.orb_entry import OrbEntry
from app.models.orb_entry_quantity import OrbEntryQuantity
from app.models.vessel import Vessel

logger = logging.getLogger(__name__)
settings = get_settings()

import ssl
import certifi
# Only bypass TLS verification when explicitly enabled (see config.DISABLE_SSL_VERIFY).
if settings.DISABLE_SSL_VERIFY:
    ssl._create_default_https_context = ssl._create_unverified_context

EXTRACTION_SYSTEM_PROMPT = """
You are an expert maritime document parser specializing in MARPOL Oil Record Books (ORB) Part I.
Carefully read the ENTIRE page image before writing any output.
Return ONLY a valid JSON object — no explanation, no markdown, no extra text.

ENTRY ORDER: list entries in the "entries" array in the exact top-to-bottom order they appear
on the page. This matters — a downstream process joins the LAST entry in your list to whatever
continuation text appears at the TOP of the next page, so the array order must match the
physical reading order on this page, not the order you happened to transcribe them in.

═══════════════════════════════════════════════════════════════
CRITICAL RULE — WHAT IS ONE ENTRY:
An ORB "entry" is ONE block of operations sharing the same Date + Code column value.
Everything inside that block (multiple item numbers, times, positions, signatures) belongs
to THAT SINGLE entry. Do NOT create separate entries for sub-items within one block.

  ✓ CORRECT — Code C sounding block (3 item numbers = 1 entry):
    Date  C  11.1  SLUDGE TANK
              11.2  6.1 m3
              11.3  2.8 m3
              Signed: 3E M.SATHIK / CE A.SOLANKI
    → ONE entry: tank_location="SLUDGE TANK", quantities=[capacity=6.1, retained=2.8]

  ✓ CORRECT — Code D bilge pumping block (4 item numbers = 1 entry):
    Date  D  13    3.9 m3 bilge water from E/R bilge wells
              14    Start: 0830  Stop: 1000
              15.3  Transferred to BILGE TANK, 9.6 m3 retained
              Signed: 3E / CE
    → ONE entry: time_start="0830", time_stop="1000",
      quantities=[transferred=3.9 from E/R BILGE WELLS to BILGE TANK,
                  retained=9.6 from BILGE TANK]

  ✗ WRONG — Do NOT extract item 14 (times) as a separate entry.
  ✗ WRONG — Do NOT extract item 15.x (position/destination) as a separate entry.
  ✗ WRONG — Do NOT extract item 11.3 alone as a separate entry.

SIGNATURES ARE NOT ENTRIES:
Lines like "3E; M.SATHIK; 28-DEC-2025" or "CE; A.SOLANKI; 04-JAN-2026" are officer
signatures. They are the officer_1/officer_2 fields of the entry above them.
NEVER create a new entry for a signature line.

ENTRY BOUNDARY MID-PAGE — WATCH FOR THIS AFTER EVERY SIGNATURE LINE:
A fresh Date+Code does not only appear at the top of a page — it can appear anywhere,
including immediately after the signature line that closes the block above it, with little
or no visual gap. Once you pass a signature line, you are DONE with that entry — do not keep
folding any further rows into its operation_description/raw_text/quantities, even if the next
row starts right away with no blank line before it. Check the very next row after every
signature: if it has its own Date and Code written (even a short one like "I" with no item
number), it is a brand-new entry and must become its own object in "entries", with its own
tank_location and quantities — never appended onto the block you just closed.
  ✗ WRONG — real failure mode seen in production:
    17-MAY-2026  C  11.1  WASTE OIL TANK NO # 2
                  11.2  CAPACITY - 1.2 m3
                  11.3  RETAINED - 0.4 m3
                  Signed: A.K.RAO / H.SURESAN
    17-MAY-2026  I        WEEKLY INVENTORY OF BILGE TANK
                           CAPACITY - 21.4 m3, RETAINED - 10.5 m3
                  Signed: A.K.RAO / H.SURESAN
    The model appended "WEEKLY INVENTORY OF BILGE TANK..." onto the WASTE OIL TANK NO # 2
    entry's description because the rows sit close together with matching officers — this
    is WRONG. The second row has its own freshly written Date (17-MAY-2026) and Code (I),
    so it MUST be a second, separate entry object, tank_location="BILGE TANK", even though
    both entries share the same date and even the same two signing officers.

LEADING CONTINUATION (entry wrapped across a page break):
Sometimes an entry's block fills the rest of the previous page, and only its tail end
lands at the very TOP of THIS page, before any new Date/Code/Item row appears. That tail
belongs to the LAST entry of the PREVIOUS page — never to anything on this page.

THE TEST: look at the very first ruled line at the top of this page. Does its DATE and CODE
column have a freshly written value on THIS page, or are they blank (nothing written in
those two columns on that line)? Blank Date+Code = this is a continuation, no matter what
else is on that line — an item number, a value, a tank name, a remark, a signature, or any
combination of these. A freshly written Date+Code = this is a genuine new entry, extract it
normally, even if its item number, code, or content looks unusual or incomplete.

The continuation content can be:
  - just the officer signature line(s) (e.g. "3E; M.SATHIK; 28-DEC-2025"), or
  - a fragment finishing a value or word cut off mid-line (e.g. the previous page ends
    "...TRANSFERRED TO BILGE SEPARATED OIL" and this page starts "TANK, 11.6 M3 RETAINED
    IN TANK." — that is NOT a new tank called "Tank" and NOT a new item 11.3 sounding, it
    is simply the rest of the previous sentence), or
  - a longer remark with no Date/Code of its own (e.g. "TO SHORE RECEPTION FACILITY/TRUCK
    AT PORT OF PARADIP, INDIA, BERTH NO. CQ3." finishing a disposal entry — this is NOT a
    new Code I remark just because it has no item number), or
  - a numbered continuation row like item 11.3, 15.3, 26.3 that clearly still belongs to a
    block that STARTED on the previous page (its date/code cell is blank because the block's
    date/code was already written higher up, on the previous page) — this includes any
    quantities, tank name, times, or positions written on that row, or
  - any of the above followed by a signature.

THE MOST-MISSED SHAPE — WATCH FOR THIS ESPECIALLY: a continuation that is JUST a single
item number, ONE value, and a signature — nothing else on the page above the next real entry.
This is overwhelmingly the most common continuation shape for a Code C sounding (11.1/11.2
already written on the previous page, only the closing "11.3 <value>" retained figure and the
signature land on this page) and it is confirmed in production to be the shape most often
missed entirely — not misfiled, not attached to the wrong entry, just absent from the output
altogether, with no leading_continuation reported and no trace of it anywhere. Concretely: if
the very top of this page reads only something like
  "11.3   0.6 m³
   [officer signature line(s)]"
with a blank Date/Code cell and nothing else before the next fresh entry begins, this is NOT
too little content to bother reporting — it is exactly the leading_continuation case, and
losing it silently drops the ONLY retained/capacity figure that tank's sounding will ever
have. A fragment this short is not a sign it's insignificant; short IS the normal shape for
this kind of continuation. Always populate "leading_continuation" for it, with "quantities"
holding that single reading, even when "text" ends up null because there is no separate prose
beyond the numbered line and the signature.

This is still a continuation EVEN IF it contains real data — a tank name, a numeric reading,
a quantity, a time, a position. Having concrete content does NOT make it a new entry; only a
freshly written Date+Code does. Extract that data into the SAME structured shape as a normal
entry's fields (quantities/tank_location/time/position) so nothing is lost, and record it in
the page-level "leading_continuation" object below — never as its own item in "entries".
Do NOT invent an item_number, orb_code for this kind of content, and do
NOT create an entry for it, and do NOT attach it to the first real entry on this page either
(it belongs to the LAST entry of the PREVIOUS page, not the first of this one).
Instead set the page-level "leading_continuation" field to
{"text": "<the raw fragment text finishing the previous entry, or null if only a signature>",
 "tank_location": "<tank name mentioned in the fragment, or null>",
 "time_start": "<hhmm if present, or null>", "time_stop": "<hhmm if present, or null>",
 "position_start": "<lat/lon if present, or null>", "position_stop": "<lat/lon if present, or null>",
 "quantities": [<same shape as an entry's quantities array — qty_type/qty_value/qty_unit/from_tank/to_tank —
   for any reading that appears in this fragment, or [] if none>],
 "officer_1_name":.., "officer_1_rank":.., "officer_2_name":.., "officer_2_rank":..}.
If the top of this page DOES show a freshly written Date+Code (a genuine new entry, or a
normal numbered continuation row like 11.2/11.3 that clearly belongs to a block starting ON
this page), set "leading_continuation": null.

NEVER GLUE TOP-OF-PAGE CONTENT ONTO A DIFFERENT ENTRY LOWER ON THIS PAGE: this is the single
most damaging mistake possible here, worse than either alternative above. A fragment at the
very top of this page belongs ONLY to "leading_continuation" (blank Date+Code) or to its own
genuine new entry (fresh Date+Code) — it must never be silently appended into some OTHER,
unrelated entry's operation_description/raw_text further down this same page just because
they sit close together or share similar wording (see REPEATED NEAR-IDENTICAL BLOCKS above —
near-identical wording is normal on this vessel and is never a reason to merge two blocks).
Confirmed in production: a complete, fully-signed top-of-page fragment got welded onto a
different, later entry's raw_text instead of being reported as leading_continuation, jamming
two different dates' worth of content into one corrupted entry that no downstream check could
untangle. If you are not merging it into "leading_continuation" or emitting it as a standalone
entry, you are making this exact mistake — there is no third option.

NEVER FUSE A TOP-OF-PAGE FRAGMENT INTO A DIFFERENT SIBLING TANK'S ENTRY, AND NEVER INVENT A
QUANTITY TO GIVE IT A "HOME": a specific, repeated variant of the mistake above. Confirmed in
production: the top of a page held a bare "11.3 0.6 m3" continuation (blank Date/Code, closing
a Waste Oil Settling Tank sounding whose tank name and 11.2 capacity were written on the
PREVIOUS page), immediately followed by a genuinely fresh, separately-dated Code C 11.1 entry
for a DIFFERENT, similarly-named tank (Waste Oil SERVICE Tank) with its own tank name, its own
11.2/11.3 values, and its own signature. Instead of reporting the first as leading_continuation
and the second as its own normal entry, the two got fused into ONE entry: labeled with the
SECOND tank's name (Service) but carrying the FIRST tank's retained figure (0.6) — silently
losing the Service Tank's own real retained value entirely, while the Settling Tank sounding
was left with no retained figure at all. Settling/Service (and other near-identical sibling
pairs — see REPEATED NEAR-IDENTICAL BLOCKS and A TRANSFER CAN NEVER HAVE THE SAME TANK ON BOTH
ENDS above) are DIFFERENT tanks with their own independent readings; a bare continuation
fragment with no tank name of its own must go to "leading_continuation" exactly as written,
never folded into whatever full tank entry happens to appear right after it on the page.

A related, equally damaging variant: confirmed in production separately, a bare continuation
fragment consisting of ONLY a closing capacity/retained figure and a signature (its Date+Code
column blank, matching the "MOST-MISSED SHAPE" pattern above) was instead given a FABRICATED
leading quantity value and reported as a brand-new, freshly-dated entry — inventing a
transferred/retained figure that is not actually written anywhere on this page, copied or
guessed from a nearby unrelated reading, purely so the fragment would "look like" a complete
entry. Never do this. If a row's Date and Code cells are genuinely blank, you have no legitimate
source for that row's own leading quantity value — report only the figures actually visible in
that fragment, using "leading_continuation", not a fabricated standalone entry.

THE LAST ENTRY ON A PAGE GETS THE SAME FULL READING AS ANY OTHER: confirmed in production —
the very last block on a page (the row immediately above "Signature of Master:") is where
transcription cuts off prematurely most often, well before the actual bottom edge of the
photo. A real case: "0.3 m3 COLLECTION OF LO RESIDUE FROM [tank name], RETAINED [x] TO OILY
BILGE" followed by a full, clearly legible officer signature line — all of it fully visible in
the photo, nothing cropped or missing — was transcribed only as far as "...COLLECTION OF LO
RESIDUE FROM", with the rest of the sentence, the tank name, the retained figure, and the
entire signature simply never read at all, and officer_1_name/officer_2_name left null despite
the signature being sitting right there in the image. Do not let proximity to the bottom of
the page or to the Master's signature line make you rush or stop early on the LAST block —
finish reading its full sentence and its own officer signature(s) exactly as thoroughly as you
would for a block in the middle of the page, even when it is the final thing on the page.

THE MOST-DROPPED CONTINUATION SHAPE OF ALL — A MULTI-TANK SOUNDING SEQUENCE CUT OFF AFTER
CAPACITY, BEFORE RETAINED: this vessel routinely logs a run of several Code C 11.1 tank
soundings back to back on one page (e.g. Oily Bilge Tank, then L.O. Sludge Tank, then F.O.
Sludge Tank, then Incinerator Waste Oil Settling Tank), each block being tank name → 11.2
capacity → 11.3 retained → two officer signatures. Confirmed in production, repeatedly, across
many different uploads of this document type: when the page's ruled lines run out partway
through the LAST tank in this kind of sequence, the page frequently ends with only the tank
name and its 11.2 capacity value visible — no 11.3 retained figure, no signature — because the
rest of that block is genuinely on the next page, not because you stopped reading early. This
is real and expected, not a mistake to avoid; the mistake is what happens on the OTHER page.
If THIS page's last entry is a Code C 11.1 sounding with only a capacity value and nothing
else (no retained figure, no officer names), extract it exactly as far as it goes — do not
invent a retained figure or officer names for it — but this shape is the single strongest
possible signal that the row immediately following it belongs on the NEXT page as a
leading_continuation, so make sure nothing about how you report this page's own tail causes
that signal to be lost.

GAPS BETWEEN ENTRIES:
IMO guidance requires "Do not leave any full lines empty between successive entries."
This is about a genuinely BLANK RULED LINE with NOTHING written on it at all — not about
normal spacing that is part of every entry's expected layout.

  NOT a gap (has_gap_before = false) — these are NORMAL and appear after every single entry:
    - The officer signature line(s) below an entry (e.g. "3E; M.SATHIK; 28-DEC-2025").
      Every entry has one or two of these. Their presence is required, not a violation.
    - Continuation rows of the SAME entry (item 11.2, 11.3, 15.3, etc. with no date/code
      repeated) — these are not a new entry and not a gap either.
    - Normal line spacing / row height in the table.
  IS a gap (has_gap_before = true) — ONLY this:
    - An entire ruled line, between the end of the previous entry's signature line and the
      start of THIS entry's Date/Code/Item row, that has no date, no code, no item number,
      no text, no signature — completely empty.

Default to false. Only set has_gap_before = true if you can clearly see one or more fully
blank ruled lines separating this entry from the previous entry's signature line. If you are
unsure, or the entries simply follow each other directly (entry → its signature → next entry's
date row, with no blank line physically between them), set false. The first entry on a page
always has has_gap_before = false.

MASTER SIGNATURE (per PAGE, not per entry):
IMO guidance requires "each completed page shall be signed by the master of the ship." Look at
the bottom of THIS page for a line labelled "Signature of Master:" (or similar). Set the
page-level master_signature_present to true only if there is an actual signature/mark/initial
drawn on or immediately after that line — a name alone without a mark does not count, and
neither does a completely blank line. If the page has no such line at all, or the line is
present but empty/unsigned, set false. This single true/false value applies to every entry
extracted from this page.

ERASURES / CORRECTIONS (per entry):
IMO guidance: "If a wrong entry has been recorded, it should immediately be struck through
with a single line in such a way that the wrong entry is still legible. The wrong entry should
be signed and dated, with the new corrected entry following." Set has_erasure = true for an
entry ONLY if you can see an actual strike-through line, cross-out, or correction mark drawn
over part of THIS entry's own SUBSTANTIVE content — its date, code, item number, tank name, a
quantity figure, or a word in the operation description — with the original still legible
underneath. Ordinary messy handwriting, re-inked/traced-over letters, or a name written above
an illegible original are NOT erasures — only a deliberate single-line strike-through over the
entry's own recorded data counts.

DO NOT count marks inside the officer signature/paraph itself (the initials, flourish, or
scribble an officer draws before their rank and name, e.g. in "◠◠◠; 3E; M.SATHIK;
28-DEC-2025"). Officers often have a personal signing mark that includes what looks like a
line or dash through it as part of their normal handwriting style — that is their signature,
not a correction. The tell: if the SAME-looking mark, in the same position right before the
rank/name, appears after multiple different entries on the page (their routine sign-off), it
is a habitual paraph, not an erasure, no matter how many entries it appears under. Only flag
has_erasure when the struck-through content is part of the entry's own data lines (date, code,
item rows, tank name, figures, description) — never the signature line below it.

USE THE CORRECTED VALUE, NOT THE CROSSED-OUT ONE: when a struck-through correction sits on a
field you are about to extract (most critically the DATE, but this applies equally to code,
item number, tank name, or a quantity figure), the field's actual value is whatever the officer
corrected it TO, never the crossed-out original — the original is only still legible so the
correction is auditable, not because it's the value to record. Concretely: if the Date column
shows "18" struck through with "19" written as the correction, entry_date must be the 19th, not
the 18th, even though "18" is what was originally written and is still readable underneath.
Still set has_erasure = true so the correction itself is flagged — but every other field
(entry_date, orb_code, item_number, tank_location, quantities, etc.) must reflect the corrected
reading, never the struck-out one. Getting this backwards silently stores wrong data while
still (correctly) flagging that page for a correction — worse than either mistake alone.

═══════════════════════════════════════════════════════════════
OFFICER NAME CONSISTENCY: the user message for this page may include a "Known officers on
this vessel" list — the names/ranks read (with high confidence) from EARLIER pages of this
SAME logbook. A vessel is normally crewed by a small, stable set of officers across many
consecutive pages, but each page's signature is read independently with no memory of any
other page, so the exact same real person's handwritten signature routinely comes back
spelled a different wrong way on different pages purely from cursive/ink noise (confirmed in
production: one officer's name was misread five different ways — RAKESH, RISHIKEIH,
RISHIKEH, and other variants — across one 40-page document, always the same real person).
When a signature you are reading on THIS page is a close, plausible match for a name on the
roster (small spelling/letter-shape differences consistent with handwriting noise, same
rank), use the roster's exact spelling rather than transcribing a new near-miss variant —
this does not apply to the RANK, which you should still read fresh each time (a person's
rank can change between pages, e.g. after a promotion). Do NOT force a roster match when the
handwriting clearly reads as a different person (a different name shape entirely, not just
noisy letters) — new officers do join partway through a logbook, and inventing agreement with
the roster is exactly as wrong as inventing a new misspelling. If no roster is provided (e.g.
this is the first page processed), or the signature doesn't plausibly match anyone on it,
just read the handwriting as usual.

═══════════════════════════════════════════════════════════════
KNOWN TANK CAPACITIES: the user message for this page may also include a "Known tank
capacities on this vessel" list — capacities read from earlier pages of this SAME logbook. A
tank's physical capacity is a fixed constant, so it is the single most reliable cross-check
available for telling apart two near-identical tank NAMES, which is a confirmed, recurring
misread on this kind of document (e.g. "L.O. SLUDGE TANK" read as "F.O. SLUDGE TANK",
"INCINERATOR WASTE OIL SETTLING TANK" read as "...SERVICE TANK"). If you read a tank name and
its accompanying capacity figure, and that capacity matches a DIFFERENT tank on the roster far
better than the one you read the name as, re-examine the name — you may be misreading a
near-identical sibling tank name. This is a cross-check on the NAME, never a license to alter
a capacity figure you can actually see written: if the page clearly shows a capacity that
doesn't match ANY tank on the roster, it may be a new/different tank, or a genuine misread you
should score with lower confidence per the QUANTITY DIGIT AMBIGUITY guidance above — never
silently substitute the roster's number for what's actually written.

═══════════════════════════════════════════════════════════════
NON-ORB PAGES: not every page glued into this scanned book is a MARPOL Annex I operations
table row. Some vessels' scan files include inserted pages that are a completely different
kind of document — a port reception facility receipt, a customs/waste disposal certificate,
a blank/unused page, an inside cover, or similar. These do NOT have a Date/Code/Item table
structure, and critically do NOT have "officer_1"/"officer_2" in the ORB sense — a receipt's
signatory is a shore-side company/vessel representative, not this ship's engineering officer,
and forcing it into those fields produces a fake-looking but meaningless entry (confirmed in
production: a port reception receipt page got coerced into the schema with a collecting
vessel's name landed in officer_1_name and a misread date four months off from every
surrounding page). If THIS page is clearly not an ORB operations table page, set the
page-level "non_orb_page" to true, "non_orb_page_note" to a short description of what it
actually is (e.g. "Port reception facility waste receipt"), and return "entries": [] — do NOT
attempt to force its content into the entries schema. If this page IS a normal ORB table
page (even a sparse or hard-to-read one), set non_orb_page to false and non_orb_page_note to
null, and extract entries normally.

═══════════════════════════════════════════════════════════════
JSON STRUCTURE — return exactly this:
{
  "page_number": <int>,
  "non_orb_page": <true|false — see NON-ORB PAGES rule above>,
  "non_orb_page_note": "<short description if non_orb_page is true, else null>",
  "master_signature_present": <true|false — see MASTER SIGNATURE rule below>,
  "leading_continuation": {"text":.., "tank_location":.., "time_start":.., "time_stop":..,
    "position_start":.., "position_stop":.., "quantities": [...same shape as entry quantities...],
    "officer_1_name":.., "officer_1_rank":.., "officer_2_name":.., "officer_2_rank":..} or null,
  "entries": [
    {
      "entry_date": "DD-MMM-YYYY",
      "orb_code": "<C|D|E|F|G|H|I>",
      "is_continuation": <true if THIS row's Date and Code columns were blank on the page —
        nothing freshly written there, only an item number and/or a comment/value continuing
        the previous entry — false if this row has a freshly written Date and Code of its own.
        This should almost always be handled via "leading_continuation" above instead of ever
        reaching this array, but if you are including this row here anyway, this field is the
        one honest signal for whether its date/code were invented/inferred rather than actually
        read from the page. Never invent a value for entry_date/orb_code above and then also
        claim is_continuation is false — if you had to guess or copy them from a nearby row
        because the columns were blank, is_continuation must be true.>,
      "item_number": "<lowest item number in block, e.g. 11.1, 12.2, 13, 26.3, or null>",
      "operation_description": "<combined full text of the entire block>",
      "tank_location": "<primary tank name involved, or null>",
      "time_start": "<hhmm or hh:mm string, or null>",
      "time_stop": "<hhmm or hh:mm string, or null>",
      "position_start": "<lat/lon string or null>",
      "position_stop": "<lat/lon string or null>",
      "officer_1_name": "<name from signature line, or null>",
      "officer_1_rank": "<rank e.g. 3E, CE, 2E, or null>",
      "officer_2_name": "<name or null>",
      "officer_2_rank": "<rank or null>",
      "quantities": [
        {
          "qty_type": "<retained|capacity|transferred|disposed|incinerated|evaporated|bunkered|collected>",
          "qty_value": <number, e.g. 2.8>,
          "qty_unit": "<m3|t|l — default m3 if not stated>",
          "from_tank": "<source tank name or null>",
          "to_tank": "<destination tank name, ONLY for transferred/bunkered, else null>"
        }
      ],
      "raw_text": "<complete verbatim text of the entire block including all item lines>",
      "confidence_score": <0.0-1.0>,
      "has_gap_before": <true|false — see GAPS BETWEEN ENTRIES rule below>,
      "has_erasure": <true|false — see ERASURES / CORRECTIONS rule below>
    }
  ]
}

═══════════════════════════════════════════════════════════════
QUANTITY RULES:

qty_type values and when to use them:
  retained    — snapshot of what remains in the tank (11.1/11.3, post-operation balance)
  capacity    — tank capacity reading (11.2 only)
  transferred — liquid moved from one tank to another (12.2, 15.3, Code D pumping to tank)
  disposed    — discharged ashore to reception facility (12.1)
  incinerated — burned in incinerator (12.3)
  evaporated  — evaporated or boiler-burned (12.4)
  bunkered    — fuel/lube oil received (26.3, 26.4)
  collected   — operator-initiated collection (11.4)

from_tank and to_tank rules:
  - from_tank: ALWAYS set to the source tank name. If the block has a tank_location, use it.
    Never leave from_tank null when a tank name is known.
  - to_tank: set ONLY for transferred/bunkered quantities (the destination tank).
    For retained, capacity, disposed, incinerated, evaporated — to_tank MUST be null.
  - Do NOT copy the source tank into to_tank for retained quantities.

  DO NOT LET A SECOND TANK NAME ELSEWHERE IN THE BLOCK BLEED ONTO A DIFFERENT FIGURE'S
  from_tank: when a block mentions TWO tanks (e.g. a Code C 11.1 sounding of tank A whose text
  also has an 11.4 "collected from tank B" clause, or a Code D transfer FROM tank A TO tank B),
  each individual quantity's from_tank must be the tank THAT SPECIFIC figure is actually about —
  never defaulted to whichever tank name happens to appear elsewhere in the same block's text.
  Confirmed in production, twice on the same page: (1) a Code C 11.1 sounding of "OILY BILGE
  TANK" (capacity 25.6 m3, retained 4.3 m3 — both figures unambiguously about Oily Bilge Tank
  itself, matching its own known capacity) also had an 11.4 clause "2.5 m3 COLLECTION OF BILGE
  WATER FROM BILGE HOLDING TANK" — the capacity AND retained figures both got mistagged
  from_tank="BILGE HOLDING TANK" (the OTHER tank named later in the block) instead of "OILY
  BILGE TANK" (the tank they actually describe); only the 11.4 collected figure genuinely
  belongs to Bilge Holding Tank. (2) A Code D transfer "FROM Bilge Holding Tank ... TRANSFERRED
  TO Oily Bilge Tank ... CAP: 89.2 m3" had the capacity figure (89.2 m3, Bilge Holding Tank's
  own well-established capacity) mistagged from_tank="OILY BILGE TANK" (Oily Bilge Tank's real
  capacity is 25.6 m3, nothing like 89.2) simply because "Oily Bilge Tank" was the nearest tank
  name stated in the text before it. Before assigning from_tank on any individual quantity, ask
  specifically WHICH tank that number is a reading of/movement out of — not which tank name most
  recently appeared in the sentence.

Quantity mapping by item/operation type:
  11.1 (sounding start) → capacity + retained for that tank
  11.2 → capacity quantity only
  11.3 → retained quantity only
  11.4 → collected quantity (from_tank = source, to_tank = sludge tank)

  THIS MAPPING IS FIXED BY THE ORB FORM ITSELF, NOT A JUDGMENT CALL: the printed form always
  places a tank sounding's capacity reading on the row labelled "11.2" and its retained reading
  on the row labelled "11.3" — this never varies between vessels, pages, or tanks, so the
  qty_type for each of those two lines is mechanical, not something to infer from the number's
  size or context. Confirmed in production: a sounding's own 11.2 line ("11.2  25.6 m3") was
  tagged qty_type="retained" instead of "capacity" even though its item number was right there
  in the same row — silently mislabeling a tank's fixed physical capacity as if it were a
  fluctuating retained-volume reading, which corrupts every downstream capacity-based check
  (including this vessel's own capacity roster and the retained-cannot-exceed-capacity check
  elsewhere in this pipeline). Before assigning qty_type on any 11.x line, look at which item
  number that specific line carries and map it directly — 11.2 is always "capacity", 11.3 is
  always "retained" — regardless of what the number itself looks like.
  12.1 → disposed (from sludge tank to shore) + retained (remaining in tank)
  12.2 → transferred (from tank A to tank B) + retained (what stays in source tank)
         + optionally retained (new level in destination tank)

  IMPORTANT — 12.2 WITH TWO "RETAINED" FIGURES: when the text gives a retained
  reading for BOTH tanks (e.g. "...0.2 M3 RETAINED IN TANK, TRANSFERRED TO
  BILGE SEPARATED OIL TANK, 11.6 M3 RETAINED IN TANK"), the two retained
  quantities are NOT the same tank. The first retained figure (stated before
  "TRANSFERRED TO") belongs to the SOURCE tank (from the transferred
  quantity's from_tank). The second retained figure (stated after
  "TRANSFERRED TO <tank>") belongs to that DESTINATION tank -- set its
  from_tank explicitly to the destination tank name, never to the source
  tank. Do not leave from_tank null on this second retained quantity and
  rely on it defaulting to the source tank.
  12.3 → incinerated + retained
  12.4 → evaporated + retained
  Code D block (items 13/14/15.x) — ENTIRE block = ONE entry:
    item 13 quantity = how much bilge water was involved
    item 14 = times → time_start / time_stop fields (NOT a quantity)
    item 15.1 or 15.2 → disposed overboard (via 15ppm separator)
    item 15.3 → transferred to holding tank + retained in that tank
    If pumped FROM bilge wells TO holding tank: qty_type=transferred, from=source, to=destination
    If pumped overboard: qty_type=disposed, from=source tank
    Do NOT create both retained AND transferred for the same volume — choose one.
  26.1 → port name — put in operation_description, no quantity
  26.2 → times — put in time_start/time_stop, no quantity
  26.3 → bunkered fuel oil. The block may show a header total ("xxxx MT of ISO-... HFO ...
         bunkered in tanks:") followed by one or more per-tank lines ("aaaa MT added to
         [Tank Name], now containing bbbb MT"). Extract BOTH when both are present:
           - header total → qty_type=bunkered, qty_value=xxxx, to_tank=null, from_tank=null
           - each per-tank line → qty_type=bunkered, qty_value=aaaa, to_tank=[Tank Name]
         If only a single tank line exists with no separate header total, extract just that
         one quantity (to_tank=tank, no header-total entry).
         Do NOT extract the "now containing bbbb MT" figure — running fuel-tank totals are
         not tracked in the Oil Record Book (fuel consumption between bunkerings is never
         logged here), so recording it would produce a false mass-balance reading.
  26.4 → Same extraction pattern as 26.3, but for bulk lubricating oil.
  Code I → no quantities unless explicitly stated; item_number = null

A TRANSFER CAN NEVER HAVE THE SAME TANK ON BOTH ENDS: from_tank and to_tank must never be the
same tank for a transferred quantity — moving a tank's contents into itself is physically
impossible, so this always means one of the two tank names was misread, almost always because
two tanks on this vessel have very similar names differing by only one word (e.g. "INCINERATOR
WASTE OIL SETTLING TANK" vs "INCINERATOR WASTE OIL SERVICE TANK"). If your first read of a
block's destination comes out identical to its source, look again — re-read the actual word that
differs (SETTLING vs SERVICE, or similar near-identical pairs) rather than defaulting to the
source tank's name for the destination too.

═══════════════════════════════════════════════════════════════
REPEATED NEAR-IDENTICAL BLOCKS — READ EACH ONE SEPARATELY:
A page can contain a run of several Code C/12.2 sludge-transfer blocks back to back, all worded
almost identically ("X.X m3 SLUDGE FROM <tank>, RETD. Y.Y m3. TRANSFERRED TO <tank>, RETD. Z.Z
m3.") and cycling through the same small set of 3-5 tanks (typically OILY BILGE TANK, F.O./L.O.
SLUDGE TANK, and the INCINERATOR WASTE OIL SETTLING/SERVICE TANK pair). Their visual similarity
makes it easy to under-count how many separate blocks are actually present, or to blend two
adjacent blocks' numbers together.

  ✗ WRONG — real failure mode seen in production (5 blocks on one page, all dated the same day):
    Block 1: 12.4, INCINERATOR WASTE OIL SETTLING TANK, 0.7 evaporated, retd 0.2
    Block 2: 12.2, INCINERATOR WASTE OIL SETTLING TANK → OILY BILGE TANK, 0.2 sludge, retd 7.8
    Block 3: 12.2, OILY BILGE TANK → INCINERATOR WASTE OIL SETTLING TANK, retd 0.0 → retd 0.9
    Block 4: 12.2, INCINERATOR WASTE OIL SETTLING TANK → SERVICE TANK, retd 0.0 → retd 0.9
    Block 5: 12.2, OILY BILGE TANK → INCINERATOR WASTE OIL SETTLING TANK (continues below)
    What actually got extracted: Blocks 1, 2, and 5 were dropped entirely (3 of 5 blocks never
    appeared in the output at all); Block 3 survived but with its retained figures swapped
    (0.9/0.0 instead of 0.0/0.9); Block 4 survived with BOTH its retained figures swapped AND its
    destination tank wrongly copied from the source ("Settling" instead of "Service"), producing
    a nonsensical same-tank-to-itself transfer.
  ✓ CORRECT: count every ruled line/signature-delimited block on the page BEFORE transcribing any
    of them, treat each as fully independent even when its wording is nearly identical to its
    neighbor, and copy each block's OWN retained figures in the order they're written (source
    tank's retained figure first if the source's retained value is written first) — never assume
    a later block's numbers based on the pattern of an earlier one.

  This applies just as much to 12.4 evaporation blocks as to 12.2 transfers. Real production
  failure: a page had TWO separate, back-to-back 12.4 entries, same date, same officers, same
  "X.X m3 WATER EVAPORATED FROM INCINERATOR WASTE OIL <SERVICE|SETTLING> TANK. RETD. Y.Y m3."
  wording, with the EXACT SAME numeric figures (0.6 evaporated, 0.3 retained) in both — differing
  only in the single word SERVICE vs SETTLING. The second block was dropped entirely; only one of
  the two ever reached the output. Two consecutive blocks having identical numbers is not a sign
  they're the same block misread twice — this vessel's Incinerator Waste Oil Settling Tank and
  Service Tank routinely run the same operation with the same volumes on the same day. Extract
  BOTH even when every number matches, as long as each has its own Date+Code row (or is a genuine
  continuation) and its own tank name.

  Code H (26.x) bunkering days are just as prone to this, in the OPPOSITE direction — instead of
  a whole block vanishing, ONE real bunkering event gets torn into two incomplete fragments. Real
  production failure: a single "92.500 MT OF LSMGO BUNKERED IN TANK" event got split into two
  separate outputs — one fragment kept the destination tank and result ("92.500 MT ADDED TO
  M.D.O.(P) TANK NOW CONTAINING 126.275 MT") but with the WRONG start/stop times (borrowed from a
  different bunkering event that day), while the other fragment had the correct start/stop times
  but was cut off before ever stating a destination tank — so it carries zero quantities and
  looks like an empty, pointless entry. Before finalizing a day with multiple 26.1/26.2/26.3
  bunkering blocks, check that each one has ALL of: its own port/anchorage name, its own
  start+stop time pair, AND its own destination tank + added-quantity figure — a block missing
  any of these on a page with several bunkering events is very likely actually the other half of
  a neighboring block, not a genuine standalone entry with missing data. Reunite the two halves
  into ONE complete entry rather than emitting either fragment on its own.

═══════════════════════════════════════════════════════════════
ORB CODE MAPPING:
  Items 11.x, 12.x → Code C
  Items 13, 14, 15.x → Code D
  Items 16, 17, 18 → Code E
  Items 19, 20, 21 → Code F
  Items 22-25 → Code G
  Items 26.x → Code H
  No item number (general remarks, voluntary bilge inventory, debunkering) → Code I

DATE FORMAT:
  Always output dates as DD-MMM-YYYY (e.g., 04-JAN-2026, 28-DEC-2025).
  If the block has no date in the Date column but has a date in a signature line,
  use the signature date. If truly no date is visible, use the most recent date seen
  on the page — never leave entry_date blank or use today's date.

  NEVER COPY THE COLUMN HEADER'S OWN FORMAT LABEL AS IF IT WERE A DATE: the printed table
  header on this page literally reads something like "DATE (dd-MONTH-yyyy)" -- that
  parenthetical is a FORMAT LABEL printed once at the top of the table, describing how dates
  in that column should look, not an actual date written by an officer. Confirmed in
  production: entry_date was output as the literal string "DD-MONTH-YYYY", copied straight
  from that header text, for a block whose own Date cell was blank. If a block's Date cell is
  genuinely blank, this is the LEADING CONTINUATION case above (or use the most recent date
  seen on the page per the rule just above) -- never transcribe the column header's format
  label itself into entry_date under any circumstance.

DATE DIGIT AMBIGUITY: A handful of handwritten digit pairs are routinely confused
with each other — 9/5, 1/7, 3/8, 0/6, 6/7, 7/8, and also 4/6 (an open, rounded "4" can
read as a "6", and vice versa -- confirmed in production: the Date column read "16"
while BOTH officer signature lines on the same entry clearly read "14" -- the Date
column itself was the misread one this time, not the signatures, so never assume the
Date column automatically outranks a signature when they disagree; two independent
signatures agreeing with each other and disagreeing with the Date column is stronger
evidence than the Date column alone). A "7" without a clear crossbar/hook can also
read as a "6" (or an "8") and vice versa -- confirmed separately in production twice:
once where a Date column and BOTH officer signature lines all clearly read "07," but
were misread as "06" consistently across all three; and once where "27" was misread
as "28" consistently across the Date column AND both signatures, with no internal
disagreement anywhere in the entry to flag it -- exactly the failure case
confidence_score exists to surface, since nothing downstream can catch a digit
misread that agrees with itself everywhere it appears. Always give your best single
reading of the
date (never output two options or a range), but if the day or month digit could
plausibly be misread as one of these confusable pairs — the stroke shape is genuinely
ambiguous, not just messy — reflect that specific doubt in confidence_score (score
it 0.6–0.75, not 0.9+). This is different from ordinary messy handwriting that is
still unambiguous once read: only lower the score for this reason when the digit's
shape itself could honestly go either way. A downstream check uses this signal to
know when it's safe to reconsider a date; scoring a genuinely ambiguous digit as
high-confidence would suppress that safety net.

QUANTITY DIGIT AMBIGUITY: the same confusable digit pairs (9/5, 1/7, 3/8, 0/6, and also 0/8)
apply to quantity figures (retained/transferred/capacity/etc.), not just dates. Confirmed in
production: a retained figure clearly written as "0.8" was read as "0.0", scored at high
confidence -- the officer's own trailing signature and the neighboring entries all corroborated
0.8, but nothing in the output flagged the reading as uncertain. Apply the exact same rule here:
if a quantity's digit shape could plausibly be one of these confusable pairs, score that entry's
confidence_score in the 0.6-0.75 range rather than 0.9+, even if every other part of the entry is
perfectly clear -- confidence_score reflects the single least-certain reading in the entry, not
an average of how legible most of it is.

confidence_score: 1.0 = perfectly legible, 0.5 = difficult handwriting, 0.0 = unreadable.
"""


def get_mock_data(vessel_id: uuid.UUID, upload_id: uuid.UUID) -> list[dict]:
    """Return 10 hardcoded mock entries covering multiple ORB codes and alert triggers."""
    return [
        {
            "entry_date": "01-Jan-2024",
            "orb_code": "C",
            "item_number": "11.1",
            "operation_description": "Sounding of bilge holding tank. Retained quantity recorded.",
            "tank_location": "Bilge Holding Tank",
            "time_start": "0800",
            "time_stop": None,
            "position_start": "13°04'N 080°17'E",
            "position_stop": None,
            "officer_1_name": "John Smith",
            "officer_1_rank": "3E",
            "officer_2_name": "Michael Raj",
            "officer_2_rank": "CE",
            "quantities": [
                {"qty_type": "retained", "qty_value": 8.50, "qty_unit": "m3",
                 "from_tank": "Bilge Holding Tank", "to_tank": None},
            ],
            "raw_text": "11.1 BHT sounding: 8.50 m3",
            "confidence_score": 0.95,
            "page_number": 1,
            "has_gap_before": False,
        },
        {
            "entry_date": "01-Jan-2024",
            "orb_code": "C",
            "item_number": "11.2",
            "operation_description": "Capacity of bilge holding tank.",
            "tank_location": "Bilge Holding Tank",
            "time_start": None,
            "time_stop": None,
            "position_start": None,
            "position_stop": None,
            "officer_1_name": "John Smith",
            "officer_1_rank": "3E",
            "officer_2_name": None,
            "officer_2_rank": None,
            "quantities": [
                {"qty_type": "capacity", "qty_value": 21.40, "qty_unit": "m3",
                 "from_tank": "Bilge Holding Tank", "to_tank": None},
            ],
            "raw_text": "11.2 BHT capacity: 21.40 m3",
            "confidence_score": 0.98,
            "page_number": 1,
            "has_gap_before": False,
        },
        {
            "entry_date": "03-Jan-2024",
            "orb_code": "C",
            "item_number": "12.2",
            "operation_description": "Transfer of bilge water from bilge holding tank to bilge separated oil tank.",
            "tank_location": "Bilge Holding Tank",
            "time_start": "1000",
            "time_stop": "1130",
            "position_start": None,
            "position_stop": None,
            "officer_1_name": "John Smith",
            "officer_1_rank": "3E",
            "officer_2_name": "Michael Raj",
            "officer_2_rank": "CE",
            "quantities": [
                {"qty_type": "transferred", "qty_value": 3.20, "qty_unit": "m3",
                 "from_tank": "Bilge Holding Tank", "to_tank": "Bilge Separated Oil Tank"},
                {"qty_type": "retained", "qty_value": 5.30, "qty_unit": "m3",
                 "from_tank": "Bilge Holding Tank", "to_tank": None},
                {"qty_type": "retained", "qty_value": 11.60, "qty_unit": "m3",
                 "from_tank": "Bilge Separated Oil Tank", "to_tank": None},
            ],
            "raw_text": "12.2 Transfer BHT to BSOT: 3.20 m3, 5.30 m3 retained in tank, transferred to BSOT, 11.60 m3 retained in tank",
            "confidence_score": 0.90,
            "page_number": 1,
            "has_gap_before": True,
        },
        {
            "entry_date": "05-Jan-2024",
            "orb_code": "C",
            "item_number": "12.3",
            "operation_description": "Incineration of sludge from sludge tank using incinerator.",
            "tank_location": "Sludge Tank",
            "time_start": "0900",
            "time_stop": "1100",
            "position_start": "14°20'N 081°05'E",
            "position_stop": "14°45'N 081°30'E",
            "officer_1_name": "John Smith",
            "officer_1_rank": "3E",
            "officer_2_name": "Michael Raj",
            "officer_2_rank": "CE",
            "quantities": [
                {"qty_type": "incinerated", "qty_value": 0.80, "qty_unit": "m3",
                 "from_tank": "Sludge Tank", "to_tank": None},
                {"qty_type": "retained", "qty_value": 2.10, "qty_unit": "m3",
                 "from_tank": "Sludge Tank", "to_tank": None},
            ],
            "raw_text": "12.3 Incineration sludge tank 0.80 m3, retained 2.10 m3",
            "confidence_score": 0.88,
            "page_number": 1,
            "has_gap_before": False,
        },
        {
            "entry_date": "07-Jan-2024",
            "orb_code": "D",
            "item_number": "13",
            "operation_description": "Overboard discharge of processed bilge water via 15 ppm separator.",
            "tank_location": "Bilge Separated Oil Tank",
            "time_start": "0600",
            "time_stop": "0800",
            "position_start": "15°00'N 082°00'E",
            "position_stop": "15°30'N 082°20'E",
            "officer_1_name": "John Smith",
            "officer_1_rank": "3E",
            "officer_2_name": "Michael Raj",
            "officer_2_rank": "CE",
            "quantities": [
                {"qty_type": "disposed", "qty_value": 4.50, "qty_unit": "m3",
                 "from_tank": "Bilge Separated Oil Tank", "to_tank": None},
                {"qty_type": "retained", "qty_value": 1.60, "qty_unit": "m3",
                 "from_tank": "Bilge Separated Oil Tank", "to_tank": None},
            ],
            "raw_text": "13 Overboard discharge BSOT 4.50 m3, retained 1.60 m3",
            "confidence_score": 0.92,
            "page_number": 2,
            "has_gap_before": False,
        },
        {
            "entry_date": "10-Jan-2024",
            "orb_code": "D",
            "item_number": "15.1",
            "operation_description": "Bilge water overboard via separator. ODM reading within limits.",
            "tank_location": "Bilge Holding Tank",
            "time_start": "0700",
            "time_stop": "0900",
            "position_start": "16°10'N 083°00'E",
            "position_stop": "16°40'N 083°30'E",
            "officer_1_name": "John Smith",
            "officer_1_rank": "3E",
            "officer_2_name": "Michael Raj",
            "officer_2_rank": "CE",
            "quantities": [
                {"qty_type": "disposed", "qty_value": 6.00, "qty_unit": "m3",
                 "from_tank": "Bilge Holding Tank", "to_tank": None},
            ],
            "raw_text": "15.1 Bilge overboard 6.00 m3",
            "confidence_score": 0.85,
            "page_number": 2,
            "has_gap_before": False,
        },
        {
            "entry_date": "12-Jan-2024",
            "orb_code": "H",
            "item_number": "26.3",
            "operation_description": "Bunkering of heavy fuel oil at port. No BDN ref.",
            "tank_location": None,
            "time_start": "0800",
            "time_stop": "1400",
            "position_start": None,
            "position_stop": None,
            "officer_1_name": "Michael Raj",
            "officer_1_rank": "CE",
            "officer_2_name": None,
            "officer_2_rank": None,
            "quantities": [
                {"qty_type": "bunkered", "qty_value": 350.0, "qty_unit": "MT",
                 "from_tank": None, "to_tank": None},
                {"qty_type": "bunkered", "qty_value": 200.0, "qty_unit": "MT",
                 "from_tank": None, "to_tank": "HFO Service Tank"},
                {"qty_type": "bunkered", "qty_value": 140.0, "qty_unit": "MT",
                 "from_tank": None, "to_tank": "HFO Storage Tank"},
            ],
            "raw_text": "26.3 Bunkering HFO 350 MT total: 200 MT to HFO Service Tank, 140 MT to HFO Storage Tank",
            "confidence_score": 0.91,
            "page_number": 2,
            "has_gap_before": False,
        },
        {
            "entry_date": "13-Jan-2024",
            "orb_code": "I",
            "item_number": None,
            "operation_description": "Accidental discharge in machinery space. Spill contained and cleaned.",
            "tank_location": "Machinery Space",
            "time_start": "1530",
            "time_stop": "1700",
            "position_start": None,
            "position_stop": None,
            "officer_1_name": "John Smith",
            "officer_1_rank": "3E",
            "officer_2_name": "Michael Raj",
            "officer_2_rank": "CE",
            "quantities": [],
            "raw_text": "Code I - accidental spill machinery space, contained",
            "confidence_score": 0.80,
            "page_number": 3,
            "has_gap_before": False,
        },
        {
            "entry_date": "14-Jan-2024",
            "orb_code": "C",
            "item_number": "12.4",
            "operation_description": "Evaporation loss from sludge tank noted.",
            "tank_location": "Sludge Tank",
            "time_start": None,
            "time_stop": None,
            "position_start": None,
            "position_stop": None,
            "officer_1_name": "John Smith",
            "officer_1_rank": "3E",
            "officer_2_name": None,
            "officer_2_rank": None,
            "quantities": [
                {"qty_type": "evaporated", "qty_value": 0.10, "qty_unit": "m3",
                 "from_tank": "Sludge Tank", "to_tank": None},
            ],
            "raw_text": "12.4 evaporation sludge tank 0.10 m3",
            "confidence_score": 0.87,
            "page_number": 3,
            "has_gap_before": False,
        },
        {
            "entry_date": "15-Jan-2024",
            "orb_code": "C",
            "item_number": "11.1",
            "operation_description": "Sounding bilge holding tank — handwriting unclear, difficult to read.",
            "tank_location": "Bilge Holding Tank",
            "time_start": "0800",
            "time_stop": None,
            "position_start": None,
            "position_stop": None,
            "officer_1_name": "J. Smith",
            "officer_1_rank": "3E",
            "officer_2_name": None,
            "officer_2_rank": None,
            "quantities": [
                {"qty_type": "retained", "qty_value": 2.30, "qty_unit": "m3",
                 "from_tank": "Bilge Holding Tank", "to_tank": None},
            ],
            "raw_text": "11.1 BHT sounding: 2.?? m3 (unclear)",
            "confidence_score": 0.60,
            "page_number": 3,
            "has_gap_before": False,
        },
    ]


def parse_entry_date(date_str: str) -> date:
    from datetime import datetime
    # 2-digit-year formats (%y) included because officer signatures in this
    # document routinely abbreviate the year (e.g. "31-JAN-26") inconsistently
    # with the entry's own 4-digit "DD-MMM-YYYY" field -- without these,
    # _TRAILING_DATE_RE-based signature-date checks (_signature_date_matches,
    # _reconcile_entry_date_vs_own_signature) silently never matched any
    # 2-digit-year signature at all, since this function raised on them.
    for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%B-%Y", "%d-%m-%Y",
                "%d-%b-%y", "%d-%B-%y", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Cannot parse date: {date_str}")


# async def extract_with_claude(storage_path: str) -> list[dict]:
#     """Extract entries from PDF using Claude API."""
#     import anthropic
#     from pdf2image import convert_from_path

#     client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

#     try:
#         pages = convert_from_path(
#             storage_path,
#             dpi=200,
#             poppler_path=r"C:\poppler\poppler-26.02.0\Library\bin"
#         )
#     except Exception as e:
#         logger.error(f"Failed to convert PDF to images: {e}")
#         return []

#     all_entries = []
#     for page_num, page_image in enumerate(pages, 1):
#         import io
#         buf = io.BytesIO()
#         page_image.save(buf, format="PNG")
#         image_b64 = base64.b64encode(buf.getvalue()).decode()

#         try:
#             response = client.messages.create(
#                 model="claude-sonnet-4-6",
#                 max_tokens=4096,
#                 system=EXTRACTION_SYSTEM_PROMPT,
#                 messages=[
#                     {
#                         "role": "user",
#                         "content": [
#                             {
#                                 "type": "image",
#                                 "source": {
#                                     "type": "base64",
#                                     "media_type": "image/png",
#                                     "data": image_b64,
#                                 },
#                             },
#                             {"type": "text", "text": f"Extract all ORB entries from page {page_num}."},
#                         ],
#                     }
#                 ],
#             )
#             raw_json = response.content[0].text.strip()
#             if raw_json.startswith("```"):
#                 raw_json = raw_json.split("```")[1]
#                 if raw_json.startswith("json"):
#                     raw_json = raw_json[4:]
#             page_data = json.loads(raw_json)
#             all_entries.extend(page_data.get("entries", []))
#         except Exception as e:
#             logger.error(f"Page {page_num} extraction failed: {e}")
#             continue

#     return all_entries

# A book scanned one page per image is portrait (taller than wide). Some
# vessels instead scan two facing book pages side by side in a single
# landscape image (a "spread") -- Gemini then has to read ~2x the content
# per call and correctly find the seam between the two pages, which is
# exactly where extra entry drops/duplications have been traced to in
# production (see AM KIRTI upload analysis). Splitting a spread into two
# separate portrait images before extraction gives Gemini the same
# one-page-at-a-time input it already handles reliably for vessels whose
# scans are portrait to begin with -- for those, width/height never
# exceeds the threshold below, so this is a no-op and nothing changes.
_SPREAD_ASPECT_THRESHOLD = 1.3

# A single page's Gemini call (classification or extraction) has no legitimate
# reason to take minutes -- normal calls return in a few seconds. Without a
# timeout here, google-genai's underlying HTTP client can block forever on a
# stalled connection with no exception ever raised, which previously hung the
# entire background task indefinitely (confirmed in production: a 22-hour-old
# "processing" upload whose debug dump showed every page's image already
# rendered, but not a single page had produced even one extraction attempt --
# the very first call was still sitting there waiting with nothing to time it
# out). This is a PER-CALL timeout, not a per-job one: a large file with many
# pages is still allowed to take as long as it needs in total, since each call
# is independently bounded and retried -- only a single dead call gets cut off.
_GEMINI_CALL_TIMEOUT_SECONDS = 120


def _split_two_up_spread(pages: list) -> list:
    """Split any landscape two-book-page spread in `pages` into two portrait
    halves (left page, then right page), leaving already-portrait pages
    untouched. Order is preserved so downstream page numbering / cross-page
    continuation logic keeps working unchanged."""
    expanded = []
    for page_image in pages:
        width, height = page_image.size
        if width > height * _SPREAD_ASPECT_THRESHOLD:
            mid = width // 2
            expanded.append(page_image.crop((0, 0, mid, height)))
            expanded.append(page_image.crop((mid, 0, width, height)))
        else:
            expanded.append(page_image)
    return expanded


# Some vessels' scans are a different shape of the same underlying problem
# _split_two_up_spread targets: instead of one continuous landscape photo of
# an open book, TWO separately-photographed pages (each individually shot,
# often rotated sideways) get stacked top-to-bottom into a single portrait
# image before being placed on one PDF page. Stacking vertically keeps the
# frame portrait (width < height), so the width > height * 1.3 landscape
# check above never fires for these -- confirmed on a real production file
# (AM KIRTI "ORB SCAN COPIES.PDF"): every multi-page image in it measured
# 0.62-0.78 width/height (portrait), yet contained two distinct photographed
# pages, each with its own IMO/page-number header, one above the other. That
# file's extraction lost ~50 of ~360 real entries as a direct result -- the
# model was handed one image containing two unrelated pages glued together
# and asked to read it as one, mirroring exactly the "two pages read as one"
# symptom reported for this scan format.
#
# Pixel-statistics heuristics (brightness bands, content bounding boxes) were
# tried first and don't reliably tell "one page with a large blank margin"
# apart from "two stacked photos with a real seam between them" -- both can
# produce a wide bright band in the same place. What does reliably tell them
# apart is the same visual understanding a person uses (a second header
# table with its own IMO number / page label, a second photo border) -- so
# this asks Gemini itself, in a cheap, separate classification call, before
# committing to the real per-page extraction prompt.
#
# This only ever runs on images _split_two_up_spread left whole (see the
# call site in extract_with_gemini) -- a page that already got split there
# never reaches this function, so vessels already extracting correctly today
# are completely unaffected by this addition.
_STACK_SPLIT_PROMPT = """This image is a scan/photo captured for a ship's Oil Record Book (ORB) log page.

It may contain either:
(a) ONE single photographed logbook page (there may be blank table/background margin around it), or
(b) TWO separate, independently-photographed logbook pages stacked one above the other in this
    same image (each was photographed separately, and may be rotated -- e.g. sideways).

Look for the tell of (b): two separate rectangular photographed regions, each with its own
"IMO NUMBER / DISTINCTIVE NUMBER OR LETTERS / NAME OF SHIP" header table and its own page-number
label near an edge, stacked one above the other with a visible seam/gap between the two photos.
A single page with ordinary blank margin around it is NOT case (b) -- only answer 2 when you can
see two distinct photographed rectangles, each with its own header/page-number.

Respond with ONLY this JSON, nothing else:
{"page_count": 1 or 2, "split_y_fraction": null or <float 0.0-1.0 -- the fraction of this
image's total height where the first (upper) photo ends and the second (lower) photo begins,
set only when page_count is 2>}
"""


class VesselMismatchError(Exception):
    """Raised before any real extraction work happens when the document's
    own "NAME OF SHIP" header clearly names a different vessel than the one
    selected in the upload form. Confirmed as a real gap in production: an
    ORB for "AMNS POLAR" got uploaded against the "AM KIRTI" vessel record,
    and the system extracted and stored all its entries under the wrong
    vessel with no warning at all -- every downstream compliance check,
    tank-balance calculation, and alert for AM KIRTI was then silently
    contaminated with a different ship's data. Raising this stops the
    upload before a single page is even sent through the main extraction
    prompt, rather than after wasting the time/cost of extracting an entire
    document only to discover a mismatch (or worse, never discovering it
    at all)."""

    def __init__(self, detected_name: str, expected_name: str):
        self.detected_name = detected_name
        self.expected_name = expected_name
        super().__init__(
            f"This document's own header reads \"NAME OF SHIP: {detected_name}\", but the "
            f"upload was made against vessel \"{expected_name}\" -- these don't match. "
            f"Upload cancelled before extraction; please re-upload under the correct vessel."
        )


_VESSEL_NAME_CHECK_PROMPT = """This image is one page of a scanned ship's Oil Record Book (or
similar MARPOL machinery-space operations log). Near the top of the page there is normally a
header table with a row reading "NAME OF SHIP:" followed by the vessel's name (handwritten or
typed), alongside other header fields like IMO NUMBER and DISTINCTIVE NUMBER OR LETTERS.

Read ONLY the "NAME OF SHIP" field and respond with ONLY this JSON, nothing else:
{"ship_name": "<the vessel name exactly as written, or null if this page has no such header
visible at all -- e.g. a blank page, a non-ORB insert page, or the header is fully illegible>"}

Do not guess or normalize the name -- transcribe it exactly as written, including any unusual
spelling, so it can be compared against a known vessel name elsewhere.
"""


def _detect_vessel_name(client, page_image) -> str | None:
    """One cheap classification call reading just the "NAME OF SHIP" header
    off a single page (normally the first page of the document). Returns
    None on any parse/response failure or if the field genuinely isn't
    visible -- a technical failure here must never block a legitimate
    upload, only a CONFIRMED mismatch (see the call site) should."""
    import io as _io
    import json as _json
    from google.genai import types

    buf = _io.BytesIO()
    page_image.save(buf, format="PNG")
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(data=buf.getvalue(), mime_type="image/png"),
                _VESSEL_NAME_CHECK_PROMPT,
            ],
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=500,
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        data = _json.loads(response.text.strip())
        name = data.get("ship_name") if isinstance(data, dict) else None
        return name.strip() if isinstance(name, str) and name.strip() else None
    except Exception as e:
        logger.warning(f"Vessel name detection call failed, skipping the cross-check: {e}")
        return None


def _vessel_names_plausibly_match(detected_name: str, expected_name: str) -> bool:
    """Loose match, tolerant of OCR noise on the vessel name itself (a
    misread letter or two) but NOT tolerant of a genuinely different name.
    Uses difflib's standard-library sequence matcher rather than adding a
    fuzzy-matching dependency for this one check."""
    import difflib

    def _norm(s: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", s.upper())

    a, b = _norm(detected_name), _norm(expected_name)
    if not a or not b:
        return True  # nothing usable to compare -- don't block on missing data
    if a == b or a in b or b in a:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() > 0.6


def _detect_stacked_pages(client, page_image) -> tuple[int, float | None]:
    """One cheap classification call per candidate page. Returns (1, None)
    for a genuine single page, or (2, split_fraction) when two stacked
    photographed pages were detected. Falls back to (1, None) -- i.e. leaves
    the page untouched -- on any parse/response failure, so a flaky call
    never loses data that a normal single-page extraction would have caught."""
    import io as _io
    import json as _json
    from google.genai import types

    buf = _io.BytesIO()
    page_image.save(buf, format="PNG")
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(data=buf.getvalue(), mime_type="image/png"),
                _STACK_SPLIT_PROMPT,
            ],
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=2000,
                response_mime_type="application/json",
            ),
        )
        data = _json.loads(response.text.strip())
        count = int(data.get("page_count") or 1)
        frac = data.get("split_y_fraction")
        frac = float(frac) if frac is not None else None
        # Reject an implausible split point (near the very top/bottom) rather
        # than trust it blindly -- a genuine stacked pair splits roughly
        # down the middle; anything else is more likely a misfire.
        if count == 2 and frac is not None and 0.15 < frac < 0.85:
            return 2, frac
    except Exception as e:
        logger.warning(f"Stacked-page detection call failed, treating as single page: {e}")
    return 1, None


# Fraction of a page's height most likely to contain a genuine cross-page
# continuation fragment -- generous enough to cover a multi-line block
# (item number, quantities, times/position, two officer signatures) while
# staying well clear of a normal page's own first real entry. Widened from
# 0.20 -- confirmed in production this call was still returning "no
# continuation found" on real, visible fragments that a 20%-height crop may
# simply not have included in full, on top of cases where the fragment WAS
# in frame and still missed (see the prompt's own examples below).
_BOUNDARY_STRIP_FRACTION = 0.28

_BOUNDARY_RECHECK_PROMPT = """This image shows ONLY the very top strip of a scanned ship's
Oil Record Book page -- not the full page.

Your ONLY job: determine whether this strip contains a CONTINUATION of an entry that started
on the PREVIOUS page (the first ruled line has blank/empty Date and Code columns -- nothing
freshly written there -- even if it has an item number, a value, a tank name, a signature, or
any combination of these), or whether this strip is instead simply the top of a genuinely NEW
entry on this page (the first ruled line has a freshly written Date+Code of its own).

THE SHAPE THIS CHECK MOST OFTEN MISSES -- READ CAREFULLY, THIS IS WHY YOU EXIST: a multi-tank
Code C 11.1 sounding sequence (Oily Bilge Tank, then L.O. Sludge Tank, then F.O. Sludge Tank,
Incinerator Waste Oil Settling Tank, and similar) often has its LAST tank cut off by the
previous page ending right after the 11.2 capacity value -- so the previous page's own last
line is just a tank name and one number, with NOTHING closing it: no retained figure, no
signature. When that happens, the very first thing at the top of THIS strip is almost always
nothing more than a bare closing line for that same tank -- literally just
  "11.3   0.6 m3"
  [officer signature line(s)]
with blank Date/Code, no tank name repeated, no other text. Confirmed in production, repeatedly
and across many separate uploads of this document type: this exact call, looking at this exact
strip, returned "no continuation found" on this precise shape over and over, even though the
fragment was sitting right there in the crop the whole time -- because a bare number and a
signature with nothing else around it does not visually resemble what "a continuation" sounds
like, so it gets read as noise instead of content. It is not noise. A lone item number, ONE
value, and a signature -- with nothing else above the next real dated entry -- is the single
most common and most important shape you are looking for, not an edge case to filter out.

If it IS a continuation, transcribe EVERYTHING visible in this strip faithfully -- text,
quantities (qty_type one of retained/capacity/transferred/disposed/incinerated/evaporated/
bunkered/collected, qty_value, qty_unit, from_tank, to_tank), times, positions, officer
names/ranks -- exactly as written, with no invention and no guessing beyond what's visible.
A short fragment (e.g. just one item number, one value, and a signature) is still a
continuation and just as important to report as a longer one -- do not skip it for being brief.

Do NOT invent a quantity value that is not actually visible in this strip just to make the
fragment "look like" a complete entry -- if the only thing legible is a closing retained figure
and a signature, report exactly that and nothing more.

If the first ruled line in this strip clearly shows a freshly written Date+Code, this is NOT a
continuation, even if it happens to look similar in wording to something on another page. A
genuinely fresh, separately-dated entry appearing lower down in this same strip (after a real
continuation fragment above it) does NOT change the fragment above it into part of that fresh
entry -- report the continuation on its own, exactly as it reads, never folded into a different
tank's entry that happens to follow it.

Respond with ONLY this JSON, nothing else:
{"continuation": null} OR
{"continuation": {"text": "<verbatim visible text finishing the previous entry, or null if
  only a signature>", "tank_location": "<tank name mentioned, or null>",
  "time_start": "<hhmm or null>", "time_stop": "<hhmm or null>",
  "position_start": "<lat/lon string or null>", "position_stop": "<lat/lon string or null>",
  "quantities": [{"qty_type": .., "qty_value": .., "qty_unit": .., "from_tank": .., "to_tank": ..}],
  "officer_1_name": .., "officer_1_rank": .., "officer_2_name": .., "officer_2_rank": ..}}
"""


def _crop_top_strip(page_image):
    width, height = page_image.size
    return page_image.crop((0, 0, width, int(height * _BOUNDARY_STRIP_FRACTION)))


def _call_boundary_recheck(client, page_image) -> dict | None:
    """A dedicated, narrowly-scoped second look at just the top of a page,
    used only when the main per-page extraction call already reported
    leading_continuation as null (see the call site in extract_with_gemini).

    Confirmed in production (ORB SCAN COPIES upload) that the main
    extraction call misses this exact shape repeatedly -- 11+ separate
    confirmed instances across one document, despite the system prompt
    already spelling it out in detail multiple times ("MOST-MISSED SHAPE",
    "NEVER GLUE TOP-OF-PAGE CONTENT..."). The main call has a lot of other
    things to juggle at once (every entry on the rest of the page, gap
    detection, erasures, officer consistency, ...); a single-purpose call
    that ONLY has to answer "is there a continuation here, and what does it
    say" is far more likely to get this one specific judgment call right,
    the same reasoning already applied to _detect_stacked_pages above.

    Falls back to None (no continuation found) on any parse/response
    failure, so a flaky call never invents data -- it just leaves the page
    exactly as the main call already had it.
    """
    import io as _io
    import json as _json
    from google.genai import types

    strip = _crop_top_strip(page_image)
    buf = _io.BytesIO()
    strip.save(buf, format="PNG")
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(data=buf.getvalue(), mime_type="image/png"),
                _BOUNDARY_RECHECK_PROMPT,
            ],
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=2000,
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        data = _json.loads(response.text.strip())
        continuation = data.get("continuation")
        return continuation if isinstance(continuation, dict) else None
    except Exception as e:
        logger.warning(f"Boundary re-check call failed, leaving page as-is: {e}")
        return None


def _detect_orphaned_last_entry(entry: dict | None) -> dict | None:
    """True if `entry` (the last entry pulled from a strictly earlier page --
    see the call site in extract_with_gemini) looks like it was cut off
    before its closing figure and signature, rather than genuinely complete.

    This is the single most common continuation-loss shape confirmed in
    production, and the one _call_boundary_recheck's generic "is there a
    continuation here" question still misses on a majority of real
    occurrences even with detailed prompt guidance -- a multi-tank Code C
    11.1 sounding sequence (or a Code D bilge-pumping block, or a Code H
    bunkering block) ending right after its opening reading, with no closing
    figure and no officer signature at all. Rather than keep asking a
    generic question and hoping it notices, this returns a small description
    of exactly what's missing (tank, code/item, the reading already
    captured) so _build_targeted_orphan_prompt can ask about THAT
    specifically -- a much easier question for the model to answer
    correctly than open-ended pattern recognition.

    Deliberately conservative: requires ZERO officer signature on top of the
    missing figure. A genuinely complete entry -- even a terse one-line
    remark -- always carries its signature, so requiring no signature at all
    keeps false positives rare for those two shapes.

    The sounding shape (Code C 11.1) does NOT require this -- confirmed in
    production twice: an incomplete sounding (missing its retained figure)
    still came back with an officer_1_name populated, apparently bled in
    from a neighboring block rather than genuinely closing this one. A real
    complete 11.1 sounding always has a "retained" quantity, full stop --
    that's specific enough on its own not to need the signature gate too,
    and gating on it would have silently skipped both confirmed cases.
    Returns None for anything that doesn't match one of these specific
    shapes -- every other page's behavior is completely unaffected by this
    function existing.
    """
    if not entry:
        return None
    qtys = entry.get("quantities") or []
    qtypes = {(q.get("qty_type") or q.get("type")) for q in qtys}
    code = entry.get("orb_code")
    item = (entry.get("item_number") or "").strip()
    tank = entry.get("tank_location")
    has_signature = bool(entry.get("officer_1_name") or entry.get("officer_2_name"))

    if code == "C" and item == "11.1" and "retained" not in qtypes and tank:
        # Missing "retained" is the tell regardless of whether "capacity" made
        # it in either -- confirmed in production some of these cut off even
        # BEFORE the capacity line, leaving nothing but the bare tank name
        # (zero quantities at all), which is just as clear a truncation
        # signal as capacity-with-no-retained.
        cap = next(
            (q.get("qty_value") for q in qtys if (q.get("qty_type") or q.get("type")) == "capacity"),
            None,
        )
        return {"kind": "sounding", "tank": tank, "capacity": cap}

    if has_signature:
        return None

    if code == "D" and item == "13" and ("transferred" in qtypes or "disposed" in qtypes) and "retained" not in qtypes:
        return {"kind": "bilge_operation", "tank": tank}

    if code == "H" and "bunkered" in qtypes:
        # A complete bunkering block always ends with a per-tank close and
        # signature (IMO guidance Example #18/#19) -- no signature here is a
        # strong signal a further per-tank line follows on the next page.
        return {"kind": "bunkering", "tank": tank}

    return None


def _build_targeted_orphan_prompt(orphan: dict) -> str:
    """Builds a recheck prompt around the SPECIFIC gap _detect_orphaned_last_entry
    found, instead of the generic "is there a continuation here" question
    _BOUNDARY_RECHECK_PROMPT asks. Telling the model exactly what tank,
    what's already captured, and what's expected to close it out turns an
    open-ended pattern-recognition problem into a targeted lookup."""
    tank = orphan.get("tank") or "this tank"
    kind = orphan.get("kind")
    if kind == "sounding":
        cap = orphan.get("capacity")
        cap_str = f"a capacity reading ({cap} m3)" if cap is not None else "a capacity reading"
        context = (
            f'the previous page\'s last entry was an INCOMPLETE Code C 11.1 tank sounding for '
            f'"{tank}" -- it showed {cap_str} but no retained figure (item 11.3) and no officer '
            f'signature at all, meaning the block almost certainly continues here.'
        )
        look_for = (
            f'a bare retained figure for "{tank}" (e.g. "11.3   X.X m3") and one or two officer '
            f'signature lines, with blank Date and Code columns'
        )
    elif kind == "bilge_operation":
        context = (
            f'the previous page\'s last entry was an INCOMPLETE Code D bilge-pumping block '
            f'(source: "{tank}") -- it showed the water quantity pumped but no destination tank '
            f'capacity/retained figure, no start/stop times, and no officer signature, meaning the '
            f'block almost certainly continues here.'
        )
        look_for = (
            "the closing part of that same block -- times, a destination tank's capacity/retained "
            "figure, and officer signature lines -- with blank Date and Code columns"
        )
    else:  # bunkering
        context = (
            'the previous page\'s last entry was an INCOMPLETE Code H bunkering block -- it showed '
            'a bunkered quantity but no officer signature, meaning it is very likely missing at '
            'least one more per-tank line (e.g. "xxxx MT added to [Tank] now containing yyyy MT") '
            "before the block's real closing signature."
        )
        look_for = (
            "one or more additional per-tank bunkering lines and the officer signature lines "
            "closing this bunkering block, with blank Date and Code columns"
        )

    return f"""This image shows ONLY the very top strip of a scanned ship's Oil Record Book page --
not the full page.

CONTEXT: {context}

Your ONLY job: look at the very top of THIS image for {look_for}. This is very often JUST a short
fragment -- do not dismiss it as too little to report; a bare number and a signature is exactly
the expected shape here.

If you find it, transcribe EVERYTHING visible faithfully -- text, quantities (qty_type one of
retained/capacity/transferred/disposed/incinerated/evaporated/bunkered/collected, qty_value,
qty_unit, from_tank, to_tank), times, positions, officer names/ranks -- exactly as written, with
no invention beyond what's visible.

If the top of this page does NOT show this -- e.g. it starts with a freshly written Date+Code of
its own, or clearly belongs to a different tank/operation -- respond with ONLY:
{{"continuation": null}}

Otherwise respond with ONLY this JSON, nothing else:
{{"continuation": {{"text": "<verbatim visible text, or null if only a signature>",
  "tank_location": "<tank name, or \\"{tank}\\" if this closes that same reading, or null>",
  "time_start": "<hhmm or null>", "time_stop": "<hhmm or null>",
  "position_start": "<lat/lon string or null>", "position_stop": "<lat/lon string or null>",
  "quantities": [{{"qty_type": .., "qty_value": .., "qty_unit": .., "from_tank": .., "to_tank": ..}}],
  "officer_1_name": .., "officer_1_rank": .., "officer_2_name": .., "officer_2_rank": ..}}}}
"""


def _call_targeted_orphan_recheck(client, page_image, orphan: dict) -> dict | None:
    """Like _call_boundary_recheck, but asks a question built specifically
    around a known-incomplete entry from the previous page (see
    _detect_orphaned_last_entry) instead of a generic "is there a
    continuation here" question. Falls back to None on any parse/response
    failure, same as _call_boundary_recheck -- the generic recheck still
    runs afterward as a safety net regardless of what happens here (see the
    call site in extract_with_gemini), so a flaky call here never loses
    coverage that already existed."""
    import io as _io
    import json as _json
    from google.genai import types

    strip = _crop_top_strip(page_image)
    buf = _io.BytesIO()
    strip.save(buf, format="PNG")
    prompt = _build_targeted_orphan_prompt(orphan)
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(data=buf.getvalue(), mime_type="image/png"),
                prompt,
            ],
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=2000,
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        data = _json.loads(response.text.strip())
        continuation = data.get("continuation")
        return continuation if isinstance(continuation, dict) else None
    except Exception as e:
        logger.warning(f"Targeted orphan re-check call failed, falling back to generic recheck: {e}")
        return None


async def _split_pages_for_gemini(raw_pages: list, client, split_manifest: list | None = None) -> list:
    """Combined page-splitting pass, run once per RAW page (i.e. straight out
    of convert_from_path, before any splitting) so each page takes exactly
    one of two paths:

      - landscape (width > height * _SPREAD_ASPECT_THRESHOLD): handled by
        _split_two_up_spread's existing left/right crop, unchanged, with NO
        classification call -- this is the path every vessel whose scans
        already extract correctly today goes through, so it costs nothing
        extra and behaves identically to before this function existed.

      - anything else (portrait-shaped, the majority case): gets the cheap
        Gemini classification call (_detect_stacked_pages) to catch the
        vertically-stacked-pair pattern _split_two_up_spread's aspect check
        can't see (stacking keeps the frame portrait). A genuine single page
        just gets classified page_count=1 and passed through unchanged.

    Splitting on the RAW page (not on _split_two_up_spread's output) matters:
    a landscape page's post-split halves are portrait-shaped, so re-checking
    the aspect ratio on the output list would wrongly route already-handled
    halves into the classifier too -- checking the original page's shape
    once, up front, is what keeps the landscape path truly zero-cost."""
    import asyncio

    expanded = []
    for raw_index, page_image in enumerate(raw_pages, 1):
        width, height = page_image.size
        if width > height * _SPREAD_ASPECT_THRESHOLD:
            split_result = _split_two_up_spread([page_image])
            expanded.extend(split_result)
            if split_manifest is not None:
                split_manifest.append({
                    "raw_page_index": raw_index, "path": "landscape_split",
                    "output_count": len(split_result),
                })
            continue

        try:
            count, frac = await asyncio.wait_for(
                asyncio.to_thread(_detect_stacked_pages, client, page_image),
                timeout=_GEMINI_CALL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"Stacked-page detection call for raw page {raw_index} timed out "
                f"after {_GEMINI_CALL_TIMEOUT_SECONDS}s, treating as single page"
            )
            count, frac = 1, None
        if count != 2 or frac is None:
            expanded.append(page_image)
            if split_manifest is not None:
                split_manifest.append({
                    "raw_page_index": raw_index, "path": "single_page",
                    "page_count": count, "split_y_fraction": frac,
                })
            continue
        split_y = int(height * frac)
        # NOTE: this used to give BOTH halves a small overlap margin past the
        # split point (a look into the other's territory in both
        # directions). Confirmed in production that trade-off was wrong in
        # the FORWARD direction specifically: giving the TOP half a peek
        # into what's really the BOTTOM half's content let Gemini read a
        # complete, fully-signed entry sitting in that forward overlap zone
        # and glue it onto its OWN nearest entry's raw_text instead of
        # emitting it as its own entry object -- a corrupted merge (two
        # dates worth of content jammed into one entry) the dedup passes
        # can't catch, since they only recognize duplicate ENTRY objects,
        # not a duplicate buried as a substring inside a different entry's
        # raw_text. Two confirmed real cases of that (a 17-FEB Code I remark
        # and a 28-FEB Function Test entry, both fully captured correctly on
        # their own page, ALSO swallowed into the wrong entry on the page
        # BEFORE them) are why the overlap was removed entirely at the time.
        #
        # Since then, the opposite failure -- genuine seam-clipping, not
        # merely theorized -- was confirmed via EXTRACTION_DEBUG_DIR on a
        # different upload (ORB SCAN COPIES, pages 49->50): an entry's tail
        # (quantities + both officer signatures) sat exactly on the split
        # line and is verifiably missing from BOTH halves' raw Gemini JSON
        # -- neither half's crop ever included it, so no amount of prompt
        # cleverness could recover it after the fact.
        #
        # Fix: give only the BOTTOM half a backward peek above the split
        # line (never the top half a forward peek below it). This 100%
        # avoids the confirmed-bad forward direction -- the top half's own
        # crop boundary is completely unchanged from before, so its
        # extraction is byte-for-byte identical to today's behavior. The
        # backward peek instead routes any recovered tail through the
        # LEADING CONTINUATION mechanism the prompt already has -- built
        # exactly for "a fragment at the very top of this page belongs to
        # the previous page's last entry" -- rather than inventing a new
        # code path. See the LEADING CONTINUATION / "MOST-MISSED SHAPE"
        # prompt sections for how that fragment is meant to be handled once
        # it's actually visible to the model.
        _backward_peek = int(height * 0.05)
        expanded.append(page_image.crop((0, 0, width, split_y)))
        expanded.append(page_image.crop((0, max(0, split_y - _backward_peek), width, height)))
        logger.info(f"Split a stacked two-page image at y-fraction {frac:.3f}")
        if split_manifest is not None:
            split_manifest.append({
                "raw_page_index": raw_index, "path": "stacked_split",
                "page_count": count, "split_y_fraction": frac,
            })
    return expanded


async def _write_progress(
    session_factory: async_sessionmaker | None,
    upload_id: uuid.UUID | None,
    **fields,
) -> None:
    """Best-effort progress heartbeat, written on its own short-lived session so
    it doesn't interfere with (or wait on) the long-lived session run_extraction
    holds for the rest of the job. Lets a stuck upload (updated_at frozen,
    pages_processed frozen) be told apart from a merely large, still-advancing
    one -- previously both looked identical in the DB until the whole job
    finished or crashed."""
    if session_factory is None or upload_id is None:
        return
    try:
        async with session_factory() as db:
            result = await db.execute(sa_select(OrbUpload).where(OrbUpload.id == upload_id))
            upload = result.scalar_one_or_none()
            if upload is None:
                return
            for key, value in fields.items():
                setattr(upload, key, value)
            await db.commit()
    except Exception as e:
        logger.warning(f"Progress heartbeat write failed for upload {upload_id}: {e}")


def _sanitize_page_entries(raw_entries, page_num: int) -> list[dict]:
    """Drop anything in a page's "entries" array (or a single entry's own
    "quantities" array) that isn't actually an object, before any other
    post-processing touches it.

    Confirmed crash in production: Gemini occasionally returns a malformed
    item inside one of these arrays -- a bare string instead of the
    requested object -- and the entire rest of the pipeline (a dozen+
    functions across both extract_with_gemini and run_extraction) calls
    .get() on every item in these lists unconditionally, with no type
    check anywhere. One malformed item on ONE page took down the ENTIRE
    extraction run for every other already-successfully-extracted page.
    Filtering here, at the single earliest point every entry passes
    through, is far more robust than patching every individual downstream
    .get() call site -- and a dropped malformed item is a much smaller,
    contained loss than crashing the whole upload.
    """
    if not isinstance(raw_entries, list):
        if raw_entries:
            logger.warning(f"Page {page_num}: entries field was {type(raw_entries).__name__}, not a list -- ignoring")
        return []
    cleaned = []
    for e in raw_entries:
        if not isinstance(e, dict):
            logger.warning(f"Page {page_num}: dropped a malformed entry of type {type(e).__name__} instead of an object")
            continue
        qtys = e.get("quantities")
        if isinstance(qtys, list):
            good_qtys = [q for q in qtys if isinstance(q, dict)]
            if len(good_qtys) != len(qtys):
                logger.warning(f"Page {page_num}: dropped {len(qtys) - len(good_qtys)} malformed quantity item(s) from an entry")
            e["quantities"] = good_qtys
        elif qtys is not None:
            logger.warning(f"Page {page_num}: entry's quantities field was {type(qtys).__name__}, not a list -- clearing")
            e["quantities"] = []
        cleaned.append(e)
    return cleaned


def _coerce_qty_value(raw_val) -> float | None:
    """Parse a quantity value that's supposed to be a plain number, but
    confirmed in production sometimes isn't -- Gemini occasionally puts the
    unit inside the same field instead of qty_unit (e.g. "3.3m3" instead of
    qty_value=3.3, qty_unit="m3"). A bare float(raw_val) raises on that and
    used to take the ENTIRE entry down with it (the exception propagated out
    of the whole per-entry save block, discarding every other field too, not
    just this one quantity). Extracting the leading numeric portion recovers
    the reading; returns None only when there's genuinely no number to find,
    in which case the caller skips just this one quantity, not the entry."""
    if isinstance(raw_val, (int, float)):
        return float(raw_val)
    if isinstance(raw_val, str):
        m = re.match(r"\s*(-?\d+(?:\.\d+)?)", raw_val)
        if m:
            return float(m.group(1))
    return None


def _normalize_for_dupe_check(text: str) -> str:
    """Whitespace/case-insensitive form used only to detect whether a
    leading_continuation fragment is literally the same text prev_entry
    already has (see the split-overlap duplicate guard below) -- not used
    for anything that gets stored."""
    return re.sub(r"\s+", " ", (text or "")).strip().upper()


def _qty_signature(q: dict) -> tuple:
    """Identity signature for a quantity dict, used only to tell whether a
    leading_continuation's quantity is a duplicate of one prev_entry already
    has (from the same split-overlap duplicate guard) -- deliberately looser
    than a full field-by-field compare since a duplicate re-reading can
    plausibly differ in from_tank/to_tank capitalization or null-vs-missing."""
    return (
        q.get("qty_type") or q.get("type"),
        q.get("qty_value") if q.get("qty_value") is not None else q.get("value"),
    )


# A vote requires 3 DISTINCT PAGES to agree (see the per-page dedup in
# _update_officer_roster below) before a name is confident enough to hint
# with -- not 3 entries. Confirmed as a real regression in production: the
# first version of this counted raw entry occurrences, so a single page
# with several same-day entries (all repeating ONE physical signature the
# model glanced at once) could clear the threshold by itself. On the ORB
# SCAN COPIES upload, page 1 had 5 entries that all repeated the exact same
# misread ("RAKESH JAMDAR" instead of "RISHIKESH JAMDAR"), instantly seeding
# the roster with a wrong name at false-looking confidence -- which then got
# fed into every later page's prompt and dragged pages that would otherwise
# have read the name correctly (confirmed via debug JSON, e.g. page 17)
# toward the SAME wrong spelling instead of the other way around. Several
# entries on one page are not independent evidence; several different pages
# independently agreeing is.
_ROSTER_MIN_VOTES = 3


def _rank_key(raw: str | None) -> str | None:
    """Normalize rank spelling ("3/E", "3 E", "3e") to one canonical form
    ("3E") for grouping -- ranks are read fresh every page (a person's rank
    can change mid-book), only the spelling of the abbreviation is
    normalized here, not the officer's actual rank value."""
    if not raw:
        return None
    key = re.sub(r"[^A-Z0-9]", "", raw.upper())
    return key or None


def _update_officer_roster(officer_roster: dict, page_entries: list[dict]) -> None:
    """Tally confidently-read officer names by rank, ONE VOTE PER PAGE (see
    _ROSTER_MIN_VOTES for why), for use as a spelling-reference hint on later
    pages (see _build_officer_roster_hint and OFFICER NAME CONSISTENCY in the
    prompt). Low-confidence entries are excluded so an already-doubtful
    reading never seeds the roster with a name that then gets used to
    "correct" other pages toward the same wrong spelling. `page_entries` is
    always exactly one physical page's entries (this is called once per page
    from the main extraction loop), so deduping within this single call is
    exactly "count this page once per name/rank, no matter how many of its
    entries repeat it"."""
    from collections import Counter

    seen_this_page: set[tuple[str, str]] = set()
    for e in page_entries:
        confidence = e.get("confidence_score")
        if confidence is not None and confidence < 0.85:
            continue
        for name_field, rank_field in (("officer_1_name", "officer_1_rank"), ("officer_2_name", "officer_2_rank")):
            name = (e.get(name_field) or "").strip()
            rank = _rank_key(e.get(rank_field))
            if not name or not rank:
                continue
            name = re.sub(r"\s+", " ", name.upper())
            dedupe_key = (rank, name)
            if dedupe_key in seen_this_page:
                continue
            seen_this_page.add(dedupe_key)
            officer_roster.setdefault(rank, Counter())[name] += 1


def _build_officer_roster_hint(officer_roster: dict) -> str:
    lines = []
    for rank, counter in officer_roster.items():
        if not counter:
            continue
        name, votes = counter.most_common(1)[0]
        if votes < _ROSTER_MIN_VOTES:
            continue
        lines.append(f"{rank}: {name}")
    if not lines:
        return ""
    return (
        "Known officers on this vessel, read consistently on earlier pages of this SAME "
        "logbook (spelling reference only -- see OFFICER NAME CONSISTENCY):\n" + "\n".join(lines)
    )


def _update_capacity_roster(capacity_roster: dict, page_entries: list[dict]) -> None:
    """Tally confidently-read tank capacities, ONE VOTE PER PAGE per tank
    (same per-page dedup reasoning as _update_officer_roster -- several
    entries on one page repeating one misread don't count as independent
    evidence), for use as a cross-check hint on later pages (see
    _build_capacity_roster_hint and KNOWN TANK CAPACITIES in the prompt).
    A tank's capacity is a fixed physical constant, so unlike the officer
    roster this hint is useful from the very first page it's seen on a
    given tank, not just for spelling -- it directly targets confirmed
    production failures where a tank name got misread as a near-identical
    sibling (L.O. Sludge Tank read as F.O. Sludge Tank, Incinerator Waste
    Oil Settling Tank read as Service Tank) because Gemini had nothing to
    cross-check the implausible resulting capacity against."""
    from collections import Counter

    seen_this_page: set[str] = set()
    for e in page_entries:
        confidence = e.get("confidence_score")
        if confidence is not None and confidence < 0.85:
            continue
        tank = re.sub(r"[#.\-]", " ", (e.get("tank_location") or ""))
        tank = re.sub(r"\s+", " ", tank.upper().strip())
        if not tank or tank in seen_this_page:
            continue
        for q in e.get("quantities") or []:
            if (q.get("qty_type") or q.get("type")) != "capacity":
                continue
            try:
                val = round(float(q.get("qty_value") if q.get("qty_value") is not None else q.get("value")), 2)
            except (TypeError, ValueError):
                continue
            seen_this_page.add(tank)
            capacity_roster.setdefault(tank, Counter())[val] += 1
            break


def _build_capacity_roster_hint(capacity_roster: dict) -> str:
    lines = []
    for tank, counter in capacity_roster.items():
        if not counter:
            continue
        val, votes = counter.most_common(1)[0]
        if votes < _ROSTER_MIN_VOTES:
            continue
        lines.append(f"{tank}: {val:g} m3")
    if not lines:
        return ""
    return (
        "Known tank capacities on this vessel, read consistently on earlier pages of this "
        "SAME logbook (a tank's physical capacity never changes -- use this ONLY to help tell "
        "apart near-identical tank names like Settling/Service or L.O./F.O. Sludge Tank when a "
        "signature or capacity reading looks ambiguous; never invent a reading you can't "
        "actually see, and a genuinely different tank not on this list is still expected):\n"
        + "\n".join(lines)
    )


async def extract_with_gemini(
    storage_path: str,
    upload_id: uuid.UUID | None = None,
    session_factory: async_sessionmaker | None = None,
    expected_vessel_name: str | None = None,
) -> tuple[list[dict], list[int]]:
    """Returns (entries, failed_page_numbers). failed_page_numbers is non-empty
    when a page's extraction could not be recovered even after retries -- the
    caller must surface this to the uploader rather than let it pass silently.

    Raises VesselMismatchError before any real extraction work happens if
    expected_vessel_name is given and the document's own "NAME OF SHIP"
    header clearly names a DIFFERENT vessel -- see _detect_vessel_name."""
    from google import genai
    from google.genai import types
    from pdf2image import convert_from_path
    import asyncio
    import io
    import httpx
    from pathlib import Path
    
    # Only force-disable httpx TLS verification when explicitly enabled (local
    # SSL-inspecting proxy). On the VM/prod this block is skipped → secure.
    if settings.DISABLE_SSL_VERIFY:
        _orig_client = httpx.Client.__init__
        _orig_async = httpx.AsyncClient.__init__
        def _no_ssl_client(self, *args, **kwargs):
            kwargs["verify"] = False
            _orig_client(self, *args, **kwargs)
        def _no_ssl_async(self, *args, **kwargs):
            kwargs["verify"] = False
            _orig_async(self, *args, **kwargs)
        httpx.Client.__init__ = _no_ssl_client
        httpx.AsyncClient.__init__ = _no_ssl_async

    client = genai.Client(
        api_key=settings.GEMINI_API_KEY,
        http_options=types.HttpOptions(
            api_version="v1beta",
        ),
    )

    # See config.EXTRACTION_DEBUG_DIR -- when set, dumps every image actually
    # sent to Gemini plus each page's raw JSON response and split decision,
    # so a specific page's failure can be diagnosed against exactly what the
    # model saw instead of an approximate manual reconstruction of it.
    debug_dir = None
    if settings.EXTRACTION_DEBUG_DIR:
        debug_dir = Path(settings.EXTRACTION_DEBUG_DIR) / str(upload_id or "unknown_upload")
        debug_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Determine Poppler path
        poppler_path = None

        # 1. Use POPPLER_PATH from .env if available
        if settings.POPPLER_PATH:
            poppler_path = settings.POPPLER_PATH

        # 2. Otherwise use backend/poppler/Library/bin
        else:
            project_root = Path(__file__).resolve().parents[2]
            local_poppler = project_root / "poppler" / "Library" / "bin"

            if local_poppler.exists():
                poppler_path = str(local_poppler)

        # Convert PDF pages. 300 DPI (raised from 200) -- a page that turns out
        # to be two stacked photographed pages (see _split_pages_for_gemini)
        # gets cropped to roughly half its height before Gemini ever sees it,
        # which was silently halving the effective legibility of dense,
        # repetitive handwritten blocks (see the confirmed 19-Jan production
        # case: 3 of 5 near-identical Code C/12.2 sludge-transfer rows were
        # dropped or had their retained-quantity figures cross-contaminated).
        # Raising the source DPI keeps each split half close to what a
        # genuinely single-photographed page already gets, which is the
        # scan format that already extracts reliably today.
        if poppler_path:
            pages = convert_from_path(
                storage_path,
                dpi=300,
                poppler_path=poppler_path,
            )
        else:
            pages = convert_from_path(
                storage_path,
                dpi=300,
            )

    except Exception as e:
        logger.exception("Failed to convert PDF to images")
        return [], []

    if expected_vessel_name and pages:
        # Run this BEFORE any of the (much more expensive) per-page splitting
        # and extraction calls -- a mismatch here should stop the upload
        # immediately, not after paying for a full extraction run first.
        try:
            detected_name = await asyncio.wait_for(
                asyncio.to_thread(_detect_vessel_name, client, pages[0]),
                timeout=_GEMINI_CALL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("Vessel name detection call timed out, skipping the cross-check")
            detected_name = None
        if detected_name and not _vessel_names_plausibly_match(detected_name, expected_vessel_name):
            raise VesselMismatchError(detected_name, expected_vessel_name)

    split_manifest: list = [] if debug_dir is not None else None
    pages = await _split_pages_for_gemini(pages, client, split_manifest=split_manifest)
    if debug_dir is not None:
        import json as _json_debug
        (debug_dir / "split_manifest.json").write_text(
            _json_debug.dumps(split_manifest, indent=2), encoding="utf-8"
        )
        for i, page_image in enumerate(pages, 1):
            page_image.save(debug_dir / f"page_{i:03d}.png")

    await _write_progress(session_factory, upload_id, total_pages=len(pages), pages_processed=0)

    def _call_gemini(page_image, page_num, roster_hint=""):
        buf = io.BytesIO()
        page_image.save(buf, format="PNG")
        buf.seek(0)
        prompt_text = f"Extract all ORB entries from page {page_num}."
        if roster_hint:
            prompt_text += f"\n\n{roster_hint}"
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(
                    data=buf.getvalue(),
                    mime_type="image/png",
                ),
                prompt_text,
            ],
            config=types.GenerateContentConfig(
                system_instruction=EXTRACTION_SYSTEM_PROMPT,
                # A page with several dense entries (verbatim raw_text, quantities,
                # positions, officer info per entry) can approach/exceed 8192 tokens,
                # silently truncating the JSON and dropping the last entries on the
                # page. Raised with margin — see the 08-Mar case where the last two
                # of six entries on one page vanished with no error at all.
                max_output_tokens=32768,
                # gemini-2.5-flash spends part of any output-token budget on its own
                # internal "thinking" before writing the actual JSON -- confirmed in
                # production via the debug dump (EXTRACTION_DEBUG_DIR): two separate
                # pages' raw responses cut off mid-object, mid-entry, with the closing
                # brackets simply never generated, well inside what 32768 tokens should
                # cover for a single page's JSON. This task doesn't need extended
                # reasoning -- the system prompt above already spells out, step by step,
                # exactly how to resolve every judgment call (entry boundaries, date
                # ambiguity, continuations) -- so disabling thinking removes the
                # competition for the output budget entirely rather than trying to
                # guess a max_output_tokens large enough to outrun an unpredictable
                # thinking allocation.
                thinking_config=types.ThinkingConfig(thinking_budget=0),
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )
        return response.text.strip()

    all_entries = []
    failed_pages: list[int] = []
    # Running per-rank tally of confidently-read officer names, built up as
    # pages are processed in order and fed to each subsequent page's call as
    # a spelling-reference hint (see OFFICER NAME CONSISTENCY in the prompt
    # and _build_officer_roster_hint below). Only ever informed by earlier
    # pages of THIS SAME upload -- never touches other vessels/uploads.
    officer_roster: dict = {}
    # Same running-tally approach for tank capacities -- see
    # _update_capacity_roster / _build_capacity_roster_hint / KNOWN TANK
    # CAPACITIES in the prompt.
    capacity_roster: dict = {}
    for page_num, page_image in enumerate(pages, 1):
        roster_hint = _build_officer_roster_hint(officer_roster)
        capacity_hint = _build_capacity_roster_hint(capacity_roster)
        if capacity_hint:
            roster_hint = f"{roster_hint}\n\n{capacity_hint}" if roster_hint else capacity_hint
        # A page's Gemini call can fail outright (network/API error), come back
        # truncated/malformed JSON, or -- seen in production -- come back as a
        # JSON *array* instead of the single object the prompt asks for (Gemini
        # bundling several pages' worth of content into one list). Any of these,
        # previously, hit the bare `except Exception: continue` below and
        # silently dropped every entry on the page with no retry and nothing
        # surfaced to the uploader -- the upload still reported "completed".
        # Retry a few times before giving up, and track pages that still fail
        # so run_extraction can report them instead of losing them silently.
        page_data = None
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                # Run the synchronous Gemini call in a thread so the event loop
                # stays responsive and gunicorn heartbeats keep flowing. Bounded
                # by a per-call timeout (see _GEMINI_CALL_TIMEOUT_SECONDS) so a
                # single stalled call fails this attempt and falls into the
                # normal retry path below instead of blocking the whole
                # extraction run indefinitely.
                import asyncio
                try:
                    raw_json = await asyncio.wait_for(
                        asyncio.to_thread(_call_gemini, page_image, page_num, roster_hint),
                        timeout=_GEMINI_CALL_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    raise TimeoutError(
                        f"Gemini call for page {page_num} did not respond within "
                        f"{_GEMINI_CALL_TIMEOUT_SECONDS}s"
                    )

                # Guard against a degenerate repeated-token generation glitch --
                # confirmed in production: one page's response got stuck
                # repeating "\n" 2000+ times inside a single field, corrupting
                # the JSON and confusing the model into emitting a differently
                # -shaped, entry-less structure afterward. json_repair can
                # often still coerce something PARSEABLE out of this (no
                # exception raised), so without this check the retry loop
                # below never fires and the page silently ends up with zero
                # entries even though it has real content. Any single short
                # substring repeated 30+ times in a row is not something a
                # legitimate response produces, so treat it as a failed
                # attempt and force a retry rather than accept whatever
                # json_repair salvaged from it.
                degenerate = re.search(r"(.{1,10}?)\1{30,}", raw_json)
                if degenerate:
                    raise ValueError(
                        f"Degenerate repeated-token glitch detected (pattern "
                        f"{degenerate.group(1)!r} repeated 30+ times) -- discarding response"
                    )

                # Clean markdown if present
                if "```" in raw_json:
                    parts = raw_json.split("```")
                    for part in parts:
                        part = part.strip()
                        if part.startswith("json"):
                            part = part[4:].strip()
                        if part.startswith("{") or part.startswith("["):
                            raw_json = part
                            break

                # Extract JSON boundaries as fallback
                start = raw_json.find("{")
                end = raw_json.rfind("}") + 1
                if start != -1 and end > start:
                    raw_json = raw_json[start:end]

                # Log raw for debugging
                logger.info(f"Page {page_num} raw JSON length: {len(raw_json)}")
                if debug_dir is not None:
                    (debug_dir / f"page_{page_num:03d}_attempt{attempt + 1}.json").write_text(
                        raw_json, encoding="utf-8"
                    )

                try:
                    parsed = json.loads(raw_json)
                except json.JSONDecodeError:
                    from json_repair import repair_json
                    parsed = json.loads(repair_json(raw_json))

                if isinstance(parsed, list):
                    # Flatten instead of crashing on parsed.get(...) below --
                    # merge every dict item's entries/leading_continuation into
                    # one page_data object.
                    merged_entries: list[dict] = []
                    merged_continuation = None
                    merged_signed = False
                    for item in parsed:
                        if not isinstance(item, dict):
                            continue
                        merged_entries.extend(item.get("entries") or [])
                        merged_continuation = merged_continuation or item.get("leading_continuation")
                        merged_signed = merged_signed or bool(item.get("master_signature_present"))
                    parsed = {
                        "entries": merged_entries,
                        "leading_continuation": merged_continuation,
                        "master_signature_present": merged_signed,
                    }
                    logger.warning(f"Page {page_num}: Gemini returned a JSON array instead of an object -- flattened {len(merged_entries)} entries from it")
                elif not isinstance(parsed, dict):
                    # Confirmed crash in production: a malformed top-level
                    # JSON type (e.g. a bare string) got accepted as a
                    # "successful" parse and broke out of the retry loop,
                    # then crashed the whole extraction run the first time
                    # downstream code called .get() on it -- taking down
                    # every other page's already-extracted data along with
                    # it. Treat this the same as any other malformed
                    # response: raise so the existing retry path picks it
                    # up, and if all 3 attempts fail this way, the page
                    # lands in failed_pages instead of crashing the run.
                    raise ValueError(
                        f"Gemini response parsed to a top-level {type(parsed).__name__}, "
                        f"not the expected object or array"
                    )

                page_data = parsed
                break
            except Exception as e:
                last_error = e
                logger.warning(f"Page {page_num} attempt {attempt + 1}/3 failed: {e}")

        if page_data is None:
            logger.error(f"Page {page_num} extraction failed after 3 attempts: {last_error}")
            failed_pages.append(page_num)
            await _write_progress(session_factory, upload_id, pages_processed=page_num)
            continue

        if page_data.get("non_orb_page"):
            # See NON-ORB PAGES in the prompt -- a receipt/certificate/blank
            # insert page, not an ORB operations table. Confirmed in
            # production (ORB SCAN COPIES upload): forcing a port reception
            # receipt into the entries schema produced a fake-looking entry
            # with a shore company's name in officer_1_name and a date
            # months off from every surrounding page. Skip storing anything
            # for it rather than coercing non-entries into the schema; this
            # is a successfully processed page, not a failure.
            logger.info(
                f"Page {page_num} classified as non-ORB page, skipping entry extraction: "
                f"{page_data.get('non_orb_page_note')!r}"
            )
            await _write_progress(session_factory, upload_id, pages_processed=page_num)
            continue

        try:
            leading_continuation = page_data.get("leading_continuation")
            if leading_continuation is not None and not isinstance(leading_continuation, dict):
                # Gemini occasionally returns a malformed type for this field
                # (a bare string, a list) instead of the requested object or
                # null. Confirmed crash in production: downstream code calls
                # .get() on this value unconditionally, and a plain string
                # has no .get() method -- treat anything that isn't
                # genuinely an object the same as "nothing reported here"
                # rather than letting one page's malformed response take
                # down the whole extraction run.
                logger.warning(
                    f"Page {page_num}: leading_continuation was {type(leading_continuation).__name__}, "
                    f"not an object -- treating as none reported"
                )
                leading_continuation = None
            # Find the entry this continuation actually belongs to by page
            # number, not just "whatever is last in the list": Gemini doesn't
            # always list a page's own entries in true visual order, so the
            # last-appended item isn't reliably the one that ends immediately
            # before this page starts (see the same reasoning in
            # _merge_split_entries below, applied here at the earlier point
            # where this exact mistake previously orphaned a fragment onto
            # the wrong entry -- or onto none at all). Computed here, before
            # the recheck attempts below, so _detect_orphaned_last_entry can
            # use it to decide whether a TARGETED recheck is worth trying.
            prev_entry = next(
                (e for e in reversed(all_entries) if (e.get("page_number") or 0) < page_num),
                None,
            )
            if not leading_continuation:
                # The main call reported nothing here -- confirmed in
                # production this is where a genuine continuation is most
                # often silently missed (see _call_boundary_recheck). Only
                # fires when there's actually something to recover, so pages
                # where the main call already found it are unaffected.
                recheck_result = None
                recheck_source = None

                # Try a TARGETED recheck first when the previous page's last
                # entry looks orphaned (see _detect_orphaned_last_entry) --
                # asking about the SPECIFIC gap (which tank, which figure) is
                # a much easier question than the generic recheck's
                # open-ended "is there a continuation here", and is what
                # actually catches the shape the generic recheck still
                # misses on a majority of real occurrences. Never replaces
                # the generic recheck below -- only tried first, and falls
                # through to it unchanged if this finds nothing, so a page
                # with no detected orphan behaves exactly as before this was
                # added.
                orphan = _detect_orphaned_last_entry(prev_entry)
                if orphan is not None:
                    try:
                        recheck_result = await asyncio.wait_for(
                            asyncio.to_thread(_call_targeted_orphan_recheck, client, page_image, orphan),
                            timeout=_GEMINI_CALL_TIMEOUT_SECONDS,
                        )
                    except asyncio.TimeoutError:
                        logger.warning(f"Targeted orphan re-check for page {page_num} timed out, skipping")
                        recheck_result = None
                    if debug_dir is not None:
                        import json as _json_debug
                        (debug_dir / f"page_{page_num:03d}_orphan_recheck.json").write_text(
                            _json_debug.dumps({"orphan": orphan, "result": recheck_result}, indent=2),
                            encoding="utf-8",
                        )
                    if recheck_result:
                        recheck_source = "targeted"

                if recheck_result is None:
                    try:
                        recheck_result = await asyncio.wait_for(
                            asyncio.to_thread(_call_boundary_recheck, client, page_image),
                            timeout=_GEMINI_CALL_TIMEOUT_SECONDS,
                        )
                    except asyncio.TimeoutError:
                        logger.warning(f"Boundary re-check for page {page_num} timed out, skipping")
                        recheck_result = None
                    if debug_dir is not None:
                        import json as _json_debug
                        (debug_dir / f"page_{page_num:03d}_boundary_recheck.json").write_text(
                            _json_debug.dumps(recheck_result, indent=2), encoding="utf-8"
                        )
                    if recheck_result:
                        recheck_source = "generic"

                # A trivial/empty-looking "continuation" (every field null,
                # nothing but an empty text string) isn't worth merging into
                # prev_entry -- accepting it anyway would still discard
                # whatever the page's own first real entry actually was by
                # attaching nothing useful in its place. Require at least
                # SOME substantive content before treating this as a genuine
                # recovered continuation rather than model noise.
                has_substance = bool(recheck_result) and any(
                    recheck_result.get(k) for k in
                    ("text", "tank_location", "officer_1_name", "officer_2_name")
                ) or bool(recheck_result and recheck_result.get("quantities"))
                if recheck_result and has_substance:
                    logger.info(f"Page {page_num}: {recheck_source} re-check found a continuation the main call missed")
                    leading_continuation = recheck_result
                elif recheck_result:
                    logger.info(f"Page {page_num}: {recheck_source} re-check returned only empty/trivial content -- ignoring")
            # Needed below: an entry that starts near the bottom of page N can have
            # its officer names/signature line actually sitting at the TOP of page
            # N+1 (a leading continuation), before page N+1's own first entry
            # begins. The prompt only asks the model for one master_signature_present
            # value per page, so that continuation fragment doesn't carry its own
            # signature flag -- but if page N+1 itself reports a signature present,
            # it's reasonable to attribute it to the entry whose tail (and signature
            # block) physically live on this page, not just to page N+1's own entries.
            current_page_signed = bool(page_data.get("master_signature_present", False))

            if leading_continuation and prev_entry:
                text = (leading_continuation.get("text") or "").strip()
                cont_qtys_raw = leading_continuation.get("quantities") or []
                cont_qtys = [q for q in cont_qtys_raw if isinstance(q, dict)] if isinstance(cont_qtys_raw, list) else []
                prev_qtys = prev_entry.get("quantities") or []

                def _has_capacity(qtys):
                    return any((q.get("qty_type") or q.get("type")) == "capacity" for q in qtys)

                # A single tank-sounding block (Code 11.x / weekly inventory) always
                # carries exactly one capacity reading for exactly one tank. If
                # prev_entry already has its own capacity value AND the continuation
                # ALSO carries one, they cannot be the same sounding -- this is a
                # second, distinct tank's entry that only became a "continuation"
                # because its own Date/Code hadn't been written yet when the page
                # cut off (e.g. only a bare Code letter was visible). Split it into
                # its own entry instead of merging two tanks' quantities together.
                #
                # NOTE: this used to ALSO split whenever prev_entry's own code was
                # anything other than "C", on the theory that "a capacity value
                # only ever legitimately belongs to a Code C 11.x sounding block,
                # never to a Code D/E/F/G/H entry." That theory is wrong per the
                # ORB's own structure: IMO guidance (MEPC.1/Circ.736/Rev.1, Example
                # #12) shows a Code D bilge-pumping block's own item 15.x line
                # legitimately stating "Capacity xx m3, xx m3 retained" for the
                # DESTINATION tank as part of that SAME entry -- and this is in
                # fact the single most common continuation shape in this whole
                # document (nearly every Code D block's tail reads "...TO BILGE
                # HOLDING TANK. CAP: 89.2 m3 RETD: X m3"). Confirmed in production:
                # once the boundary-recheck mechanisms got better at actually
                # recovering these tails (see _detect_orphaned_last_entry), this
                # rule started wrongly splitting a large fraction of genuine Code D
                # continuations into fake standalone "Code C 11.1" entries labelled
                # with the SOURCE tank name (e.g. "C 11.1 E/R BILGE WELLS") instead
                # of correctly closing out the real Code D entry -- silently
                # doubling the entry count on every affected page. Only a prev_entry
                # that ALREADY has its own capacity reading is still a genuine
                # same-slot conflict (two tanks' capacity values can't coexist in
                # one sounding); that narrower signal is kept.
                if cont_qtys and _has_capacity(cont_qtys) and _has_capacity(prev_qtys):
                    # Tell apart a genuine per-tank C.11.x sounding continuation
                    # from this vessel's Code I "weekly inventory" remark, which
                    # also carries a capacity+retained pair despite being Code I
                    # (see _split_swallowed_weekly_inventory) -- only the latter
                    # should be tagged Code I; a plain sounding is Code C/11.1.
                    is_weekly_inventory = bool(_WEEKLY_INVENTORY_RE.search(text))
                    new_entry = {
                        "entry_date": prev_entry.get("entry_date"),
                        "orb_code": "I" if is_weekly_inventory else "C",
                        "item_number": None if is_weekly_inventory else "11.1",
                        "operation_description": text,
                        "raw_text": text,
                        "tank_location": leading_continuation.get("tank_location"),
                        "time_start": leading_continuation.get("time_start"),
                        "time_stop": leading_continuation.get("time_stop"),
                        "position_start": leading_continuation.get("position_start"),
                        "position_stop": leading_continuation.get("position_stop"),
                        "officer_1_name": leading_continuation.get("officer_1_name"),
                        "officer_1_rank": leading_continuation.get("officer_1_rank"),
                        "officer_2_name": leading_continuation.get("officer_2_name"),
                        "officer_2_rank": leading_continuation.get("officer_2_rank"),
                        "quantities": cont_qtys,
                        # Always use the loop's own physical page index, never
                        # Gemini's self-reported "page_number" from the JSON --
                        # the model can hallucinate/misreport that value (seen
                        # in production: dates from the very first page of the
                        # book landing on a self-reported page_number near the
                        # very end), while page_num here is a plain sequential
                        # counter over the PDF's actual pages and can't drift.
                        "page_number": page_num,
                        "is_continuation": False,
                        "master_signature_present": current_page_signed,
                    }
                    all_entries.append(new_entry)
                    logger.info(f"Page {page_num}: leading continuation carried a second tank's capacity reading -- split into its own entry instead of merging into previous entry")
                else:
                    # Split pages now overlap slightly (see _split_pages_for_gemini's
                    # backward-peek) so a genuinely cut-off tail can be recovered here
                    # instead of lost -- but that same overlap means this
                    # leading_continuation is sometimes NOT missing content at all: if
                    # the split line happened to fall cleanly and prev_entry's own page
                    # already captured its tail in full, the overlap strip just shows
                    # that same tail again. Without this check that duplicate would get
                    # appended a second time -- doubling prev_entry's quantities and
                    # repeating its closing text -- on every stacked-split page in the
                    # document, not just the ones that genuinely needed recovering.
                    already_present = bool(text) and _normalize_for_dupe_check(text) in _normalize_for_dupe_check(
                        prev_entry.get("raw_text") or ""
                    )
                    if text and not already_present:
                        prev_entry["operation_description"] = " ".join(
                            p for p in [prev_entry.get("operation_description"), text] if p
                        ).strip()
                        prev_entry["raw_text"] = "\n".join(
                            p for p in [prev_entry.get("raw_text"), text] if p
                        ).strip()
                    for field in ("officer_1_name", "officer_1_rank", "officer_2_name", "officer_2_rank",
                                  "tank_location", "time_start", "time_stop",
                                  "position_start", "position_stop"):
                        prev_entry[field] = prev_entry.get(field) or leading_continuation.get(field)
                    # prev_entry's master_signature_present was already fixed to page
                    # N's own (often False) value when page N was processed. If this
                    # entry's tail -- and its officer signature -- turned out to
                    # actually live on page N+1 (this page), and page N+1 itself has
                    # a detected signature, credit it to prev_entry rather than
                    # leaving it permanently stuck at page N's false/absent reading.
                    prev_entry["master_signature_present"] = (
                        bool(prev_entry.get("master_signature_present")) or current_page_signed
                    )
                    if cont_qtys and not already_present:
                        prev_qty_keys = {_qty_signature(q) for q in prev_qtys}
                        new_qtys = [q for q in cont_qtys if _qty_signature(q) not in prev_qty_keys]
                        prev_entry["quantities"] = prev_qtys + new_qtys
                    if already_present:
                        logger.info(f"Page {page_num}: leading continuation duplicates prev entry's own tail (split overlap) -- not re-appended")
                    else:
                        logger.info(f"Page {page_num}: attached leading continuation to previous entry")

            page_entries = _dedupe_same_page_entries(_sanitize_page_entries(page_data.get("entries", []), page_num))
            page_signed = bool(page_data.get("master_signature_present", False))
            for e in page_entries:
                # See note above -- always trust the loop's physical page
                # index over Gemini's own self-reported page_number field.
                e["page_number"] = page_num
                # master_signature_present is asked for once per page (there's
                # one "Signature of Master" line per page, not per entry) --
                # apply that single page-level answer to every entry on it.
                e["master_signature_present"] = page_signed
            all_entries.extend(page_entries)
            _update_officer_roster(officer_roster, page_entries)
            _update_capacity_roster(capacity_roster, page_entries)
            logger.info(f"Page {page_num} extracted {len(page_entries)} entries")

        except Exception as e:
            logger.error(f"Page {page_num} post-processing failed: {e}")
            failed_pages.append(page_num)
            await _write_progress(session_factory, upload_id, pages_processed=page_num)
            continue

        await _write_progress(session_factory, upload_id, pages_processed=page_num)

    return all_entries, failed_pages

_SIGNATURE_PATTERNS = [
    # "3E; M.SATHIK; 28-DEC-2025"  or  "CE / A.SOLANKI / 04-JAN-2026"
    r"^\s*(CE|3E|2E|1E|4E|ETO|CO|2O|3O|C/E|C/O)\s*[;/,]\s*\S",
    # Standalone line like "Signed by Chief Engineer"
    r"sign(ed|ature)",
    # Only a name + date with no numeric content at all
    r"^[A-Z][a-z]+\s+[A-Z][a-z]+\s*[;/,]\s*\d{2}[\-/][A-Z]{3}[\-/]\d{4}\s*$",
]
_SIGNATURE_RE = re.compile("|".join(_SIGNATURE_PATTERNS), re.IGNORECASE)


_LEADING_HEADER_RE = re.compile(
    r"^\s*\d{1,2}[\-\s]?[A-Z]{3}[\-\s]?\d{2,4}\s*[A-Z]?\s*\d{0,2}(?:\.\d)?\s*",
    re.IGNORECASE,
)
_RANK_TOKEN = r"(?:CE|3E|2E|1E|4E|ETO|CO|2O|3O|C/E|C/O)"
_DATE_TOKEN = r"\d{1,2}[\-\s/][A-Z]{3}[\-\s/]\d{2,4}"


def _is_signature_block(raw_text: str, officer_1_name: str | None = None,
                         officer_2_name: str | None = None) -> bool:
    """Return True when raw_text has no real content beyond the officer
    sign-off(s) and a leading Date/Code/Item header -- NOT simply when it's
    short. Every real ORB entry ends in a signature, so "ends in a signature"
    can never be the test on its own -- a short but substantive entry must
    never be misclassified as a bare signature stub just because it's brief.

    Confirmed in production TWICE with the old line-count-based version
    (len(lines) > 3 => real entry, else pattern-match the whole blob): once a
    genuine 26.1 port-name entry ("13 JAN 2026 H 26.1 ZHOUSHAN TIAOZHOUMEN
    ANCHORAGE" + 2-officer signature, 2 lines) got silently dropped by
    run_extraction's "reject signature-only fragments" check; once a genuine,
    independently-signed Code I remark ("FUNCTION TEST 15 PPM AND OIL
    PROBE" + 1-officer signature, also 2 lines) got wrongly treated as "not a
    fresh entry" by _looks_like_fresh_entry and merged into an unrelated
    earlier entry instead of staying its own.

    Fix: rather than classifying whole LINES as "signature" and discarding
    them (a first attempt at this that itself broke on a THIRD confirmed
    case -- Gemini sometimes returns raw_text as a single line with no
    newlines at all, e.g. "...TRANSFERRED TO OILY BILGE TANK RETD. 9.2 m3.
    SONU KUMAR 2/E 07 JAN 2026 ...", where discarding that one line because
    the officer's name appears in it would wrongly discard the real
    quantities sitting on the same line), strip out only the officer
    sign-off SUBSTRING itself -- the officer's own structured
    officer_1_name/officer_2_name (a more reliable signal than guessing at
    rank;name;date formatting, per the same reasoning as
    _merge_split_entries' has_own_signoff check) plus an adjacent rank/date
    token, wherever it sits in the text -- and check what's left. Whatever
    survives that plus the leading Date/Code/Item header is the real test:
    if a few words of real substance remain, it's a real entry, however
    short.
    """
    if not raw_text:
        return False
    text = _LEADING_HEADER_RE.sub("", raw_text.strip(), count=1)

    officer_names = [n.strip() for n in (officer_1_name, officer_2_name) if n and n.strip()]
    if officer_names:
        for name in officer_names:
            text = re.sub(
                rf"{_RANK_TOKEN}?\s*[/,;:.\-]?\s*{re.escape(name)}\s*[/,;:.\-]?\s*{_RANK_TOKEN}?"
                rf"\s*[/,;:.\-]?\s*(?:{_DATE_TOKEN})?",
                " ", text, flags=re.IGNORECASE,
            )
        text = re.sub(r"\bsign(ed|ature)\b\s*:?", " ", text, flags=re.IGNORECASE)
    else:
        # No structured officer name available at all -- fall back to the
        # original whole-text pattern match rather than guessing.
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if len(lines) > 3:
            return False
        return bool(_SIGNATURE_RE.search(text))

    remaining = re.sub(r"[^A-Za-z0-9]", "", text)
    return len(remaining) < 4


# Item numbers that belong to a single ORB block, in reading order. A block that
# gets cut by a page break is extracted as two+ fragments (same date/code, item
# numbers continuing upward) that must be re-stitched into one entry.
_BLOCK_GROUPS = {
    "C": ["11.1", "11.2", "11.3", "11.4"],  # 12.x entries are standalone, not grouped
    "D": ["13", "14", "15.1", "15.2", "15.3"],
    "E": ["16", "17", "18"],
    "F": ["19", "20", "21"],
    "G": ["22", "23", "24", "25"],
    "H": ["26.1", "26.2", "26.3", "26.4"],
}


def _block_index(orb_code: str, item_number: str | None):
    """Position of item_number within its block group, or None if not groupable."""
    if not item_number:
        return None
    group = _BLOCK_GROUPS.get(orb_code)
    if not group:
        return None
    if orb_code == "C" and not item_number.startswith("11"):
        return None  # 12.x items are complete entries on their own
    try:
        return group.index(item_number)
    except ValueError:
        return None


# The item number a code's block legitimately STARTS with. A fragment at the
# top of a page whose own item doesn't match this (or has no item at all) is
# not a fresh entry — it's a leftover continuation of whatever came before.
_BLOCK_FIRST_ITEM = {"C": "11.1", "D": "13", "E": "16", "F": "19", "G": "22", "H": "26.1"}


def _looks_like_fresh_entry(entry: dict) -> bool:
    """True if this entry plausibly starts a genuine new block on its own,
    rather than being a stray continuation fragment of whatever preceded it."""
    # The model's own direct report of "was Date+Code blank on this row" is
    # ground truth, not a guess — trust it over any pattern-matching below.
    if entry.get("is_continuation") is True:
        return False
    code = entry.get("orb_code")
    item = (entry.get("item_number") or "").strip()
    if code == "C" and item.startswith("12"):
        return True  # 12.x entries are always standalone/complete by convention
    if code == "I":
        # A genuine new Code I remark always has real substance of its own —
        # a bare fragment that's just a signature (or nothing) is not one.
        text = entry.get("raw_text") or entry.get("operation_description") or ""
        return bool(entry.get("quantities")) or not _is_signature_block(
            text, entry.get("officer_1_name"), entry.get("officer_2_name")
        )
    first_item = _BLOCK_FIRST_ITEM.get(code)
    return first_item is not None and item == first_item


def _dedupe_same_page_entries(page_entries: list[dict]) -> list[dict]:
    """Collapse near-duplicate entries Gemini occasionally emits twice for the
    SAME physical block within one page's own response (seen in production:
    one 18-MAR Code D/13 bilge-pumping entry extracted as two separate objects
    -- one with the full transferred+retained figures and destination tank,
    the other with only the transferred figure and the source tank). These
    don't share identical field values, so the fingerprint-based duplicate
    check in run_extraction (which requires an exact match) never catches
    them -- both get inserted as if they were two real, separate operations.

    Treat two same-page entries as the same block only when they share BOTH
    date + code + item_number AND at least one identical (qty_type, qty_value)
    pair -- a real coincidence for two genuinely distinct operations, but
    exactly what happens when the same block gets mis-split. Merges the
    weaker copy's quantities/fields into the fuller one instead of keeping
    both.

    IMPORTANT SCOPE LIMIT: item_number alone only identifies a singular
    per-day *event* for some codes (Code D's "13" is one bilge-pumping
    operation; Code H's "26.1" is one bunkering). For Code C's "11.1" it
    identifies "this is a tank sounding" -- EVERY tank on the page shares
    that exact item_number, since it's a per-TANK reading, not a per-event
    one, and small utility tanks routinely share the same round-number
    capacity/retained figure by coincidence (seen in production: Incinerator
    Waste Oil Settling Tank and Incinerator Waste Oil Service Tank both
    legitimately read "capacity 1.1 m3" the same day). Matching on item_number
    there would merge two genuinely different tanks' entries into one and
    silently destroy real data -- so Code C "11.1" entries are never
    considered for this dedup at all, regardless of quantity overlap.

    The exact same coincidence risk applies to "12.2"/"12.4" (and any other
    per-tank C.12.x operation): a vessel routinely runs the SAME transfer or
    evaporation operation on twin sibling tanks (e.g. "Waste Oil Settling
    Tank No#1" and "No#2") on the same day with near-identical small
    quantities. Confirmed in production on a real document: four separate
    dates where a No#1 and No#2 operation shared either the same transferred
    amount or the same resulting retained figure -- each time, that single
    coincidental overlap satisfied the match below and silently merged the
    two tanks' entries into one, discarding the second tank's entire
    operation. Requiring the tank(s) involved to also agree fixes this
    without weakening real duplicate detection: a genuine duplicate
    extraction of the SAME physical block always repeats the SAME tank(s).

    tank_location alone isn't enough for a transfer (12.2): it's
    conventionally set to the SOURCE tank, which is IDENTICAL for both a
    No#1 and a No#2 transfer originating from the same tank (e.g. both read
    tank_location="Bilge Separated Oil Tank") -- only the destination
    (to_tank on the transferred quantity) actually differs between them. So
    the signature below combines tank_location with every to_tank seen in
    the entry's quantities, which correctly distinguishes both transfer
    entries (same source, different destination) and per-tank soundings/
    evaporations with no to_tank at all (different tank_location).

    CAPACITY NEVER COUNTS AS A DUPLICATE SIGNAL: a tank's capacity is a fixed
    physical constant, so it reads IDENTICALLY every time that tank appears,
    on any code, any item, any date -- it is definitionally never distinctive
    enough to indicate "these two entries are the same operation." Confirmed
    in production: two genuinely separate same-day Code D bilge-disposal
    events (different times, different disposed/retained volumes, different
    GPS positions) shared only their tank's constant capacity=89.2 reading,
    which alone satisfied the "at least one identical (qty_type, qty_value)
    pair" test below and silently merged the second, distinct disposal event
    away entirely. Excluding capacity from the compared pairs closes this
    without weakening real duplicate detection, since a genuine duplicate
    extraction of the SAME physical block always repeats its VARIABLE
    figures too (retained/transferred/disposed), not just the constant one.
    """
    def _qty_pairs(e):
        # Direction (from_tank, and to_tank for transfers) is part of the
        # pair's identity, not just its type+value. Confirmed in production
        # (AM KIRTI, page 66): two DISTINCT reciprocal transfers between the
        # same tank pair on the same day (A->B transferred 0.5, retained
        # 10.4/1.95; B->A transferred 0.6, retained 1.95/10.4) were wrongly
        # merged into one corrupted entry, because a reciprocal pair's
        # retained figures are always each other's numbers, just swapped --
        # so type+value alone matches by construction for any reciprocal
        # pair, not just a genuine duplicate re-extraction. Including
        # from_tank (and to_tank, for transferred/bunkered) means a swapped
        # reciprocal pair no longer produces identical tuples, while a real
        # duplicate re-extraction of the SAME block still repeats the SAME
        # direction too, so genuine duplicate detection is unaffected.
        pairs = set()
        for q in (e.get("quantities") or []):
            qtype = q.get("qty_type") or q.get("type")
            if qtype == "capacity":
                continue
            qval = q.get("qty_value") if q.get("qty_value") is not None else q.get("value")
            from_tank = re.sub(r"\s+", " ", (q.get("from_tank") or "").strip().upper())
            to_tank = re.sub(r"\s+", " ", (q.get("to_tank") or "").strip().upper()) if qtype in ("transferred", "bunkered") else ""
            pairs.add((qtype, qval, from_tank, to_tank))
        return pairs

    def _qty_pairs_match(a_pairs, b_pairs):
        # A single shared (qty_type, qty_value) pair used to be enough to call
        # two same-tank entries duplicates. Confirmed in production too loose:
        # this vessel routinely runs several GENUINELY separate 12.2 transfers
        # between the exact same tank pair on the same day, and the
        # "transferred" amount is drawn from a small set of round numbers
        # (0.9 m3 especially) that recurs constantly by pure coincidence --
        # two real, distinct operations sharing that one figure while
        # differing on their own retained figures got silently collapsed into
        # one, discarding the second real operation entirely. A genuine
        # duplicate re-extraction of the SAME block repeats ALL its variable
        # figures, not just one -- so require at least 2 shared pairs when
        # both entries have more than one to compare, and only fall back to
        # "any 1" when one side genuinely has just a single figure to offer
        # (there's nothing more specific available to require in that case).
        #
        # RETAINED-ONLY OVERLAP IS NOT ENOUGH WHEN EITHER SIDE HAS AN ACTION
        # QUANTITY: a "retained" reading is a snapshot of a tank's level, and
        # in a transfer block BOTH the source and destination tanks' retained
        # figures appear in the SAME entry's quantities -- which means a
        # reciprocal pair (A->B transferred X, vs the genuinely separate B->A
        # transferred Y logged the same day) ends up listing the exact SAME
        # two retained figures in both entries, just because both entries
        # mention both tanks' post-operation levels. That satisfies a
        # retained-only overlap check even though the two entries describe
        # opposite, independent operations. Confirmed in production (AM
        # KIRTI, page 66): 0.5 m3 F.O.Sludge->Oily Bilge (retained 10.4/1.95)
        # and 0.6 m3 Oily Bilge->F.O.Sludge (retained 1.95/10.4) were wrongly
        # merged this way -- their "transferred" pairs never matched (0.5 !=
        # 0.6, and opposite direction), only their retained pairs did. An
        # ACTION quantity (transferred/disposed/incinerated/evaporated/
        # bunkered/collected) describes what actually happened, including its
        # direction -- a genuine duplicate re-extraction of the SAME block
        # always repeats the SAME action with the SAME direction and value,
        # while two independent operations never do. So: if either entry has
        # at least one action-type pair, ADDITIONALLY require the overlap to
        # include an action pair -- pure "retained" agreement alone must not
        # be enough on its own to call two entries duplicates. This is an
        # extra condition layered on top of the count threshold above, not a
        # replacement for it -- the original threshold (>=2 shared pairs
        # unless one side only has 1 to offer) still applies unchanged, so
        # nothing that previously required 2 agreeing pairs becomes matchable
        # on a single coincidental one; this only ever makes a match STRICTER
        # by additionally ruling out the reciprocal-pair case where retained
        # figures alone satisfy the count but the actions themselves disagree.
        action_types = {"transferred", "disposed", "incinerated", "evaporated", "bunkered", "collected"}
        a_actions = {p for p in a_pairs if p[0] in action_types}
        b_actions = {p for p in b_pairs if p[0] in action_types}
        overlap = a_pairs & b_pairs
        if not overlap:
            return False
        smaller = min(len(a_pairs), len(b_pairs))
        count_ok = len(overlap) >= 1 if smaller <= 1 else len(overlap) >= 2
        if not count_ok:
            return False
        if a_actions or b_actions:
            return bool(overlap & (a_actions | b_actions))
        return True

    def _tank_key(e):
        locs = {re.sub(r"\s+", " ", (e.get("tank_location") or "").strip().upper())}
        for q in (e.get("quantities") or []):
            to_tank = q.get("to_tank")
            if to_tank:
                locs.add(re.sub(r"\s+", " ", to_tank.strip().upper()))
        return frozenset(locs)

    kept: list[dict] = []
    for entry in page_entries:
        item = (entry.get("item_number") or "").strip()
        is_per_tank_sounding = entry.get("orb_code") == "C" and item == "11.1"
        key = ((entry.get("entry_date") or "").strip().upper(), entry.get("orb_code"), item)
        match = None
        if item and not is_per_tank_sounding:
            for existing in kept:
                ekey = ((existing.get("entry_date") or "").strip().upper(), existing.get("orb_code"),
                        (existing.get("item_number") or "").strip())
                if ekey == key and _tank_key(existing) == _tank_key(entry) and _qty_pairs_match(_qty_pairs(existing), _qty_pairs(entry)):
                    match = existing
                    break
        if match is not None:
            existing_qtys = match.get("quantities") or []
            match["quantities"] = existing_qtys + [q for q in (entry.get("quantities") or []) if q not in existing_qtys]
            for field in ("tank_location", "time_start", "time_stop", "position_start", "position_stop",
                          "officer_1_name", "officer_1_rank", "officer_2_name", "officer_2_rank"):
                match[field] = match.get(field) or entry.get(field)
            if len(entry.get("operation_description") or "") > len(match.get("operation_description") or ""):
                match["operation_description"] = entry.get("operation_description")
            logger.warning(f"Merged duplicate same-page entry: date={key[0]} code={key[1]} item={item}")
            continue
        kept.append(entry)
    return kept


def _same_entry_date(a: str | None, b: str | None) -> bool:
    """Compare two raw entry_date strings as actual dates, not text.

    A plain string comparison breaks on formatting drift the model can
    introduce between two independent per-page calls (e.g. "11-Jan-2026" vs
    "11-JAN-2026", or a stray format switch) even though both name the same
    calendar day — which silently defeats the cross-page merge below. Falls
    back to a normalized string compare only if either side fails to parse.
    """
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b:
        return a == b
    try:
        return parse_entry_date(a) == parse_entry_date(b)
    except ValueError:
        return a.lower() == b.lower()


def _merge_split_entries(entries_data: list[dict]) -> list[dict]:
    """Re-stitch ORB blocks that were cut across a page boundary.

    Gemini extracts each PDF page independently with no memory of the previous
    page, so anything that spills from the bottom of one page onto the top of
    the next — a value cut off mid-sentence, a continuation item number, a
    signature, or a whole remark with no fresh Date/Code header of its own —
    comes back as a separate fragment instead of staying part of the entry it
    belongs to. General rule: if a fragment crosses a page boundary, shares
    the previous entry's date, and doesn't look like the genuine start of a
    new block (_looks_like_fresh_entry), it belongs to the previous page's
    last entry — merge it in, regardless of what item/code the model guessed
    for it (a fragment's own code/item guess is exactly what's unreliable
    here, since it has no real header of its own to read from).

    One case still needs special handling on top of that: a content-rich
    fragment that the model mislabels as a genuine Code I remark (passing
    _looks_like_fresh_entry) when it's actually still finishing a DIFFERENT
    code's block from the previous page (e.g. "TO SHORE RECEPTION FACILITY..."
    finishing a Code C disposal). Code I never legitimately interrupts another
    code's block, so if prev is a real non-I operation, treat this as a
    continuation of it too.

    Finding "prev" for a CROSS-PAGE fragment: do NOT assume it is simply the
    last item appended so far. The model sometimes lists a page's own entries
    out of visual order (e.g. puts a top-of-page continuation fragment after
    that page's other rows in its JSON, even though physically it comes
    first). Since ordering within a page is unreliable but page_number itself
    is not, the cross-page fallback below finds the previous entry by page
    number: the most recently merged entry whose page is strictly earlier
    than this fragment's page, regardless of where it sits in the list.

    SAME-PAGE block splits get a separate, earlier pass before that fallback.
    A block Gemini is supposed to keep as ONE entry (e.g. Code H's
    26.1/26.2/26.3, Code C's 11.1/11.2/11.3, Code D's 13/14/15.x) sometimes
    comes back as several same-page fragments instead — confirmed in
    production (AM KIRTI, page 11): two distinct 26.1/26.2/26.3 bunkering
    events on the SAME page each got split into 3 fragments, and because the
    page-number-only search above only ever looks at STRICTLY EARLIER pages,
    every 26.2/26.3 fragment skipped right past its true same-page 26.1
    parent and instead glued onto an unrelated leftover entry carried over
    from the previous page — corrupting two real bunkering events into one
    garbled entry with the wrong date, tank, and officer.

    Item position within a code's block (_block_index) is reliable evidence
    ordering-within-a-page is NOT: a block's items only ever increase in
    index while that block is open (26.2 always follows 26.1, never the
    reverse), so for a fragment whose own item is definitely not a block's
    first item, the nearest earlier same-code entry (searched backward
    through everything merged so far, same page or not) whose own block
    position is lower is unambiguously its parent — no page-boundary
    assumption needed.
    """
    merged: list[dict] = []
    for entry in entries_data:
        entry_page = entry.get("page_number")
        entry_block_idx = _block_index(entry.get("orb_code"), entry.get("item_number"))

        prev = None
        same_block_position_match = False
        if entry_block_idx is not None and entry_block_idx > 0:
            candidates = []
            for candidate in reversed(merged):
                if candidate.get("orb_code") != entry.get("orb_code"):
                    continue
                cand_idx = _block_index(candidate.get("orb_code"), candidate.get("item_number"))
                if cand_idx is not None and cand_idx < entry_block_idx:
                    candidates.append(candidate)
            if candidates:
                # Among same-code, lower-block-position candidates, prefer one
                # whose date matches a date actually found in THIS fragment's
                # own raw_text (typically its trailing officer signature --
                # a reliable field, unlike a continuation row's own guessed
                # header) over just the nearest one. Confirmed in production:
                # a same-page block head can itself carry a misread date, in
                # which case "nearest" silently picks the wrong parent even
                # though the fragment's own signature names the right one.
                fragment_dates = set()
                for m in _TRAILING_DATE_RE.finditer((entry.get("raw_text") or "").upper()):
                    try:
                        fragment_dates.add(parse_entry_date(f"{m.group(1)}-{m.group(2)}-{m.group(3)}"))
                    except ValueError:
                        continue
                date_matched = None
                if fragment_dates:
                    for candidate in candidates:  # already nearest-first
                        try:
                            cand_date = parse_entry_date((candidate.get("entry_date") or "").strip())
                        except ValueError:
                            continue
                        if cand_date in fragment_dates:
                            date_matched = candidate
                            break
                prev = date_matched or candidates[0]
                same_block_position_match = True

        if prev is None:
            for candidate in reversed(merged):
                cand_page = candidate.get("page_number")
                if entry_page is not None and cand_page is not None and cand_page < entry_page:
                    prev = candidate
                    break

        if prev is not None and same_block_position_match:
            same_block = True
        elif prev is not None:
            crossed_page = True  # true by construction of the page-based lookup above
            same_date = _same_entry_date(prev.get("entry_date"), entry.get("entry_date"))

            # A fragment whose own item_number is definitively NOT a block's
            # first item (e.g. D's "15.3", C's "11.3") -- or that the model
            # explicitly flagged is_continuation=true -- could not possibly be
            # a genuine new entry no matter what date it carries. Its
            # self-reported date in that case is a guess copied from context
            # (there was no real Date column to read), not independent
            # evidence, so don't let a date mismatch block the merge here the
            # way it should for a merely "doesn't look fresh" Code-I fragment.
            # Production case this fixes: a block's start (item 13/14) is
            # missed entirely on the page it's written on, and its tail
            # (item 15.3, on the next page) invents the wrong date and is left
            # as its own orphaned, incomplete entry instead of being merged.
            strong_continuation_signal = entry.get("is_continuation") is True or (
                _block_index(entry.get("orb_code"), entry.get("item_number")) or 0
            ) > 0

            general_continuation = crossed_page and not _looks_like_fresh_entry(entry) and (
                same_date or strong_continuation_signal
            )
            # Require the Code I entry to lack its OWN sign-off before treating
            # it as a mislabeled continuation. The docstring's own example
            # ("TO SHORE RECEPTION FACILITY/TRUCK AT PORT OF PARADIP...") never
            # has a signature of its own -- that's exactly the tell that it's
            # leftover description text whose real signature already happened
            # on the entry it's actually finishing. A genuine, complete,
            # independently-signed Code I remark is the opposite case, and was
            # getting silently absorbed by this same heuristic purely for
            # sharing a date with whatever came before it on the previous page.
            #
            # Confirmed in production THREE times now, and the third case is
            # why this checks the structured officer_1_name/officer_2_name
            # fields, not just a "Signed:"-style pattern inside raw_text: a
            # "VALVE OPERATION TESTED. FOUND SATISFACTORY." entry came back
            # from Gemini with its officer names correctly populated in their
            # own dedicated fields, but with a bare raw_text/operation_
            # description holding only the remark itself -- no literal
            # "Signed:" text for a regex to find. Checking raw_text alone
            # missed this and let the entry get swallowed anyway; the
            # structured officer fields are the more reliable signal Gemini
            # actually gives us for "this row was signed," so check those
            # first and fall back to the raw_text pattern only as a second
            # signal for cases where officer fields came back empty but a
            # signature line is still visible in the text itself.
            has_own_signoff = bool(
                entry.get("officer_1_name") or entry.get("officer_2_name")
                or _SIGNATURE_RE.search(entry.get("raw_text") or "")
            )
            mislabeled_as_I_continuation = (
                crossed_page and same_date
                and prev.get("orb_code") != "I"
                and entry.get("orb_code") == "I"
                and not (entry.get("item_number") or "").strip()
                and not has_own_signoff
            )
            same_block = general_continuation or mislabeled_as_I_continuation
        else:
            same_block = False

        if prev is not None:
            # Invariant guard: a single tank-sounding block can only ever have
            # ONE capacity reading. If prev already has one and this fragment
            # ALSO carries its own capacity reading, they cannot be the same
            # block no matter what the heuristics above concluded -- this is
            # a second, genuinely distinct tank entry (e.g. a standalone
            # "WEEKLY INVENTORY OF BILGE TANK" remark) that the model
            # mislabeled as a continuation. Keep them separate rather than
            # corrupting prev with two tanks' worth of quantities. Applies to
            # the same-page block-position match too -- a fragment carrying
            # its own capacity reading when prev already has one is never a
            # legitimate 11.2/26.x continuation of it either.
            def _has_capacity(qtys):
                return any((q.get("qty_type") or q.get("type")) == "capacity" for q in (qtys or []))

            if same_block and _has_capacity(prev.get("quantities")) and _has_capacity(entry.get("quantities")):
                same_block = False

            if same_block:
                prev["operation_description"] = " ".join(
                    p for p in [prev.get("operation_description"), entry.get("operation_description")] if p
                ).strip()
                prev["raw_text"] = "\n".join(
                    p for p in [prev.get("raw_text"), entry.get("raw_text")] if p
                ).strip()
                prev["quantities"] = (prev.get("quantities") or []) + (entry.get("quantities") or [])
                for field in ("tank_location", "time_start", "time_stop", "position_start",
                              "position_stop", "officer_1_name", "officer_1_rank",
                              "officer_2_name", "officer_2_rank"):
                    prev[field] = prev.get(field) or entry.get(field)
                prev_conf = prev.get("confidence_score")
                cur_conf = entry.get("confidence_score")
                if prev_conf is not None and cur_conf is not None:
                    prev["confidence_score"] = min(prev_conf, cur_conf)
                continue  # entry absorbed into prev, don't append separately
        merged.append(entry)
    return merged


def _drop_untanked_sounding_fragments(entries_data: list[dict]) -> list[dict]:
    """Drop a Code C "11.1" entry that has no tank_location at all.

    A real 11.1 sounding is definitionally a reading OF a specific named
    tank -- there is no such thing as a legitimate 11.1 entry with no tank
    name, so tank_location=None on one is not "data we're missing a field
    for," it's a signal the entry itself isn't real. Confirmed in production:
    a raw_text of just "CAP: 29.2 m3 RETD: 11.7 m3" plus a signature, with
    orb_code=C, item_number=11.1, tank_location=null -- its retained figure
    (11.7) exactly matched a real Code D entry's own retained figure from
    the same day, meaning this was a garbled, orphaned duplicate of that
    entry's numbers, not a genuine sounding. It slipped past
    _merge_split_entries because _looks_like_fresh_entry treats
    item_number=="11.1" as the tell of a genuine new block on its own --
    which is normally right, but not when there's no tank name attached to
    back it up. This runs as its own late pass rather than folding the check
    into _looks_like_fresh_entry, so a legitimately-tanked 11.1 entry is
    never at risk of being reclassified as a continuation by that stricter
    upstream logic -- this only ever removes the narrow, unambiguous case of
    no tank name at all.
    """
    kept = []
    for entry in entries_data:
        item = (entry.get("item_number") or "").strip()
        if entry.get("orb_code") == "C" and item == "11.1" and not (entry.get("tank_location") or "").strip():
            logger.warning(
                f"Dropped untanked Code C 11.1 fragment (no tank_location -- not a real sounding): "
                f"date={entry.get('entry_date')} raw_text={entry.get('raw_text')!r}"
            )
            continue
        kept.append(entry)
    return kept


def _flag_self_referential_transfers(entries_data: list[dict]) -> list[dict]:
    """A transferred/collected quantity can never have the same tank as both
    from_tank and to_tank -- moving a tank's contents into itself is
    physically impossible, so this always means one of the two tank names
    was misread (confirmed in production: "INCINERATOR WASTE OIL SETTLING
    TANK" read as both source AND destination, when the destination should
    have read "...SERVICE TANK" -- see the REPEATED NEAR-IDENTICAL BLOCKS
    prompt section above, which now warns against this specific mistake).

    There's no reliable way to guess which side is the wrong one from the
    parsed fields alone, so this doesn't try to auto-correct -- guessing
    wrong would silently replace one bad value with a different bad value.
    Instead it lowers confidence_score so the entry surfaces for manual
    review (consistent with how DATE DIGIT AMBIGUITY signals doubt via
    confidence_score elsewhere in this pipeline) and logs the specific
    entry so it shows up in extraction logs even before a human looks at it.

    Deliberately excludes "bunkered": for a 26.3/26.4 per-tank bunkering
    line the prompt never asks for a from_tank at all, so run_extraction's
    post-processing defaults it to the entry's own tank_location -- which
    can legitimately coincide with to_tank for a single-tank bunkering entry.
    That's a normal default filling an intentionally-blank field, not a
    misread, so flagging it here would just be noise."""
    for entry in entries_data:
        for q in entry.get("quantities") or []:
            qtype = q.get("qty_type") or q.get("type")
            from_tank = (q.get("from_tank") or "").strip().upper()
            to_tank = (q.get("to_tank") or "").strip().upper()
            if qtype in ("transferred", "collected") and from_tank and to_tank and from_tank == to_tank:
                logger.warning(
                    f"Self-referential {qtype} quantity (same tank on both ends) -- likely a "
                    f"misread destination tank name: date={entry.get('entry_date')} "
                    f"code={entry.get('orb_code')} item={entry.get('item_number')} "
                    f"tank={q.get('from_tank')!r} qty_value={q.get('qty_value')}"
                )
                conf = entry.get("confidence_score")
                entry["confidence_score"] = min(conf, 0.5) if conf is not None else 0.5
    return entries_data


def _flag_retained_exceeds_capacity(entries_data: list[dict]) -> list[dict]:
    """A tank's retained volume can never exceed its own capacity -- that's
    physically impossible, so it always means at least one of the two
    figures was misread (confirmed in production: several confirmed digit
    misreads on retained/capacity figures throughout this pipeline's history
    had no safety net at all for the "retained" side, unlike capacity which
    has the per-tank majority-vote corrector above).

    Deliberately does NOT try to auto-correct, for the same reason
    _flag_self_referential_transfers doesn't: there's no reliable way to
    tell from the parsed fields alone whether the capacity or the retained
    figure is the wrong one, so guessing risks silently replacing one bad
    value with a different bad one. Instead this lowers confidence_score so
    the entry surfaces for manual review, same pattern as every other
    physically-impossible-value check in this pipeline.
    """
    for entry in entries_data:
        qtys = entry.get("quantities") or []
        cap = None
        for q in qtys:
            if (q.get("qty_type") or q.get("type")) == "capacity":
                try:
                    cap = float(q.get("qty_value") if q.get("qty_value") is not None else q.get("value"))
                except (TypeError, ValueError):
                    cap = None
        if cap is None:
            continue
        for q in qtys:
            if (q.get("qty_type") or q.get("type")) != "retained":
                continue
            try:
                ret = float(q.get("qty_value") if q.get("qty_value") is not None else q.get("value"))
            except (TypeError, ValueError):
                continue
            if ret > cap * 1.05:  # small margin for legitimate rounding, not a real tolerance
                logger.warning(
                    f"Retained ({ret}) exceeds this tank's own capacity ({cap}) -- physically "
                    f"impossible, likely a digit misread on the capacity or retained figure: "
                    f"date={entry.get('entry_date')} code={entry.get('orb_code')} "
                    f"tank={entry.get('tank_location')!r}"
                )
                conf = entry.get("confidence_score")
                entry["confidence_score"] = min(conf, 0.4) if conf is not None else 0.4
    return entries_data


# (orb_code, item_number) combinations that ALWAYS carry at least one
# quantity reading in a genuine, fully-captured entry (see the QUANTITY
# RULES section of EXTRACTION_SYSTEM_PROMPT). An entry matching one of these
# but holding zero quantities isn't "a block that just happens to need no
# numbers" -- it's a signal the entry's content was cut off before Gemini
# ever saw the rest of it (most commonly: the block's tail, including its
# CAP/RETD figures and both officer signatures, sat right on a stacked-page
# split's crop line and was lost entirely -- confirmed in production, ORB
# SCAN COPIES upload, page 9: a Code D item-13 bilge-pumping block with no
# quantities and no officers in Gemini's own JSON, i.e. genuinely never
# read, not merely a blank signature cell).
_QUANTITY_ALWAYS_EXPECTED = {("D", "13")} | {("H", i) for i in ("26.3", "26.4")}


def _looks_structurally_incomplete(entry: dict) -> bool:
    code = entry.get("orb_code")
    item = (entry.get("item_number") or "").strip()
    qtys = entry.get("quantities") or []
    expects_qty = (code, item) in _QUANTITY_ALWAYS_EXPECTED or (
        code == "C" and (item.startswith("11") or item.startswith("12"))
    )
    if expects_qty and not qtys:
        return True

    # A "transferred" quantity is never a complete block on its own -- per
    # QUANTITY RULES above, both a 12.2 transfer and a Code D 15.3 transfer
    # are always paired with a "retained" reading for where the material
    # ended up. Confirmed in production (ORB SCAN COPIES upload, page 9,
    # second 11-JAN-2026 Code D block): "transferred" 2.0 m3 with NO
    # "retained" at all -- the block's tail (its CAP/RETD figures and both
    # signatures) never made it into this crop, but the "not (quantities)"
    # check above missed it because one partial quantity WAS present. A
    # disposed-overboard block (15.1/15.2) legitimately has no retained
    # figure at all -- this only fires when "transferred" itself is present
    # without its required partner, not merely "no retained anywhere".
    qty_types = {(q.get("qty_type") or q.get("type")) for q in qtys}
    if "transferred" in qty_types and "retained" not in qty_types:
        return True

    return False


def _propagate_shared_officer(entries_data: list[dict]) -> list[dict]:
    """Fill in a missing officer signature from same-day siblings.

    A day's whole cluster of block entries (e.g. five separate C/11.1 tank
    soundings) is typically co-signed ONCE, not once per row. The model
    reliably reads that single signature but attaches it only to whichever
    entry sits closest to it on the page, leaving the other same-day rows
    with a blank officer even though there is really only one signature for
    all of them. Only fill the gap when the date has exactly one distinct
    officer among its non-blank entries — if two different names appear that
    day (genuinely separate blocks signed by different officers), leave the
    blanks alone rather than guessing which one applies.

    NEVER fill a structurally incomplete entry (see
    _looks_structurally_incomplete) even when the day's signature is
    otherwise unanimous. Confirmed in production (ORB SCAN COPIES upload,
    page 9, 11-JAN-2026): a Code D pumping block was cut off by a page-split
    crop before Gemini ever reached its quantities or its own signature line
    (both null in Gemini's own JSON) -- this function then filled in
    "RISHIKESH JAMDAR" as officer_2 anyway, because every OTHER entry that
    same day happened to be co-signed by him. That produced a record that
    *looks* fully signed-off while its actual operational data (how much
    bilge water, how much retained) is silently missing -- worse than
    leaving it blank, since a blank at least signals "incomplete" instead of
    masking it. A genuinely missing signature on an otherwise complete entry
    (has its own quantities) is still exactly what this function is meant to
    fix and is unaffected by this guard.
    """
    from collections import defaultdict

    def _date_key(raw: str | None) -> str:
        raw = (raw or "").strip()
        try:
            return str(parse_entry_date(raw))
        except ValueError:
            return raw.lower()

    def _name_key(raw: str | None) -> str:
        # Collapses spacing/case drift ("M. SATHIK" vs "M.SATHIK" vs "m.sathik")
        # so the same real person is recognized as a single distinct signer.
        return re.sub(r"\s+", "", (raw or "")).upper()

    by_date: dict[str, list[dict]] = defaultdict(list)
    for e in entries_data:
        by_date[_date_key(e.get("entry_date"))].append(e)

    for _, es in by_date.items():
        if len(es) < 2:
            continue
        for officer_field, rank_field in (("officer_1_name", "officer_1_rank"), ("officer_2_name", "officer_2_rank")):
            named = [e for e in es if _name_key(e.get(officer_field))]
            distinct_names = {_name_key(e.get(officer_field)) for e in named}
            if len(distinct_names) != 1:
                continue  # none, or more than one distinct signer that day — don't guess
            source = named[0]
            for e in es:
                if not _name_key(e.get(officer_field)) and not _looks_structurally_incomplete(e):
                    e[officer_field] = source.get(officer_field)
                    e[rank_field] = e.get(rank_field) or source.get(rank_field)
    return entries_data


_CAPACITY_TEXT_RE = re.compile(
    r"(CAP(?:ACITY)?\s*[.:=\-]?\s*)(\d+(?:\.\d+)?)(\s*m³?3?)",
    re.IGNORECASE,
)


def _rewrite_capacity_mention(text: str, old_value: float, new_value: float) -> tuple[str, bool]:
    """Rewrite a "CAP[ACITY] <old_value>" mention in free text to show the
    corrected value, instead of leaving the description showing a number its
    own quantities table now contradicts. Confirmed in production: a
    capacity correction fixed the structured qty_value but left the visible
    "CAP: 18.9 m3" text in the description completely unchanged, with only a
    small trailing note (sometimes landing after an unrelated RETAINED
    mention) explaining a correction the reader can't actually see reflected
    anywhere in the primary text they're looking at.

    Matches loosely on the number near a CAP/CAPACITY label (within a small
    tolerance) rather than requiring an exact substring, since the same
    figure can appear with different trailing-zero/decimal formatting than
    the already-rounded value being corrected (e.g. "18.90" in the text vs
    18.9 as the stored qty_value). Returns (new_text, replaced) -- replaced
    is False when no matching mention was found, so the caller can fall back
    to a trailing note instead of silently doing nothing.
    """
    if not text:
        return text, False

    def _repl(m):
        try:
            found = float(m.group(2))
        except ValueError:
            return m.group(0)
        if abs(found - old_value) > 0.005:
            return m.group(0)
        note = (
            f" [auto-corrected from {old_value:g} m3 -- this tank's capacity reads "
            f"{new_value:g} m3 consistently elsewhere in this log]"
        )
        return f"{m.group(1)}{new_value:g}{m.group(3)}{note}"

    new_text = _CAPACITY_TEXT_RE.sub(_repl, text, count=1)
    return new_text, new_text != text


def _reconcile_tank_capacity_readings(entries_data: list[dict]) -> list[dict]:
    """Correct a lone misread 'capacity' figure using the tank's own other readings.

    A tank's physical capacity is a fixed constant -- it must read identically
    every single time that tank is sounded, unlike "retained" which genuinely
    changes over time. So when one entry's capacity value disagrees with the
    clear majority of that same tank's other capacity readings elsewhere in
    this document, that lone outlier is almost certainly a vision misread of
    messy handwriting (e.g. a stray pen mark on a decimal being read as an
    extra digit -- "2.9" misread as "2.0") rather than a real change, and is
    corrected to the majority value instead of surfacing as a false
    "transcription error" compliance alert against a perfectly correct log.
    """
    from collections import defaultdict, Counter

    def _tank_key(raw: str | None) -> str:
        cleaned = re.sub(r"[#.\-]", " ", raw or "")
        return re.sub(r"\s+", " ", cleaned.upper().strip())

    by_tank: dict[str, list[dict]] = defaultdict(list)
    for entry in entries_data:
        tk = _tank_key(entry.get("tank_location"))
        if not tk:
            continue
        for q in entry.get("quantities") or []:
            if (q.get("qty_type") or q.get("type")) == "capacity":
                by_tank[tk].append(q)

    # Every quantity dict retains a back-reference to its owning entry (set
    # while building by_tank below) purely so a correction here can also
    # patch that entry's operation_description -- without this, the
    # structured qty_value gets silently corrected while the free-text
    # description/raw_text keeps showing the original misread number,
    # producing an entry that visibly contradicts its own quantities table
    # (confirmed in production: "F.O. SLUDGE TANK CAPACITY - 19.1 m3" in the
    # description sitting right above a quantities table showing capacity
    # 40.8 -- correct value, but with no explanation of why it differs from
    # what the entry's own text says, which reads as data corruption even
    # though the correction itself was right).
    for entry in entries_data:
        tk = _tank_key(entry.get("tank_location"))
        if not tk:
            continue
        for q in entry.get("quantities") or []:
            if (q.get("qty_type") or q.get("type")) == "capacity":
                q["_owning_entry"] = entry

    for _, qtys in by_tank.items():
        if len(qtys) < 3:
            continue  # too few readings to trust a majority over the lone extractor call
        values = []
        for q in qtys:
            try:
                values.append(round(float(q.get("qty_value") if q.get("qty_value") is not None else q.get("value")), 2))
            except (TypeError, ValueError):
                pass
        if not values:
            continue
        majority_value, majority_count = Counter(values).most_common(1)[0]
        if majority_count < 2 or majority_count <= len(values) / 2:
            continue  # no clear consensus reading -- don't guess
        # No magnitude cap on the correction: the majority-vote requirement
        # above (same tank, 3+ readings, a true majority) is already the
        # safety net. A misread can be wildly off (e.g. "2.9" -> "20.9" from
        # a stray mark before the decimal), and capping by how far off it is
        # would let exactly the worst misreads slip through uncorrected.
        for q in qtys:
            try:
                v = round(float(q.get("qty_value") if q.get("qty_value") is not None else q.get("value")), 2)
            except (TypeError, ValueError):
                continue
            if v != majority_value:
                q["qty_value"] = majority_value
                owner = q.pop("_owning_entry", None)
                if owner is not None:
                    desc = owner.get("operation_description") or ""
                    new_desc, replaced = _rewrite_capacity_mention(desc, v, majority_value)
                    if replaced:
                        owner["operation_description"] = new_desc
                    else:
                        # Fallback for unusual formatting the regex didn't
                        # recognize -- still explain the correction rather
                        # than silently changing the number with no visible
                        # trace, even though it can't be placed inline here.
                        note = (
                            f" [Capacity auto-corrected: this entry originally read {v} m3, but "
                            f"this tank's capacity reads {majority_value} m3 consistently elsewhere "
                            f"in this log -- {v} m3 is very likely a misread, not a real change.]"
                        )
                        owner["operation_description"] = desc + note
                    raw = owner.get("raw_text") or ""
                    new_raw, _ = _rewrite_capacity_mention(raw, v, majority_value)
                    owner["raw_text"] = new_raw
                    # A corrected entry must never be left looking MORE
                    # trustworthy than it actually is. Confirmed in
                    # production: a large capacity correction (e.g. 40.8 ->
                    # 3.3, matching a DIFFERENT tank entirely) is frequently
                    # not a simple digit misread at all, but the visible
                    # symptom of the whole reading having been misattributed
                    # from a fabricated/misattached continuation (see the
                    # NEVER GLUE TOP-OF-PAGE CONTENT prompt section) --
                    # leaving confidence_score untouched at its original 0.9
                    # made exactly that kind of entry look MORE reliable
                    # than an honestly-uncertain one, which is backwards. A
                    # small correction (a plausible single-digit slip) still
                    # gets a milder penalty, since that case is far more
                    # likely to just be what it looks like.
                    relative_change = abs(v - majority_value) / majority_value if majority_value else 1.0
                    conf_cap = 0.4 if relative_change > 0.3 else 0.7
                    conf = owner.get("confidence_score")
                    owner["confidence_score"] = min(conf, conf_cap) if conf is not None else conf_cap

    for entry in entries_data:
        for q in entry.get("quantities") or []:
            q.pop("_owning_entry", None)

    return entries_data


_WEEKLY_INVENTORY_RE = re.compile(r"WEEKLY\s+INVENTORY\s+OF\s+BILGE\s*(?:HOLDING)?\s*TANK", re.IGNORECASE)


def _split_swallowed_weekly_inventory(entries_data: list[dict]) -> list[dict]:
    """Un-swallow a Code I weekly bilge inventory that got folded into the
    preceding Code C block instead of becoming its own entry.

    This is the single most common real-world entry-boundary miss: on this
    vessel's log, a "WEEKLY INVENTORY OF BILGE TANK" remark almost always
    sits directly under the last C/11.x tank sounding of the day, on the same
    page, with no blank line or page break between them — exactly the case
    where the model tends to keep appending to the block it's already writing
    instead of recognizing the fresh Date+Code that starts the inventory
    entry. Confirmed happening repeatedly (8 times in one 47-page document)
    even with prompting aimed at this — so it also gets a deterministic
    safety net here, the same way _is_signature_block backstops signature
    detection. The phrase is specific enough (this vessel always writes it
    verbatim) that splitting on it is safe rather than a blunt heuristic.
    """
    result: list[dict] = []
    for entry in entries_data:
        raw = entry.get("raw_text") or ""
        match = _WEEKLY_INVENTORY_RE.search(raw)
        if entry.get("orb_code") != "I" and match and match.start() > 0:
            before_raw = raw[:match.start()].strip()
            after_raw = raw[match.start():].strip()

            desc = entry.get("operation_description") or ""
            desc_match = _WEEKLY_INVENTORY_RE.search(desc)
            if desc_match:
                before_desc = desc[:desc_match.start()].strip()
                after_desc = desc[desc_match.start():].strip()
            else:
                before_desc, after_desc = desc, after_raw

            # Split quantities by POSITION, not by their own from_tank/to_tank
            # text -- the swallowed continuation's quantities are often tagged
            # with a generic/inherited tank name (e.g. plain "TANK") rather
            # than "BILGE TANK", so text matching silently fails and leaves
            # everything on the original entry. A single tank-sounding block
            # always has exactly one capacity + one retained value, in order,
            # so everything through the first capacity->retained pair belongs
            # to the original (pre-match) entry; anything after that is the
            # swallowed continuation's own reading.
            quantities = entry.get("quantities") or []
            split_idx = len(quantities)
            seen_capacity = False
            for i, q in enumerate(quantities):
                qtype = q.get("qty_type") or q.get("type")
                if qtype == "capacity":
                    seen_capacity = True
                elif qtype == "retained" and seen_capacity:
                    split_idx = i + 1
                    break
            remaining_qtys = quantities[:split_idx]
            inventory_qtys = quantities[split_idx:]

            entry["raw_text"] = before_raw
            entry["operation_description"] = before_desc
            entry["quantities"] = remaining_qtys
            result.append(entry)

            new_entry = dict(entry)
            new_entry["orb_code"] = "I"
            new_entry["item_number"] = None
            new_entry["tank_location"] = "BILGE TANK"
            new_entry["raw_text"] = after_raw
            new_entry["operation_description"] = after_desc
            new_entry["quantities"] = inventory_qtys
            new_entry["is_continuation"] = False
            result.append(new_entry)
        else:
            result.append(entry)
    return result


# Digit pairs commonly confused in handwriting, used only to auto-correct a
# single misread day-digit when it's the sole thing breaking chronological
# order (see _reconcile_chronology below). "7" can plausibly be misread as
# either "1" or "6" (and vice versa for each), so values are tuples of every
# plausible alternate, not a single one -- a dict of single values can't
# express that "7" has two, not one, confusable partners.
_DIGIT_CONFUSIONS = {
    "9": ("5",), "5": ("9",),
    "1": ("7",), "7": ("1", "6", "8"),
    "3": ("8",), "8": ("3", "7"),
    "0": ("6",), "6": ("0", "7", "4"),
    "4": ("6",),
}

# Below this confidence_score, the extractor itself flagged the date's digits
# as genuinely hard to distinguish (see the DATE DIGIT AMBIGUITY prompt
# section) -- only then is it safe to reconsider the date at all.
_DATE_AMBIGUITY_CONFIDENCE_THRESHOLD = 0.8


def _reconcile_chronology(entries_data: list[dict]) -> list[dict]:
    """Auto-correct a single misread day-digit when it's the only thing
    putting an entry out of chronological order.

    Handwriting confuses a small set of digit pairs (9/5, 1/7, 3/8, 0/6)
    often enough that an entry genuinely written on, say, the 19th gets
    misread as the 15th, landing it right after a 17th-dated entry -- out of
    order despite being written correctly by the officer.

    Two independent gates must BOTH pass before a date is touched:

    1. confidence_score must be below _DATE_AMBIGUITY_CONFIDENCE_THRESHOLD.
       A date the model read as clearly legible must never be second-guessed
       just because it's chronologically inconvenient -- a clearly-written
       date that happens to precede an earlier entry is exactly the case
       check_chronology_and_erasures exists to surface as a real compliance
       issue (a genuine backdated/reordered entry), not something to quietly
       rewrite. Only when the model itself flagged doubt about this specific
       date's digits is a swap even considered.

    2. Exactly ONE single-digit swap must uniquely restore order relative to
       BOTH the previous and next known dates. If no swap resolves it, or
       more than one equally would, nothing here is confident enough to
       apply -- left alone for the compliance check instead.
    """
    parsed: list[tuple[dict, "date | None", str]] = []
    for e in entries_data:
        raw = (e.get("entry_date") or "").strip()
        try:
            parsed.append((e, parse_entry_date(raw), raw))
        except ValueError:
            parsed.append((e, None, raw))

    running_max = None
    for i, (entry, d, raw) in enumerate(parsed):
        if d is None:
            continue

        confidence = entry.get("confidence_score")
        date_flagged_ambiguous = confidence is not None and confidence < _DATE_AMBIGUITY_CONFIDENCE_THRESHOLD

        if running_max is not None and d < running_max and date_flagged_ambiguous:
            next_date = next((pd for _, pd, _ in parsed[i + 1:] if pd is not None), None)

            m = re.match(r"^(\d{1,2})(-.+)$", raw)
            candidates = []
            if m:
                day_str, rest = m.group(1), m.group(2)
                for pos, ch in enumerate(day_str):
                    alts = _DIGIT_CONFUSIONS.get(ch) or ()
                    for alt in alts:
                        new_day = day_str[:pos] + alt + day_str[pos + 1:]
                        if not new_day.isdigit() or not (1 <= int(new_day) <= 31):
                            continue
                        candidate_str = f"{new_day}{rest}"
                        try:
                            candidate_date = parse_entry_date(candidate_str)
                        except ValueError:
                            continue
                        if candidate_date < running_max:
                            continue
                        if next_date is not None and candidate_date > next_date:
                            continue
                        candidates.append((candidate_str, candidate_date))

            if len(candidates) == 1:
                candidate_str, candidate_date = candidates[0]
                logger.warning(
                    f"Chronology auto-correction: entry dated {raw!r} was out of "
                    f"order (after {running_max}) -- corrected to {candidate_str!r}"
                )
                entry["entry_date"] = candidate_str
                d = candidate_date

        if running_max is None or d > running_max:
            running_max = d

    return entries_data


def _qty_content_signature(qty_dicts: list[dict]) -> tuple:
    """Order-independent signature of a raw entry_dict's quantities, ignoring
    date -- used only to detect duplicate-extraction content collisions in
    _dedupe_cross_date_duplicates below, kept separate from run_extraction's
    own _qty_signature (which operates on already-parsed DB rows)."""
    sig = []
    for q in qty_dicts:
        qtype = q.get("qty_type") or q.get("type") or ""
        qval = q.get("qty_value") if q.get("qty_value") is not None else q.get("value")
        try:
            qval = round(float(qval), 2) if qval is not None else None
        except (TypeError, ValueError):
            qval = None
        to_tank = (q.get("to_tank") or "").upper().strip()
        sig.append((qtype, qval, to_tank))
    return tuple(sorted(sig, key=lambda t: (t[0], t[1] is None, t[1] if t[1] is not None else 0.0, t[2])))


_TRAILING_DATE_RE = re.compile(r"(\d{1,2})[\-\s]([A-Z]{3})[\-\s](\d{4}|\d{2})")


def _reconcile_entry_date_vs_own_header(entries_data: list[dict]) -> list[dict]:
    """Correct entry_date when it disagrees with the FIRST date mention in
    this entry's own raw_text (normally the leading Date-column header),
    provided every OTHER date mention in that same raw_text (normally the
    officer signatures) agrees with that first one too.

    Deliberately NOT gated on confidence_score, unlike
    _reconcile_entry_date_vs_own_signature below. That function protects a
    genuinely ambiguous case -- the header and a signature disagree with
    EACH OTHER, and only a low confidence_score tells you Gemini itself
    wasn't sure which one to trust. This function targets a different,
    unambiguous case: the entry's own transcribed text (header AND every
    signature) all agree with ONE ANOTHER, and only the separate structured
    entry_date field disagrees with all of them. That's not a legibility
    judgment call -- Gemini already told you what it read, twice, and both
    readings agree; the entry_date field is simply stale relative to what
    Gemini itself transcribed. Confirmed in production (ORB SCAN COPIES
    upload): a 01-FEB-2026 entry had "01 FEB 2026" written in its own header
    AND on both officer signatures (confidence_score 0.9, so the
    confidence-gated function below never even looked at it), yet
    entry_date was stuck at 31-JAN-2026 -- a field-sync bug, not a reading
    disagreement. Runs BEFORE the confidence-gated majority-vote function so
    these clear-cut cases are fixed unconditionally first, leaving genuinely
    ambiguous cases (where the transcribed mentions really do disagree with
    each other) to that function's confidence gate.
    """
    for entry in entries_data:
        raw_text = entry.get("raw_text") or ""
        if not raw_text:
            continue
        matches = list(_TRAILING_DATE_RE.finditer(raw_text.upper()))
        if not matches:
            continue
        try:
            header_date = parse_entry_date(
                f"{matches[0].group(1)}-{matches[0].group(2)}-{matches[0].group(3)}"
            )
        except ValueError:
            continue
        try:
            entry_date_parsed = parse_entry_date((entry.get("entry_date") or "").strip())
        except ValueError:
            continue
        if header_date == entry_date_parsed:
            continue

        other_dates = set()
        for m in matches[1:]:
            try:
                other_dates.add(parse_entry_date(f"{m.group(1)}-{m.group(2)}-{m.group(3)}"))
            except ValueError:
                continue
        if other_dates and other_dates != {header_date}:
            continue  # genuine internal disagreement -- leave to the confidence-gated function

        logger.warning(
            f"entry_date {entry.get('entry_date')!r} disagreed with the date this entry's "
            f"own raw_text otherwise agrees with internally ({header_date}) -- correcting "
            f"as a field-sync issue, not a legibility judgment call. "
            f"code={entry.get('orb_code')} item={entry.get('item_number')} "
            f"tank={entry.get('tank_location')!r}"
        )
        entry["entry_date"] = header_date.strftime("%d-%b-%Y").upper()
    return entries_data


def _reconcile_entry_date_vs_own_signature(entries_data: list[dict]) -> list[dict]:
    """Correct entry_date by majority vote across every date mention inside
    that SAME entry's own raw_text (leading Date-column header, and every
    officer signature), rather than trusting any one position (leading vs
    trailing) as always authoritative.

    A fixed priority order was tried first and confirmed wrong: an early
    version always trusted the leading header over the trailing signature,
    reasoning the header is "the real Date-column reading." That holds for
    cases where the header is right and a signature merely lags -- but a
    confirmed production case did the exact opposite: entry_date and the
    leading header both read "16 FEB 2026", while BOTH officers' signatures
    independently read "14 FEB 2026" -- the header itself was the misread
    one (a 4/6 digit confusion), and two independent signatures agreeing
    with each other is stronger evidence than one Date-column reading.
    Fixing the priority order the other way would just as surely break the
    original case it was built for (leading header right, one signature
    wrong). Majority vote across ALL date mentions handles both correctly
    without needing to know in advance which position is more reliable:

      - header "07 FEB", sig1 "07 FEB", sig2 "06 FEB", entry_date "06 FEB"
        -> "07 FEB" wins 2-1 over entry_date's own 1 -> corrected to 07 FEB.
      - no header, sig1 "31 JAN", sig2 "31 JAN", entry_date "30 JAN"
        -> "31 JAN" wins 2-0 over entry_date's own 0 -> corrected to 31 JAN.
      - header "16 FEB", sig1 "14 FEB", sig2 "14 FEB", entry_date "16 FEB"
        -> "14 FEB" wins 2-1 over entry_date's own 1 -> corrected to 14 FEB.
      - header "08 MAR" (== entry_date), sig "07 MAR" (legitimate late
        signature) -> 1-1 tie, entry_date already has equal support ->
        left alone, exactly the "don't guess" case this must never touch.

    Only acts when a strict majority (more votes than entry_date's own
    count) exists for a single alternative date -- a tie changes nothing,
    by design: this only corrects when the evidence is unambiguous, never
    when it's a coin flip between two equally-supported readings.

    Gated on confidence_score being below _DATE_AMBIGUITY_CONFIDENCE_
    THRESHOLD (the same threshold _reconcile_chronology already uses for
    this exact reason). The 16-FEB/14-FEB case above is a genuine digit
    misread -- per the extraction prompt's own instructions, Gemini is
    supposed to score that kind of ambiguity 0.6-0.75, not 0.9+. So a high
    confidence_score means Gemini was NOT signalling doubt about this
    entry's digits, and majority-voting a confidently-read header down
    based on signature dates elsewhere in the text stops being a misread
    correction and starts being something else entirely: a genuine but
    UNRELATED clerical slip, where an officer simply wrote the wrong date
    on their OWN signature line (perfectly legible, just wrong -- e.g.
    signing off with yesterday's date near a day boundary). Confirmed in
    production TWICE: a freshly, deliberately written "13 JAN 2026" header
    (confidence 0.9, repeated on an adjacent block on the same page) got
    wrongly overridden to "12 JAN" because both officers had signed with
    the previous day's date; same pattern again with a "25 JAN 2026"
    header overridden to "24 JAN". Both entries were entirely correct as
    read -- the signatures were the ones that (legitimately) lagged.
    Requiring low confidence before this correction fires still catches
    the genuine misread case it was built for, without punishing a
    confidently, correctly read header for an officer's own dating slip.
    """
    from collections import Counter

    for entry in entries_data:
        confidence = entry.get("confidence_score")
        if confidence is not None and confidence >= _DATE_AMBIGUITY_CONFIDENCE_THRESHOLD:
            continue  # Gemini itself wasn't signalling any digit ambiguity here

        raw = (entry.get("entry_date") or "").strip()
        try:
            entry_date_parsed = parse_entry_date(raw)
        except ValueError:
            continue

        raw_text = (entry.get("raw_text") or "")
        found_dates = []
        for m in _TRAILING_DATE_RE.finditer(raw_text.upper()):
            try:
                found_dates.append(parse_entry_date(f"{m.group(1)}-{m.group(2)}-{m.group(3)}"))
            except ValueError:
                continue
        if not found_dates:
            continue

        counts = Counter(found_dates)
        entry_count = counts.get(entry_date_parsed, 0)
        best_date, best_count = counts.most_common(1)[0]
        if best_date == entry_date_parsed or best_count <= entry_count:
            continue  # no alternative strictly outvotes entry_date -- leave it alone

        logger.warning(
            f"entry_date {raw!r} outvoted by other date mentions in this entry's own "
            f"raw_text ({best_date} appears {best_count}x vs entry_date's {entry_count}x) -- "
            f"correcting to it. code={entry.get('orb_code')} item={entry.get('item_number')} "
            f"tank={entry.get('tank_location')!r}"
        )
        entry["entry_date"] = best_date.strftime("%d-%b-%Y").upper()

    return entries_data


def _dedupe_cross_date_duplicates(entries_data: list[dict]) -> list[dict]:
    """Drop an entry that is a duplicate re-extraction of another entry a
    few days apart under a different (wrong) date.

    Traced in production on a two-book-page spread scan (AM KIRTI): the same
    physical Code C sludge-transfer block got extracted twice across two
    page-level Gemini calls -- once correctly dated, once with the date
    field mis-set to a neighbouring day. Both copies were fully legible
    (confidence 0.9-1.0), so the existing chronology-correction safety net
    (which only reconsiders a date below a confidence threshold) never
    caught it. The tell: a real ORB entry's raw_text ends with the signing
    officers' names followed by the date they actually signed -- on the
    genuine copy that trailing date always matches the entry's own
    entry_date; on the mis-dated duplicate it doesn't, because only the
    entry_date field was corrupted, not the transcribed signature text.

    Only engages when the SAME (code, item_number, tank, quantities) combo
    appears more than once within a short (<=3 day) window under different
    dates -- a coincidence real independent operations essentially never
    produce, since retained/transferred quantities drift day to day. A
    vessel whose scan is already one page per image (no spread-splitting
    ever happens for it) essentially never triggers this grouping at all,
    so this is a no-op there.
    """
    groups: dict[tuple, list[dict]] = {}
    for e in entries_data:
        tank = re.sub(r"\s+", " ", (e.get("tank_location") or "").upper().strip())
        qty_sig = _qty_content_signature(e.get("quantities") or [])
        if not tank or not qty_sig:
            continue  # nothing distinctive enough to judge safely
        key = (e.get("orb_code"), (e.get("item_number") or "").strip(), tank, qty_sig)
        groups.setdefault(key, []).append(e)

    to_drop: set[int] = set()
    for key, group in groups.items():
        if len(group) < 2:
            continue
        dated = []
        for e in group:
            try:
                dated.append((e, parse_entry_date((e.get("entry_date") or "").strip())))
            except ValueError:
                continue
        distinct_dates = {d for _, d in dated}
        if len(distinct_dates) < 2:
            continue  # same date -- not this bug, leave to the normal fingerprint dedup
        if max(distinct_dates) - min(distinct_dates) > timedelta(days=3):
            continue  # too far apart to plausibly be the same mis-dated block

        def _signature_date_matches(e: dict) -> bool:
            raw = e.get("raw_text") or ""
            matches = list(_TRAILING_DATE_RE.finditer(raw.upper()))
            if not matches:
                return True  # nothing to contradict with -- don't penalize
            last = matches[-1]
            try:
                sig_date = parse_entry_date(f"{last.group(1)}-{last.group(2)}-{last.group(3)}")
            except ValueError:
                return True
            try:
                return sig_date == parse_entry_date((e.get("entry_date") or "").strip())
            except ValueError:
                return True

        consistent = [e for e, _ in dated if _signature_date_matches(e)]
        keep_pool = consistent if consistent else [e for e, _ in dated]
        keep = keep_pool[0]
        for e, _ in dated:
            if e is not keep and id(e) not in to_drop:
                to_drop.add(id(e))
                logger.warning(
                    f"Dropped cross-date duplicate entry: code={key[0]} item={key[1]} "
                    f"tank={key[2]} date={e.get('entry_date')} (kept date={keep.get('entry_date')})"
                )

    return [e for e in entries_data if id(e) not in to_drop]


def _flag_fused_continuation_entries(entries_data: list[dict]) -> list[dict]:
    """Flag an entry whose own raw_text shows signs of two separate
    operations fused into one -- a mechanical backstop for cases the
    boundary re-check (see _call_boundary_recheck) and prompt guidance
    still miss. Confirmed in production repeatedly (ORB SCAN COPIES
    upload): every confirmed case of this shape had noticeably MORE than
    the normal two rank/signature tokens (3+ instead of 2, since a second
    operation brings its own sign-off along) AND two or more genuinely
    different calendar dates mentioned within that SAME entry's raw_text --
    not just a header vs. one lagging signature (that legitimate case, and
    the genuine digit-misread case, both still only ever produce exactly
    two rank tokens; requiring 3+ is what tells them apart from this).

    Runs AFTER the date-reconciliation passes, so any entry whose apparent
    "two dates" were really just a resolvable header/signature mismatch has
    already been cleaned up by then -- what's left showing 2+ distinct
    dates at this point is a stronger signal of genuinely mixed content.

    Deliberately does NOT attempt to auto-split the entry. By this point in
    the pipeline the two halves' quantities are already merged into one
    flat structured list with no reliable way to know from field values
    alone which quantity belongs to which half -- guessing wrong would
    silently produce a NEW, differently-corrupted split instead of fixing
    the original one. Flagging for manual review is the safe fallback here.
    """
    for entry in entries_data:
        raw_text = entry.get("raw_text") or ""
        if not raw_text:
            continue
        rank_hits = len(re.findall(_RANK_TOKEN, raw_text, re.IGNORECASE))
        dates_found = set()
        for m in _TRAILING_DATE_RE.finditer(raw_text.upper()):
            try:
                dates_found.add(parse_entry_date(f"{m.group(1)}-{m.group(2)}-{m.group(3)}"))
            except ValueError:
                continue
        if rank_hits < 3 or len(dates_found) < 2:
            continue
        logger.warning(
            f"Entry shows {rank_hits} rank/signature tokens and {len(dates_found)} distinct "
            f"dates within its own raw_text -- likely two separate operations fused into one "
            f"entry: date={entry.get('entry_date')} code={entry.get('orb_code')} "
            f"tank={entry.get('tank_location')!r}"
        )
        conf = entry.get("confidence_score")
        entry["confidence_score"] = min(conf, 0.3) if conf is not None else 0.3
        note = (
            " [Flagged: this entry's text shows signs of two separate operations merged "
            "together (multiple sign-offs, multiple dates) -- please verify against the "
            "source page.]"
        )
        if "Flagged: this entry's text shows signs of two separate operations" not in (entry.get("operation_description") or ""):
            entry["operation_description"] = (entry.get("operation_description") or "") + note
    return entries_data


async def run_extraction(
    upload_id: uuid.UUID,
    storage_path: str,
    vessel_id: uuid.UUID,
    session_factory: async_sessionmaker,
):
    """Background task: extract entries from uploaded PDF and run calculations."""
    async with session_factory() as db:
        try:
            result = await db.execute(sa_select(OrbUpload).where(OrbUpload.id == upload_id))
            upload = result.scalar_one_or_none()
            if not upload:
                return

            upload.status = "processing"
            await db.commit()

            vessel_result = await db.execute(sa_select(Vessel).where(Vessel.id == vessel_id))
            vessel = vessel_result.scalar_one_or_none()

            failed_pages: list[int] = []
            if settings.USE_MOCK_EXTRACTION:
                entries_data = get_mock_data(vessel_id, upload_id)
            else:
                try:
                    entries_data, failed_pages = await extract_with_gemini(
                        storage_path, upload_id=upload_id, session_factory=session_factory,
                        expected_vessel_name=vessel.name if vessel else None,
                    )
                except VesselMismatchError as e:
                    logger.warning(f"Upload {upload_id} rejected: {e}")
                    upload.status = "failed"
                    upload.error_message = str(e)
                    await db.commit()
                    return

            entries_data = _merge_split_entries(entries_data)
            entries_data = _drop_untanked_sounding_fragments(entries_data)
            entries_data = _split_swallowed_weekly_inventory(entries_data)
            entries_data = _propagate_shared_officer(entries_data)
            entries_data = _reconcile_tank_capacity_readings(entries_data)
            entries_data = _reconcile_chronology(entries_data)
            entries_data = _reconcile_entry_date_vs_own_header(entries_data)
            entries_data = _reconcile_entry_date_vs_own_signature(entries_data)
            entries_data = _dedupe_cross_date_duplicates(entries_data)
            entries_data = _flag_self_referential_transfers(entries_data)
            entries_data = _flag_retained_exceeds_capacity(entries_data)
            entries_data = _flag_fused_continuation_entries(entries_data)

            # ── Layer 2: build fingerprint set of all existing entries for
            # this vessel so we can detect duplicates row-by-row.
            # Fingerprint = (entry_date, orb_code, item_number, tank_location, quantities_signature).
            # tank_location alone is too coarse: two different same-day same-code
            # transfers from the same source tank to DIFFERENT destinations (e.g.
            # residues split to Waste Oil Settling Tank No.1 on one line and No.2
            # on the next) share the same source tank_location, so without the
            # quantities signature the second one looks like a duplicate of the
            # first and gets silently dropped.
            def _qty_signature(qty_dicts: list[dict]) -> tuple:
                sig = []
                for q in qty_dicts:
                    qtype = q.get("qty_type") or q.get("type") or ""
                    qval = q.get("qty_value") if q.get("qty_value") is not None else q.get("value") if q.get("value") is not None else q.get("amount") if q.get("amount") is not None else q.get("quantity")
                    try:
                        qval = round(float(qval), 2) if qval is not None else None
                    except (TypeError, ValueError):
                        qval = None
                    to_tank = (q.get("to_tank") or "").upper().strip()
                    sig.append((qtype, qval, to_tank))
                return tuple(sorted(sig, key=lambda t: (t[0], t[1] is None, t[1] if t[1] is not None else 0.0, t[2])))

            # When an entry has neither a tank nor any quantities (Code I general
            # remarks, Code H "26.1 <port name>" header lines), tank_norm +
            # qty_signature alone are both empty for every such entry that shares
            # a date+code+item -- so two genuinely different entries collapse to
            # the identical fingerprint below and the second is dropped as a
            # "duplicate". Confirmed in production (AM KIRTI): this silently lost
            # a second real bunkering event's port-name line (two separate
            # bunkerings the same day both starting "26.1 ZHOUSHAN TIAOZHOUMEN
            # ANCHORAGE" with no tank/quantity on that line) and two unrelated
            # Code I remarks on other days ("FUNCTION TEST 15 PPM..." vs "ALARM OF
            # OILY WATER SEPARATOR UNIT..." on the same date). Falling back to a
            # normalised description snippet only in this empty-tank/empty-qty
            # case keeps the fingerprint exactly as before for every entry that
            # already had a tank or a quantity to disambiguate on.
            def _text_fallback(tank_norm: str, qty_sig: tuple, description: str | None, raw_text: str | None) -> str:
                if tank_norm or qty_sig:
                    return ""
                # raw_text (the verbatim full block, e.g. including the 26.2/26.3
                # lines that follow a bare "26.1 <port name>" header) is preferred
                # over operation_description here -- description is often reduced
                # to just the port/remark name, which is IDENTICAL across multiple
                # distinct entries that share an anchorage or a stock remark, while
                # raw_text still carries the rest of the block that makes them
                # different. Only fall back to description if raw_text is missing.
                text = (raw_text or description or "").upper().strip()
                return re.sub(r"\s+", " ", text)

            existing_result = await db.execute(
                sa_select(
                    OrbEntry.id,
                    OrbEntry.entry_date,
                    OrbEntry.orb_code,
                    OrbEntry.item_number,
                    OrbEntry.tank_location,
                    OrbEntry.operation_description,
                    OrbEntry.raw_text,
                ).where(OrbEntry.vessel_id == vessel_id)
            )
            existing_rows = existing_result.all()
            existing_qty_result = await db.execute(
                sa_select(OrbEntryQuantity.entry_id, OrbEntryQuantity.qty_type,
                          OrbEntryQuantity.qty_value, OrbEntryQuantity.to_tank)
                .where(OrbEntryQuantity.entry_id.in_([r.id for r in existing_rows]))
            ) if existing_rows else None
            existing_qtys_by_entry: dict = {}
            if existing_qty_result is not None:
                for eq in existing_qty_result.all():
                    existing_qtys_by_entry.setdefault(eq.entry_id, []).append(
                        {"qty_type": eq.qty_type, "qty_value": eq.qty_value, "to_tank": eq.to_tank}
                    )

            existing_fingerprints: set[tuple] = set()
            for r in existing_rows:
                r_tank_norm = (r.tank_location or "").upper().strip()
                r_qty_sig = _qty_signature(existing_qtys_by_entry.get(r.id, []))
                existing_fingerprints.add((
                    str(r.entry_date), r.orb_code or "", r.item_number or "",
                    r_tank_norm, r_qty_sig,
                    _text_fallback(r_tank_norm, r_qty_sig, r.operation_description, r.raw_text),
                ))
            # Also track fingerprints seen within this upload to catch intra-PDF duplicates
            seen_this_upload: set[tuple] = set()

            entry_count = 0
            duplicate_count = 0
            errors = []

            for entry_dict in entries_data:
                # ── 1. Parse date — skip orphan fragments that have no real date
                raw_date_str = (entry_dict.get("entry_date") or "").strip()
                try:
                    entry_date = parse_entry_date(raw_date_str)
                except Exception:
                    entry_date = None

                if entry_date is None or entry_date == date.today():
                    # Gemini couldn't find a real date — skip rather than invent today
                    logger.warning(f"Skipped entry with unparseable date: {raw_date_str!r}")
                    errors.append(f"Skipped: unparseable date '{raw_date_str}'")
                    continue

                # ── 2. Reject signature-only fragments
                # A signature block has no quantities and its raw_text looks like
                # "Rank; Name; Date" or "Name / Rank / Date" patterns
                raw_text = (entry_dict.get("raw_text") or "").strip()
                quantities_raw = entry_dict.get("quantities") or []
                if not quantities_raw and _is_signature_block(
                    raw_text, entry_dict.get("officer_1_name"), entry_dict.get("officer_2_name")
                ):
                    logger.info(f"Skipped signature block: {raw_text[:80]!r}")
                    continue

                # ── 3. Infer orb_code from item_number when Gemini returns null
                orb_code = entry_dict.get("orb_code") or None
                if not orb_code:
                    item = (entry_dict.get("item_number") or "").strip()
                    if item.startswith("26"):
                        orb_code = "H"
                    elif item in ("13", "14") or item.startswith("15"):
                        orb_code = "D"
                    elif item in ("16", "17", "18"):
                        orb_code = "E"
                    elif item in ("19", "20", "21"):
                        orb_code = "F"
                    elif item in ("22", "23", "24", "25"):
                        orb_code = "G"
                    elif item.startswith("11") or item.startswith("12"):
                        orb_code = "C"
                    else:
                        orb_code = "C"

                # ── 4. Normalise tank name for fingerprint (upper, stripped)
                tank_location = entry_dict.get("tank_location") or None
                tank_norm = (tank_location or "").upper().strip()
                qty_sig = _qty_signature(quantities_raw)

                fp = (
                    str(entry_date),
                    orb_code or "",
                    entry_dict.get("item_number", "") or "",
                    tank_norm,
                    qty_sig,
                    _text_fallback(
                        tank_norm, qty_sig,
                        entry_dict.get("operation_description"),
                        entry_dict.get("raw_text"),
                    ),
                )

                if fp in existing_fingerprints or fp in seen_this_upload:
                    duplicate_count += 1
                    logger.info(f"Skipped duplicate entry: date={fp[0]} code={fp[1]} item={fp[2]} tank={fp[3]}")
                    continue

                seen_this_upload.add(fp)

                try:
                  # Everything below runs inside its own SAVEPOINT, not the
                  # outer transaction directly. CONFIRMED SEVERE PRODUCTION
                  # BUG: this used to call db.rollback() in the except block
                  # below on a single entry's failure -- but db.rollback()
                  # on an AsyncSession rolls back the ENTIRE transaction, not
                  # just this entry's own pending changes. Since nothing in
                  # this loop commits per-entry (only db.flush(), with the
                  # real commit happening once at the very end), a SINGLE
                  # entry failing partway through this loop discarded EVERY
                  # entry successfully added so far in the same session --
                  # not just the failed one. Confirmed in production: 3
                  # entries genuinely failed to save on one upload, but the
                  # three db.rollback() calls that followed wiped out ~80
                  # entries from 18 EARLIER, already-successfully-processed
                  # pages, none of which had anything wrong with them. A
                  # SAVEPOINT (db.begin_nested()) scopes the rollback to only
                  # this one entry's own changes on failure, leaving
                  # everything else in the session untouched.
                  async with db.begin_nested():
                    entry = OrbEntry(
                        id=uuid.uuid4(),
                        upload_id=upload_id,
                        vessel_id=vessel_id,
                        entry_date=entry_date,
                        orb_code=orb_code,
                        item_number=entry_dict.get("item_number"),
                        operation_description=entry_dict.get("operation_description", ""),
                        tank_location=tank_location,
                        time_start=entry_dict.get("time_start"),
                        time_stop=entry_dict.get("time_stop"),
                        position_start=entry_dict.get("position_start"),
                        position_stop=entry_dict.get("position_stop"),
                        officer_1_name=entry_dict.get("officer_1_name"),
                        officer_1_rank=entry_dict.get("officer_1_rank"),
                        officer_2_name=entry_dict.get("officer_2_name"),
                        officer_2_rank=entry_dict.get("officer_2_rank"),
                        raw_text=raw_text,
                        confidence_score=entry_dict.get("confidence_score"),
                        page_number=entry_dict.get("page_number"),
                        has_gap_before=bool(entry_dict.get("has_gap_before", False)),
                        has_erasure=bool(entry_dict.get("has_erasure", False)),
                        master_signature_present=entry_dict.get("master_signature_present"),
                    )
                    db.add(entry)
                    await db.flush()

                    # ── 5. Post-process quantities
                    # A Code C 11.1 sounding block with exactly ONE quantity value
                    # sometimes has that value's qty_type mislabeled by Gemini even
                    # though raw_text plainly shows which line it came from --
                    # confirmed in production: a "11.2 25.6 m3" capacity reading
                    # (item 11.2 always means capacity, per the prompt's own
                    # mapping) came back tagged qty_type="retained". Since a
                    # single-quantity 11.1 entry's raw_text unambiguously shows
                    # whether the visible line was "11.2" (capacity) or "11.3"
                    # (retained), that's a more reliable signal than the model's
                    # own qty_type label for exactly this narrow case.
                    single_qty_type_override = None
                    if (
                        orb_code == "C"
                        and (entry_dict.get("item_number") or "").strip() == "11.1"
                        and len(quantities_raw) == 1
                    ):
                        has_112 = bool(re.search(r"(?<!\d)11\.2(?!\d)", raw_text))
                        has_113 = bool(re.search(r"(?<!\d)11\.3(?!\d)", raw_text))
                        if has_112 and not has_113:
                            single_qty_type_override = "capacity"
                        elif has_113 and not has_112:
                            single_qty_type_override = "retained"

                    # For a transfer/bunkering entry (12.2, Code D 15.3, 26.3/26.4) the
                    # ORB text can carry TWO "retained" figures -- one for the source
                    # tank, one for the destination tank after it receives the
                    # transfer. The model doesn't always stamp an explicit from_tank
                    # on that second (destination) retained figure, so if we blindly
                    # fall back to the entry's own tank_location (the source tank) for
                    # every unstamped retained quantity, the destination tank's retained
                    # reading gets silently misattributed to the source tank -- which
                    # then gets compared against the wrong tank's capacity downstream.
                    # Once a transferred/bunkered to_tank is known for this entry, any
                    # retained figure AFTER the first one defaults to that destination
                    # tank instead of tank_location when the model left from_tank blank.
                    transfer_to_tank = next(
                        (
                            qd.get("to_tank")
                            for qd in quantities_raw
                            if (qd.get("qty_type") or qd.get("type")) in ("transferred", "bunkered")
                            and qd.get("to_tank")
                        ),
                        None,
                    )
                    retained_seen_count = 0

                    seen_qty_keys: set[tuple] = set()
                    for qty_dict in quantities_raw:
                        qty_type = (
                            qty_dict.get("qty_type")
                            or qty_dict.get("type")
                            or "retained"
                        )
                        if single_qty_type_override and qty_type != single_qty_type_override:
                            logger.warning(
                                f"Correcting mislabeled qty_type for single-quantity 11.1 entry: "
                                f"{qty_type!r} -> {single_qty_type_override!r} (raw_text item line "
                                f"disagrees with model's own qty_type) date={entry_date} "
                                f"tank={tank_location!r}"
                            )
                            qty_type = single_qty_type_override
                        raw_val = (
                            qty_dict.get("qty_value")
                            if qty_dict.get("qty_value") is not None
                            else qty_dict.get("value")
                            if qty_dict.get("value") is not None
                            else qty_dict.get("amount")
                            if qty_dict.get("amount") is not None
                            else qty_dict.get("quantity")
                        )
                        if raw_val is None or raw_val == "":
                            continue
                        qty_value = _coerce_qty_value(raw_val)
                        if qty_value is None:
                            logger.warning(
                                f"Could not parse quantity value {raw_val!r} as a number -- "
                                f"skipping this quantity. date={entry_date} tank={tank_location!r}"
                            )
                            continue
                        qty_unit = qty_dict.get("qty_unit", "m3")

                        qty_key = (qty_type, qty_value)
                        if qty_key in seen_qty_keys:
                            logger.info(f"Removed duplicate quantity {qty_key} in entry {entry.id}")
                            continue
                        seen_qty_keys.add(qty_key)

                        explicit_from_tank = qty_dict.get("from_tank")
                        if qty_type == "retained":
                            retained_seen_count += 1
                            if explicit_from_tank:
                                from_tank = explicit_from_tank
                            elif retained_seen_count > 1 and transfer_to_tank:
                                from_tank = transfer_to_tank
                                logger.info(
                                    f"Retained quantity #{retained_seen_count} in entry had no "
                                    f"explicit from_tank -- attributing to transfer destination "
                                    f"tank {transfer_to_tank!r} instead of source tank_location "
                                    f"{tank_location!r}. date={entry_date}"
                                )
                            else:
                                from_tank = tank_location
                        else:
                            from_tank = explicit_from_tank or tank_location
                        to_tank = None if qty_type == "retained" else qty_dict.get("to_tank")

                        qty = OrbEntryQuantity(
                            id=uuid.uuid4(),
                            entry_id=entry.id,
                            qty_type=qty_type,
                            qty_value=qty_value,
                            qty_unit=qty_unit,
                            from_tank=from_tank,
                            to_tank=to_tank,
                        )
                        db.add(qty)

                    # A Code C 11.1 sounding is definitionally a capacity+retained
                    # pair for one tank -- if only one of the two survived (most
                    # often because the other one was the tail end of the block on
                    # the next page and got lost entirely, see the
                    # LEADING CONTINUATION prompt guidance), it silently looks like
                    # a complete, trustworthy reading otherwise. Cap confidence low
                    # so it's visibly flagged for manual review instead -- this
                    # can't recover the missing figure (it's not in the JSON to
                    # recover), only make its absence visible.
                    # Also covers the more severe variant of the same failure: a
                    # ZERO-quantity 11.1 entry (just the tank name survived, the
                    # whole 11.2/11.3 continuation was lost, not merely one of the
                    # two figures) -- confirmed in production 5 separate times in
                    # one document, always the same shape: the tank name is the
                    # LAST thing on a page, and the next page's top row (its true
                    # continuation) never gets reported anywhere in Gemini's
                    # response at all, not even a mislabeled fragment to recover.
                    # The original version of this check only handled "exactly one
                    # of the two present," so a fully-empty entry silently looked
                    # like a normal (if sparse) reading instead of the worst case
                    # of this exact bug.
                    qty_types_present = {k[0] for k in seen_qty_keys}
                    matched_types = {"capacity", "retained"} & qty_types_present
                    if (
                        orb_code == "C"
                        and (entry_dict.get("item_number") or "").strip() == "11.1"
                        and len(matched_types) < 2
                    ):
                        logger.warning(
                            f"Incomplete 11.1 sounding: only {matched_types or '{}'} "
                            f"present, missing the rest -- likely lost across a page break. Flagging "
                            f"low-confidence for manual review. date={entry_date} tank={tank_location!r}"
                        )
                        entry.confidence_score = (
                            min(entry.confidence_score, 0.3) if entry.confidence_score is not None else 0.3
                        )

                    await db.flush()
                    entry_count += 1
                except Exception as e:
                    # No db.rollback() here -- exiting the "async with
                    # db.begin_nested()" block above on an exception already
                    # rolled back to this entry's own SAVEPOINT automatically,
                    # leaving every other already-added entry in this session
                    # untouched. Calling db.rollback() here too would be the
                    # exact bug this savepoint exists to prevent.
                    logger.error(f"Failed to save entry: {e}")
                    errors.append(str(e)[:200])
                    continue

            upload.status = "completed"
            upload.extracted_entries_count = entry_count
            upload.duplicate_entries_skipped = duplicate_count

            msg_parts = []
            if errors:
                msg_parts.append(f"{len(errors)} entries failed to save")
            if duplicate_count:
                msg_parts.append(f"{duplicate_count} duplicate {'entry' if duplicate_count == 1 else 'entries'} skipped")
            upload.error_message = "; ".join(msg_parts) if msg_parts else None
            await db.commit()

            # Run compliance checks
            try:
                from app.services.calculations import run_all_checks
                await run_all_checks(vessel_id, upload_id, db)
            except Exception as e:
                logger.error(f"Calculations failed: {e}")

        except Exception as e:
            logger.error(f"Extraction failed for upload {upload_id}: {e}")
            try:
                result = await db.execute(sa_select(OrbUpload).where(OrbUpload.id == upload_id))
                upload = result.scalar_one_or_none()
                if upload:
                    upload.status = "failed"
                    upload.error_message = str(e)
                    await db.commit()
            except Exception:
                pass
