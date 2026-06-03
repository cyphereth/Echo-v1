import os
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker, Session
from .models import Base

_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///echo_radar.db")
_connect_args = {"check_same_thread": False} if _DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(_DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

# Columns added after the initial schema shipped. create_all() never ALTERs an
# existing table, so we add missing columns by hand. Idempotent and safe to run
# on every startup — only columns that don't yet exist get added.
_MIGRATIONS: dict[str, dict[str, str]] = {
    "brands": {
        "niche_keywords": "TEXT DEFAULT '[]'",
        "auto_collect":   "BOOLEAN DEFAULT 0",
        "user_id":        "INTEGER",
    },
    "probes": {
        "source": "TEXT DEFAULT 'brand'",
        "label":  "TEXT",
    },
    "mentions": {
        "source":      "TEXT DEFAULT 'brand'",
        "competitor":  "TEXT",
        "opportunity": "TEXT",
    },
}


def _migrate() -> None:
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, cols in _MIGRATIONS.items():
            if table not in tables:
                continue  # create_all() already built it with every column
            have = {c["name"] for c in insp.get_columns(table)}
            for col, ddl in cols.items():
                if col not in have:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


def init_db() -> None:
    Base.metadata.create_all(engine)
    _migrate()


def get_session() -> Session:
    return SessionLocal()
