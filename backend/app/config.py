from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/orb_platform"
    SECRET_KEY: str = "change-this-secret-key-to-something-secure-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    ANTHROPIC_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    USE_MOCK_EXTRACTION: bool = True
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE_MB: int = 50
    # Folder containing poppler binaries (pdftoppm). Leave empty on Linux/VM so
    # pdf2image finds them on the system PATH (/usr/bin via poppler-utils).
    # On local Windows, set to e.g. C:\poppler\poppler-26.02.0\Library\bin
    POPPLER_PATH: str = ""
    # Comma-separated list of origins allowed to call the API (CORS).
    # Default covers local dev (Vite ports) and the production VM domain.
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173,https://envper.ozellar.com"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    # Opt-in TLS verification bypass for local networks behind an SSL-inspecting
    # proxy that breaks certificate validation. MUST stay False on the VM/prod.
    DISABLE_SSL_VERIFY: bool = False

    # Azure Blob Storage — stores IOPP tank certificate/survey documents.
    AZURE_STORAGE_CONNECTION_STRING: str = ""
    AZURE_STORAGE_CONTAINER: str = "iopp-documents"

    # ── WNI Fuel Scraper (Check 7 support) ─────────────────────────────────
    # Separate, standalone scraper — see app/scrapers/wni_fuel_scraper.py.
    # Reuses the same WNI portal credentials as the existing historical
    # scraper; set these in .env (same values you already use there).
    WNI_LOGIN_URL: str = ""
    WNI_USERNAME: str = ""
    WNI_PASSWORD: str = ""
    # Path to the newline-delimited vessel name list used by the fuel
    # scraper. Defaults to a file named vessels.txt in the backend root.
    WNI_VESSELS_FILE: str = "vessels.txt"

    # ── Extraction debug dump ───────────────────────────────────────────────
    # When set, each ORB extraction run writes one subfolder per upload here
    # containing: every image actually sent to Gemini (post-split, exactly as
    # seen by the model), the raw JSON response for each page, and a
    # manifest.json recording each page's stacked-pair split decision
    # (page_count / split_y_fraction) and its final page_number. Without this,
    # diagnosing a specific page's failure means guessing where the real
    # split boundary landed -- this makes it exact instead. Empty (default)
    # disables the dump entirely; this is diagnostic-only and never read by
    # the extraction logic itself.
    EXTRACTION_DEBUG_DIR: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()