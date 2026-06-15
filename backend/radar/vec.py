from __future__ import annotations
import numpy as np
import sqlite_vec

from .embeddings import EMBED_DIM

# vec0 virtual tables. Cosine distance so distance = 1 - cosine_similarity.
_TABLES = ("mention_vec", "incident_vec", "story_vec")


def create_vec_tables(conn) -> None:
    """Create vec0 tables. `conn` is a SQLAlchemy Connection or raw DBAPI conn."""
    exec_ = conn.exec_driver_sql if hasattr(conn, "exec_driver_sql") else conn.execute
    for t in _TABLES:
        exec_(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {t} USING vec0("
            f"id INTEGER PRIMARY KEY, "
            f"embedding float[{EMBED_DIM}] distance_metric=cosine)"
        )


def _ser(v: np.ndarray) -> bytes:
    return sqlite_vec.serialize_float32(np.asarray(v, dtype=np.float32).tolist())


def store(conn, table: str, row_id: int, v: np.ndarray) -> None:
    """Insert-or-replace one vector. `conn` is a raw DBAPI connection."""
    conn.execute(
        f"INSERT OR REPLACE INTO {table}(id, embedding) VALUES (?, ?)",
        (row_id, _ser(v)),
    )


def knn(conn, table: str, q: np.ndarray, k: int = 5) -> list[tuple[int, float]]:
    """Return [(id, cosine_distance), ...] nearest to q, closest first."""
    rows = conn.execute(
        f"SELECT id, distance FROM {table} "
        f"WHERE embedding MATCH ? AND k = ? ORDER BY distance",
        (_ser(q), k),
    ).fetchall()
    return [(int(r[0]), float(r[1])) for r in rows]
