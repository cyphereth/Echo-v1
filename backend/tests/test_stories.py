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


def test_models_create_and_relate():
    from radar.models import Story, Incident, StoryPoint, Mention
    s = _session()
    st = Story(brand_id=1, title="t",
               first_seen_at=datetime.now(timezone.utc),
               last_seen_at=datetime.now(timezone.utc))
    s.add(st); s.flush()
    inc = Incident(brand_id=1, story_id=st.id, title="i",
                   first_seen_at=datetime.now(timezone.utc),
                   last_seen_at=datetime.now(timezone.utc))
    s.add(inc); s.flush()
    m = Mention(brand_id=1, platform="telegram", post_id="p", author="@a",
                text="x", source="niche", incident_id=inc.id,
                created_at=datetime.now(timezone.utc))
    s.add(m); s.flush()
    pt = StoryPoint(story_id=st.id, bucket_start=datetime.now(timezone.utc),
                    mention_count=3, avg_sentiment=0.5, source_count=2)
    s.add(pt); s.commit()
    assert st.id and inc.story_id == st.id and m.incident_id == inc.id
    assert st.is_anomaly is False and st.status == "active"
