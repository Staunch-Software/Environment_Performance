from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
