# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ORB Digitization Platform: digitizes scanned/handwritten MARPOL Oil Record Book (Part I) PDFs into structured entries, runs automated compliance checks (alerts), and produces Excel/PDF reports plus a "daily log" view. Backend is FastAPI + async SQLAlchemy + PostgreSQL; frontend is React 18 + Vite.

Repo root is `Environment_Performance/` (the README refers to it as `orb-platform/`).

## Commands

Backend (run from `backend/`; Windows venv at `backend/venv`, needs Python 3.11+, PostgreSQL, and poppler for `pdf2image`):

```bash
pip install -r requirements.txt
cp .env.example .env            # then set DATABASE_URL, SECRET_KEY, etc.
alembic upgrade head            # migrations
python seed.py                  # admin user (admin@orbplatform.com) + sample vessel/tanks
uvicorn app.main:app --reload --port 8000   # API docs at /docs
venv/Scripts/python.exe tests/test_extraction_pipeline.py   # tests
```

- Tests are a plain script (no pytest): each `test_*` function is called from `main()` in `tests/test_extraction_pipeline.py`. To run one case, call that function from a Python shell or temporarily edit `main()`.
- Fuel scrapers (Playwright, sync): `python -m scrapers.wni_fuel_scraper` and `python -m scrapers.mariapps_fuel_scraper` from `backend/`; `scripts/run_fuel_scrapers.sh` runs both under cron on the VM (hardcoded `/opt/orb-platform/backend`).
- Alembic: new migration = `alembic revision -m "..."`; numbered `00N_*.py` files are the convention, though a couple of hash-named/odd-named files also live in `alembic/versions/`.

Frontend (run from `frontend/`): `npm install`, `npm run dev` (Vite on :3000, proxies `/api` to :8000), `npm run build`. No lint or test setup.

## Architecture

**Request flow.** `app/main.py` mounts routers from `app/api/` under `/api` (auth, users, vessels, vessel_tanks, orb_uploads, orb_entries, orb_alerts). Responses are wrapped by `success()` in `app/schemas/common.py`. Auth is JWT via `app/dependencies.py`. Frontend axios (`src/api/axios.js`) attaches the bearer token from localStorage and redirects to `/login` on 401.

**Upload → extraction → checks pipeline** (the core of the system):
1. `POST /api/uploads` (`api/orb_uploads.py`) validates the PDF, rejects duplicates by SHA-256 file hash (layer 1), saves it under `UPLOAD_DIR/<vessel_id>/`, optionally mirrors it to Azure Blob, creates an `OrbUpload` with `status=pending`, and schedules `run_extraction` as a FastAPI background task.
2. `services/extraction.py` (~4k lines) `run_extraction`: renders pages with pdf2image, sends them to **Gemini** (`google-genai`) for vision extraction (the README says Claude/`claude-sonnet-4-6`; the live path is Gemini, and the Anthropic call in the file is commented out). Pre-steps include splitting two-up spreads / stacked pages, vessel-name mismatch detection (`VesselMismatchError` fails the upload), boundary/orphan-entry rechecks, and officer/capacity "roster" hints carried across pages. Progress is written to the upload row.
3. Then a long chain of deterministic post-processing repairs on the raw entries (merge split entries, reconcile chronology/dates against headers and signatures, dedupe, propagate officers, flag self-referential transfers, etc.). Each is a separate `_reconcile_*`/`_flag_*`/`_dedupe_*` function; `tests/test_extraction_pipeline.py` holds regression tests for confirmed real-scan bugs, so extend it when changing these.
4. Row-level duplicate detection (layer 2) by fingerprint (date, code, item, tank, quantities signature), then entries/quantities/alerts are persisted and `services/calculations.py: run_all_checks` runs.

`USE_MOCK_EXTRACTION=true` (the default) skips Gemini and uses `get_mock_data`, so any PDF yields canned entries.

**Compliance checks** (`services/calculations.py`): 13 async checks invoked from `run_all_checks` (the docstring says 12; README lists 9, both stale). Alerts are created via `create_alert_if_new` to avoid duplicates. Tank-name matching is fuzzy (`_norm_tank`, protected words derived from the vessel's tanks) and is shared conceptually with `services/daily_log.py` (`match_tank`, `classify`), which builds the per-day log from entries plus `FuelConsumption`.

**Fuel consumption data.** `scrapers/` (WNI Logbook+ and MariApps portals, via Playwright) upsert into `fuel_consumption` (unique per vessel_name + report_date) using a separate **sync** engine (`scrapers/sync_database.py`, psycopg2), independent of the app's async asyncpg engine. Check 7 (`sludge_vs_fuel_consumption`) reads this table. Vessel names come from `vessels.txt`.

**Reports.** `services/excel_report.py` (openpyxl) and `services/pdf_report.py` (ReportLab), served from the uploads router.

**Storage.** Original PDFs local (`UPLOAD_DIR`) plus best-effort Azure Blob (`AZURE_STORAGE_*`); IOPP tank certificate documents also go to Azure (`services/azure_storage.py`).

**Frontend.** `src/App.jsx` defines routes (dashboard, vessels, uploads, upload detail, entries, alerts, daily-log, admin/users, admin/vessels). State lives in three contexts (`Auth`, `Sidebar`, `Toast`); pure CSS in `src/styles`. Mixed `.js`/`.jsx` files are allowed because `vite.config.js` forces the JSX loader for `.js`. Vite uses `import.meta.env.VITE_API_URL` (not the README's `REACT_APP_API_URL`).

## Config notes

- Settings live in `app/config.py` (pydantic-settings, reads `backend/.env`, which is gitignored). Beyond the README's variables: `GEMINI_API_KEY`, `POPPLER_PATH` (set on Windows), `CORS_ORIGINS`, `DISABLE_SSL_VERIFY` (local-only, must stay false in production), `EXTRACTION_DEBUG_DIR` (dumps per-page images/JSON/split manifest for diagnosing extraction), `AZURE_STORAGE_*`, and `WNI_*` scraper credentials.
- `.claude/launch.json` defines an `orb-backend` dev server using `backend/venv/Scripts/uvicorn.exe`.
