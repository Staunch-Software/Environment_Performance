"""ORB PDF extraction service — mock and Claude API modes."""
import re
import uuid
import json
import base64
import logging
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import select

from sqlalchemy import select as sa_select

from app.config import get_settings
from app.models.orb_upload import OrbUpload
from app.models.orb_entry import OrbEntry
from app.models.orb_entry_quantity import OrbEntryQuantity

logger = logging.getLogger(__name__)
settings = get_settings()

import ssl
import certifi
ssl._create_default_https_context = ssl._create_unverified_context

EXTRACTION_SYSTEM_PROMPT = """
You are an expert maritime document parser specializing in MARPOL Oil Record Books (ORB) Part I.
Carefully read the ENTIRE page image before writing any output.
Return ONLY a valid JSON object — no explanation, no markdown, no extra text.

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

═══════════════════════════════════════════════════════════════
JSON STRUCTURE — return exactly this:
{
  "page_number": <int>,
  "entries": [
    {
      "entry_date": "DD-MMM-YYYY",
      "orb_code": "<C|D|E|F|G|H|I>",
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
      "quantities": [ ... ],
      "raw_text": "<complete verbatim text of the entire block including all item lines>",
      "confidence_score": <0.0-1.0>
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

Quantity mapping by item/operation type:
  11.1 (sounding start) → capacity + retained for that tank
  11.2 → capacity quantity only
  11.3 → retained quantity only
  11.4 → collected quantity (from_tank = source, to_tank = sludge tank)
  12.1 → disposed (from sludge tank to shore) + retained (remaining in tank)
  12.2 → transferred (from tank A to tank B) + retained (what stays in source tank)
         + optionally retained (new level in destination tank)
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
  26.3 → bunkered fuel oil quantity; to_tank = fuel tank receiving it
  26.4 → bunkered lube oil quantity; to_tank = lube oil tank receiving it
  Code I → no quantities unless explicitly stated; item_number = null

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
            ],
            "raw_text": "12.2 Transfer BHT to BSOT: 3.20 m3, retained 5.30 m3",
            "confidence_score": 0.90,
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
            ],
            "raw_text": "26.3 Bunkering HFO 350 MT",
            "confidence_score": 0.91,
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
        },
    ]


def parse_entry_date(date_str: str) -> date:
    from datetime import datetime
    for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%B-%Y", "%d-%m-%Y"):
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

async def extract_with_gemini(storage_path: str) -> list[dict]:
    from google import genai
    from google.genai import types
    from pdf2image import convert_from_path
    import io
    import httpx
    
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

    try:
        pages = convert_from_path(
            storage_path,
            dpi=200,
            poppler_path=r"C:\poppler\poppler-26.02.0\Library\bin"
        )
    except Exception as e:
        logger.error(f"Failed to convert PDF to images: {e}")
        return []

    all_entries = []
    for page_num, page_image in enumerate(pages, 1):
        try:
            buf = io.BytesIO()
            page_image.save(buf, format="PNG")
            buf.seek(0)

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Part.from_bytes(
                        data=buf.getvalue(),
                        mime_type="image/png",
                    ),
                    f"{EXTRACTION_SYSTEM_PROMPT}\n\nExtract all ORB entries from page {page_num}.",
                ],
                config=types.GenerateContentConfig(
                    max_output_tokens=8192,
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )

            raw_json = response.text.strip()

            # Clean markdown if present
            if "```" in raw_json:
                parts = raw_json.split("```")
                for part in parts:
                    part = part.strip()
                    if part.startswith("json"):
                        part = part[4:].strip()
                    if part.startswith("{"):
                        raw_json = part
                        break

            # Extract JSON boundaries as fallback
            start = raw_json.find("{")
            end = raw_json.rfind("}") + 1
            if start != -1 and end > start:
                raw_json = raw_json[start:end]

            # Log raw for debugging
            logger.info(f"Page {page_num} raw JSON length: {len(raw_json)}")

            try:
                page_data = json.loads(raw_json)
            except json.JSONDecodeError:
                try:
                    from json_repair import repair_json
                    page_data = json.loads(repair_json(raw_json))
                except Exception:
                    logger.error(f"Page {page_num} JSON repair also failed, skipping")
                    continue
                
            all_entries.extend(page_data.get("entries", []))
            logger.info(f"Page {page_num} extracted {len(page_data.get('entries', []))} entries")

        except Exception as e:
            logger.error(f"Page {page_num} extraction failed: {e}")
            continue

    return all_entries

_SIGNATURE_PATTERNS = [
    # "3E; M.SATHIK; 28-DEC-2025"  or  "CE / A.SOLANKI / 04-JAN-2026"
    r"^\s*(CE|3E|2E|1E|4E|ETO|CO|2O|3O|C/E|C/O)\s*[;/,]\s*\S",
    # Standalone line like "Signed by Chief Engineer"
    r"(?i)sign(ed|ature)",
    # Only a name + date with no numeric content at all
    r"^[A-Z][a-z]+\s+[A-Z][a-z]+\s*[;/,]\s*\d{2}[\-/][A-Z]{3}[\-/]\d{4}\s*$",
]
_SIGNATURE_RE = re.compile("|".join(_SIGNATURE_PATTERNS))


def _is_signature_block(raw_text: str) -> bool:
    """Return True when raw_text appears to be only an officer signature, not an ORB entry."""
    if not raw_text:
        return False
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
    if len(lines) > 3:
        return False  # real entries have more content
    return bool(_SIGNATURE_RE.search(raw_text))


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

            if settings.USE_MOCK_EXTRACTION:
                entries_data = get_mock_data(vessel_id, upload_id)
            else:
                entries_data = await extract_with_gemini(storage_path)

            # ── Layer 2: build fingerprint set of all existing entries for
            # this vessel so we can detect duplicates row-by-row.
            # Fingerprint = (vessel_id, entry_date, orb_code, item_number, tank_location)
            existing_result = await db.execute(
                sa_select(
                    OrbEntry.entry_date,
                    OrbEntry.orb_code,
                    OrbEntry.item_number,
                    OrbEntry.tank_location,
                ).where(OrbEntry.vessel_id == vessel_id)
            )
            existing_fingerprints: set[tuple] = {
                (str(r.entry_date), r.orb_code or "", r.item_number or "", (r.tank_location or "").upper().strip())
                for r in existing_result.all()
            }
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
                if not quantities_raw and _is_signature_block(raw_text):
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

                fp = (
                    str(entry_date),
                    orb_code or "",
                    entry_dict.get("item_number", "") or "",
                    tank_norm,
                )

                if fp in existing_fingerprints or fp in seen_this_upload:
                    duplicate_count += 1
                    logger.info(f"Skipped duplicate entry: date={fp[0]} code={fp[1]} item={fp[2]} tank={fp[3]}")
                    continue

                seen_this_upload.add(fp)

                try:
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
                        )
                        db.add(entry)
                        await db.flush()

                        # ── 5. Post-process quantities
                        seen_qty_keys: set[tuple] = set()
                        for qty_dict in quantities_raw:
                            qty_type = qty_dict.get("qty_type", "retained")
                            qty_value = float(qty_dict.get("qty_value") or 0)
                            qty_unit = qty_dict.get("qty_unit", "m3")

                            # Dedup: skip if same (type, value) already added for this entry
                            qty_key = (qty_type, qty_value)
                            if qty_key in seen_qty_keys:
                                logger.info(f"Removed duplicate quantity {qty_key} in entry {entry.id}")
                                continue
                            seen_qty_keys.add(qty_key)

                            # Backfill from_tank from entry tank_location when Gemini left it null
                            from_tank = qty_dict.get("from_tank") or tank_location

                            # retained quantities must never have a to_tank
                            if qty_type == "retained":
                                to_tank = None
                            else:
                                to_tank = qty_dict.get("to_tank")

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

                    entry_count += 1
                except Exception as e:
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
