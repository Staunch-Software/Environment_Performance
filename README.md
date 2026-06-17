# ORB Digitization Platform

A full-stack MARPOL Oil Record Book (ORB) Part I digitization and compliance platform.
Extracts handwritten ORB entries via Claude AI, runs 9 automated compliance checks,
and generates Excel/PDF reports.

---

## Prerequisites

| Tool | Minimum Version |
|------|----------------|
| Python | 3.11+ |
| Node.js | 18+ |
| PostgreSQL | 15+ |
| poppler-utils | any (for pdf2image) |

### Install poppler

**Windows:** Download from https://github.com/oschwartz10612/poppler-windows/releases  
Unzip and add the `bin/` folder to your PATH.

**Ubuntu/Debian:**
```bash
sudo apt-get install poppler-utils
```

**macOS:**
```bash
brew install poppler
```

---

## Backend Setup

```bash
cd orb-platform/backend

# 1. Create and activate virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
copy .env.example .env
# Edit .env and set your DATABASE_URL and SECRET_KEY at minimum

# 4. Create the PostgreSQL database
# Connect to PostgreSQL and run:
#   CREATE DATABASE orb_platform;

# 5. Run database migrations
alembic upgrade head

# 6. Seed initial data (admin user + AM UMANG vessel + 6 tanks)
python seed.py
```

### Environment Variables (`.env`)

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL async URL | — |
| `SECRET_KEY` | JWT signing secret (32+ chars) | — |
| `ALGORITHM` | JWT algorithm | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime | `1440` (24h) |
| `ANTHROPIC_API_KEY` | Claude API key | — |
| `USE_MOCK_EXTRACTION` | Skip Claude API, use mock data | `true` |
| `UPLOAD_DIR` | Directory for uploaded PDFs | `uploads` |
| `MAX_UPLOAD_SIZE_MB` | Max upload size | `50` |

---

## Running the Backend

```bash
cd orb-platform/backend
uvicorn app.main:app --reload --port 8000
```

API docs available at: http://localhost:8000/docs

---

## Frontend Setup

```bash
cd orb-platform/frontend

# 1. Install dependencies
npm install

# 2. (Optional) Create .env for custom API URL
echo REACT_APP_API_URL=http://localhost:8000 > .env
```

## Running the Frontend

```bash
cd orb-platform/frontend
npm start
```

App available at: http://localhost:3000

---

## Default Login Credentials

| Field | Value |
|-------|-------|
| Email | `admin@orbplatform.com` |
| Password | `Admin@123` |

---

## Testing with Mock Extraction

With `USE_MOCK_EXTRACTION=true` (the default), uploading **any PDF file** will trigger
the mock extraction pipeline, which generates 10 predefined entries covering multiple
ORB codes and producing the following alert types:

- `wrong_item_code` — Item 12.4 used for evaporation (should be 12.5)
- `missing_bdn` — Bunkering entry with no BDN reference
- `low_confidence_extraction` — Entry with 60% confidence score
- `overdue_sounding` — Gap detection across sounding entries

**Steps to test:**
1. Log in as admin
2. Go to **ORB Uploads** → click **Upload ORB PDF**
3. Select any vessel and any PDF file
4. The upload will transition: `pending → processing → completed`
5. Refresh after ~2 seconds to see entries and alerts
6. Go to **Alerts** to see generated compliance alerts
7. Use **Download Excel** / **Download PDF** on the upload detail page

---

## Switching to Real Claude API Extraction

1. Obtain an Anthropic API key from https://console.anthropic.com
2. Edit `.env`:
   ```
   USE_MOCK_EXTRACTION=false
   ANTHROPIC_API_KEY=sk-ant-...your-key...
   ```
3. Ensure poppler is installed (required for `pdf2image`)
4. Restart the backend server
5. Upload a real ORB PDF scan — each page is sent to `claude-sonnet-4-6` for extraction

The extraction model used is `claude-sonnet-4-6`. Extraction runs as a background task
so the upload endpoint returns immediately with `status=pending`.

---

## Project Structure

```
orb-platform/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app, CORS, router registration
│   │   ├── config.py        # Settings via pydantic-settings
│   │   ├── database.py      # Async SQLAlchemy engine + session
│   │   ├── dependencies.py  # JWT auth dependencies
│   │   ├── models/          # 7 SQLAlchemy ORM models
│   │   ├── schemas/         # Pydantic v2 request/response schemas
│   │   ├── api/             # 6 FastAPI routers
│   │   └── services/
│   │       ├── extraction.py    # Claude API + mock extraction
│   │       ├── calculations.py  # 9 compliance checks
│   │       ├── excel_report.py  # 5-sheet Excel report
│   │       └── pdf_report.py    # PDF report via ReportLab
│   ├── alembic/             # Database migrations
│   ├── seed.py              # Initial data seeder
│   └── requirements.txt
└── frontend/
    └── src/
        ├── api/axios.js         # Axios with auth interceptors
        ├── context/AuthContext  # JWT auth state
        ├── components/          # Shared UI components
        └── pages/               # 10 page components + admin panel
```

---

## Compliance Checks

| Check | Type | Trigger |
|-------|------|---------|
| Running balance | `mass_balance_error` | Δ > 0.15 m³ between computed and logged |
| Individual tank capacity | `tank_capacity_threshold` | Tank > 85% full |
| Combined tank capacity | `combined_capacity_threshold` | All tanks > 85% combined |
| Overdue sounding | `overdue_sounding` | > 8 day gap between soundings |
| Wrong item code | `wrong_item_code` | Items 12.4/11.4/Code I misuse |
| Overdue discharge | `overdue_discharge` | > 14 days between bilge discharges |
| Missing BDN | `missing_bdn` | Bunkering entry lacks 6+ char reference |
| Sludge generation | `sludge_generation_rate` | > 2% or < 0.5% of fuel bunkered |
| Low confidence | `low_confidence_extraction` | AI confidence < 75% |

---

## Tech Stack

- **Backend:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, asyncpg, Alembic, Pydantic v2
- **AI:** Anthropic Claude API (claude-sonnet-4-6) with vision for handwriting extraction
- **Reports:** openpyxl (Excel), ReportLab (PDF)
- **Frontend:** React 18, React Router v6, Axios, Pure CSS
- **Database:** PostgreSQL 15
