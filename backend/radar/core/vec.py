from __future__ import annotations
import numpy as np

from .embeddings import EMBED_DIM

# Plain SQLite tables holding embeddings as float32 BLOBs. Cosine similarity is
# computed in numpy (no sqlite extension) — the host Python has extension loading
# disabled. distance = 1 - cosine_similarity.
_TABLES = ("mention_vec", "incident_vec", "story_vec")


def create_vec_tables(conn) -> None:
    """Create vector tables. `conn` is a SQLAlchemy Connection or raw DBAPI conn."""
    exec_ = conn.exec_driver_sql if hasattr(conn, "exec_driver_sql") else conn.execute
    for t in _TABLES:
        exec_(
            f"CREATE TABLE IF NOT EXISTS {t} "
            f"(id INTEGER PRIMARY KEY, embedding BLOB NOT NULL)"
        )


def _ser(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def _deser(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v if n == 0 else v / n


def store(conn, table: str, row_id: int, v: np.ndarray) -> None:
    """Insert-or-replace one vector. `conn` is a raw DBAPI connection."""
    conn.execute(
        f"INSERT OR REPLACE INTO {table}(id, embedding) VALUES (?, ?)",
        (row_id, _ser(v)),
    )


def knn(conn, table: str, q: np.ndarray, k: int = 5) -> list[tuple[int, float]]:
    """Return [(id, cosine_distance), ...] nearest to q, closest first.

    Scans the whole table; callers only ever knn over centroid tables
    (incident_vec / story_vec), which stay small. Vectors are L2-normalized
    defensively so this is correct even if a stored vector wasn't unit length.
    """
    rows = conn.execute(f"SELECT id, embedding FROM {table}").fetchall()
    if not rows:
        return []
    qn = _unit(np.asarray(q, dtype=np.float32))
    out = [(int(rid), 1.0 - float(np.dot(qn, _unit(_deser(blob)))))
           for rid, blob in rows]
    out.sort(key=lambda x: x[1])
    return out[:k]
