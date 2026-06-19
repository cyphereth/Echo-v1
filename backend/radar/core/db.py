import os
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker, Session
from ..models import Base

_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///echo_radar.db")
_connect_args = {"check_same_thread": False} if _DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(
    _DATABASE_URL,
    connect_args=_connect_args,
    # WAL mode: readers don't block writers and writers don't block readers.
    # Prevents "database is locked" when background collect runs concurrently.
    pool_pre_ping=True,
)


def _enable_wal(connection, _record):
    if _DATABASE_URL.startswith("sqlite"):
        connection.execute("PRAGMA journal_mode=WAL")
        # 30s: collect (wizard-triggered) and the scheduler can both write at
        # once; SQLite allows one writer, so the other waits instead of erroring.
        connection.execute("PRAGMA busy_timeout=30000")


from sqlalchemy import event
event.listen(engine, "connect", _enable_wal)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

# Columns added after the initial schema shipped. create_all() never ALTERs an
# existing table, so we add missing columns by hand. Idempotent and safe to run
# on every startup — only columns that don't yet exist get added.
_MIGRATIONS: dict[str, dict[str, str]] = {
    "brands": {
        "niche_keywords": "TEXT DEFAULT '[]'",
        "auto_collect":   "BOOLEAN DEFAULT 0",
        "user_id":        "INTEGER",
        "market":         "TEXT DEFAULT 'global'",
        "sphere":         "TEXT DEFAULT ''",
        "geo":            "TEXT DEFAULT ''",
        "category_terms": "TEXT DEFAULT '[]'",
        "audience_terms": "TEXT DEFAULT '[]'",
        "tg_channels":    "TEXT DEFAULT '[]'",
        "followers":      "INTEGER DEFAULT 0",
        "local_mode":     "BOOLEAN DEFAULT 0",
    },
    "probes": {
        "source":    "TEXT DEFAULT 'brand'",
        "label":     "TEXT",
        "topic_id":  "INTEGER",
    },
    "mentions": {
        "source":      "TEXT DEFAULT 'brand'",
        "competitor":  "TEXT",
        "opportunity": "TEXT",
        "is_spam":     "BOOLEAN DEFAULT 0",
        "incident_id": "INTEGER",
        "topic_id":    "INTEGER",
    },
    "incidents": {
        "topic_id": "INTEGER",
    },
    "stories": {
        "topic_id":         "INTEGER",
        "source_count":     "INTEGER DEFAULT 0",
        "verified":         "BOOLEAN DEFAULT 0",
        "credibility":      "TEXT DEFAULT 'unrated'",
        "credibility_note": "TEXT DEFAULT ''",
        "summary":          "TEXT DEFAULT ''",
    },
    "reports": {
        "topic_id": "INTEGER",
    },
    "comments": {
        "is_opportunity": "BOOLEAN DEFAULT 0",
        "opportunity":    "TEXT",
        "is_spam":        "BOOLEAN DEFAULT 0",
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


# brand_id shipped NOT NULL, but news-mode rows are topic-scoped (exactly one of
# brand_id/topic_id is set). SQLite can't ALTER a column to drop NOT NULL, so we
# rewrite the table's stored DDL via writable_schema. Idempotent: tables whose
# brand_id is already nullable are skipped.
_NULLABLE_BRAND_ID = ("mentions", "incidents", "stories", "reports", "probes")


def _relax_brand_id_not_null() -> None:
    if not _DATABASE_URL.startswith("sqlite"):
        return
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        placeholders = ",".join("?" * len(_NULLABLE_BRAND_ID))
        rows = cur.execute(
            f"SELECT name, sql FROM sqlite_master WHERE type='table' "
            f"AND name IN ({placeholders})", _NULLABLE_BRAND_ID,
        ).fetchall()
        targets = [(n, s) for (n, s) in rows if "brand_id INTEGER NOT NULL" in s]
        if not targets:
            return
        cur.execute("PRAGMA writable_schema = ON")
        for name, ddl in targets:
            cur.execute(
                "UPDATE sqlite_master SET sql = ? WHERE type='table' AND name = ?",
                (ddl.replace("brand_id INTEGER NOT NULL", "brand_id INTEGER"), name),
            )
        # Bump schema_version so every other connection reparses on next use.
        ver = cur.execute("PRAGMA schema_version").fetchone()[0]
        cur.execute(f"PRAGMA schema_version = {ver + 1}")
        cur.execute("PRAGMA writable_schema = OFF")
        raw.commit()
    finally:
        raw.close()


def init_db() -> None:
    Base.metadata.create_all(engine)
    _migrate()
    _relax_brand_id_not_null()
    from .vec import create_vec_tables
    with engine.begin() as conn:
        create_vec_tables(conn)


def get_session() -> Session:
    return SessionLocal()
