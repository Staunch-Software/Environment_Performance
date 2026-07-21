"""Synchronous database connection dedicated to the WNI fuel scraper.

The main ORB application (app/database.py) uses an ASYNC engine
(postgresql+asyncpg://...) because FastAPI request handlers are async.
The fuel scraper is a standalone script driven by synchronous Playwright
(sync_api), so it needs a plain blocking SQLAlchemy Session instead —
handing it an async session/engine would raise "no running event loop"
errors or silently deadlock.

This module builds its OWN sync engine from the same DATABASE_URL setting,
with the driver swapped from asyncpg to psycopg2. It does not import or
modify app/database.py in any way, so the existing async app is unaffected.
"""
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


def _to_sync_url(database_url: str) -> str:
    """Convert an asyncpg URL to a psycopg2 URL.

    'postgresql+asyncpg://user:pass@host/db' -> 'postgresql+psycopg2://user:pass@host/db'
    Leaves already-sync URLs (e.g. plain 'postgresql://...') untouched.
    """
    if "+asyncpg" in database_url:
        return database_url.replace("+asyncpg", "+psycopg2")
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return database_url


SYNC_DATABASE_URL = _to_sync_url(settings.DATABASE_URL)

sync_engine = create_engine(
    SYNC_DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    autoflush=False,
    autocommit=False,
)


def get_sync_session() -> Session:
    """Returns a new sync Session. Caller is responsible for closing it
    (use as a context manager or in a try/finally — see wni_fuel_scraper.py)."""
    return SyncSessionLocal()