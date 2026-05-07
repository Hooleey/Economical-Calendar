import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATABASE_PATH = BACKEND_DIR / "events.db"

_RAW_DB_URL = (os.getenv("DATABASE_URL") or "").strip()


def _normalize_postgres_url(url: str) -> str:
    # Heroku/Render historically use postgres://; SQLAlchemy prefers explicit driver.
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql+psycopg2://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


if _RAW_DB_URL:
    DATABASE_URL = _normalize_postgres_url(_RAW_DB_URL)
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
else:
    DATABASE_URL = f"sqlite:///{DATABASE_PATH.as_posix()}"
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def ensure_sqlite_columns() -> None:
    """Add columns/index for existing SQLite DBs (create_all does not migrate)."""
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info('events')")).fetchall()
        colnames = {r[1] for r in rows}
        if not colnames:
            return
        if "event_time" not in colnames:
            conn.execute(text("ALTER TABLE events ADD COLUMN event_time VARCHAR(16)"))
        if "source" not in colnames:
            conn.execute(text("ALTER TABLE events ADD COLUMN source VARCHAR(32) NOT NULL DEFAULT 'manual'"))
        if "external_id" not in colnames:
            conn.execute(text("ALTER TABLE events ADD COLUMN external_id VARCHAR(160)"))
        if "remaining_time" not in colnames:
            conn.execute(text("ALTER TABLE events ADD COLUMN remaining_time VARCHAR(32)"))
        if "currency" not in colnames:
            conn.execute(text("ALTER TABLE events ADD COLUMN currency VARCHAR(16)"))
        if "actual" not in colnames:
            conn.execute(text("ALTER TABLE events ADD COLUMN actual VARCHAR(64)"))
        if "forecast" not in colnames:
            conn.execute(text("ALTER TABLE events ADD COLUMN forecast VARCHAR(64)"))
        if "previous" not in colnames:
            conn.execute(text("ALTER TABLE events ADD COLUMN previous VARCHAR(64)"))
        if "description" not in colnames:
            conn.execute(text("ALTER TABLE events ADD COLUMN description TEXT"))
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_events_external_id "
                "ON events (external_id) WHERE external_id IS NOT NULL"
            )
        )
