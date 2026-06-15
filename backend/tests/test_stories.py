import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone, timedelta
import numpy as np
import pytest


def _engine_with_vec():
    """In-memory engine with all tables created (vec tables are plain SQLite)."""
    from sqlalchemy import create_engine
    from radar.models import Base
    from radar import vec

    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        vec.create_vec_tables(conn)
    return eng


def _session():
    from sqlalchemy.orm import Session as _S
    return _S(_engine_with_vec())


def test_store_and_knn_roundtrip():
    from radar import vec
    s = _session()
    conn = s.connection().connection  # raw DBAPI conn
    a = np.array([1.0, 0.0] + [0.0] * 382, dtype=np.float32)
    b = np.array([0.0, 1.0] + [0.0] * 382, dtype=np.float32)
    vec.store(conn, "incident_vec", 1, a)
    vec.store(conn, "incident_vec", 2, b)
    hits = vec.knn(conn, "incident_vec", a, k=2)
    assert hits[0][0] == 1            # nearest id is the identical vector
    assert hits[0][1] == pytest.approx(0.0, abs=1e-4)  # cosine distance ~0
