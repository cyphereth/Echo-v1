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
    "intel_mentions": {
        "hidden": "BOOLEAN NOT NULL DEFAULT 0",
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


def _fix_intel_probes_nullable() -> None:
    """Guard: if intel_probes exists with direction_id NOT NULL (old schema from
    before Task 1 made it nullable), rebuild the table so Task 4 intake can insert
    probes without a direction_id.  SQLite cannot ALTER a NOT NULL constraint away,
    so we recreate the table preserving all rows.  Idempotent: does nothing on a
    fresh DB or one that already has the nullable column."""
    if not _DATABASE_URL.startswith("sqlite"):
        return  # PostgreSQL can ALTER; this guard is SQLite-only
    insp = inspect(engine)
    if "intel_probes" not in set(insp.get_table_names()):
        return  # table doesn't exist yet; create_all() will build it correctly
    cols = {c["name"]: c for c in insp.get_columns("intel_probes")}
    if "direction_id" not in cols:
        return  # unexpected schema; leave it alone
    if not cols["direction_id"].get("nullable", True):
        # direction_id is NOT NULL — rebuild to nullable.
        # Use only the columns that exist in the OLD table so the INSERT
        # works regardless of how many columns the old schema had.
        # Special-case next_run_at: old rows may store NULL (TEXT), substitute now().
        old_col_names = list(cols.keys())
        select_exprs = [
            "COALESCE(next_run_at, datetime('now'))" if c == "next_run_at" else c
            for c in old_col_names
        ]
        col_list    = ", ".join(old_col_names)
        select_list = ", ".join(select_exprs)
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE intel_probes_old AS SELECT * FROM intel_probes"
            )
            conn.exec_driver_sql("DROP TABLE intel_probes")
            # Recreate with the correct (nullable) schema from the ORM definition.
            import radar.intel.models  # noqa: F401 — ensures table in metadata
            from ..models import Base as _Base
            _Base.metadata.tables["intel_probes"].create(conn)
            conn.exec_driver_sql(
                f"INSERT INTO intel_probes ({col_list}) "
                f"SELECT {select_list} FROM intel_probes_old"
            )
            conn.exec_driver_sql("DROP TABLE intel_probes_old")


def init_db() -> None:
    import radar.news.models, radar.brand.models, radar.intel.models  # noqa: F401  register new tables
    Base.metadata.create_all(engine)
    from .migrate_split import migrate_split
    migrate_split(engine)
    _migrate()
    _fix_intel_probes_nullable()
    from .vec import create_vec_tables
    with engine.begin() as conn:
        create_vec_tables(conn)


def get_session() -> Session:
    return SessionLocal()
