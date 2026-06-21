"""test_stories.py — surviving tests from the legacy stories module.

Legacy tests that referenced deleted modules (radar.stories, radar.models.Story/
Incident/StoryPoint/Mention, radar.scope) have been removed. Their coverage is now
provided by test_brand_passes.py, test_news_stories.py, test_clustering_engine.py,
and test_brand_passes.py::test_brand_anomaly_detect_anomaly_sets_is_anomaly.

Surviving tests:
  - test_store_and_knn_roundtrip: vector store/search (core.vec, no legacy models)
  - test_scheduler_calls_update_stories: scheduler delegation to brand domain
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone, timedelta
import numpy as np
import pytest


def _engine_with_vec():
    """In-memory engine with all tables created (vec tables are plain SQLite)."""
    from sqlalchemy import create_engine
    from radar.models import Base
    from radar.core import vec

    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    with eng.begin() as conn:
        vec.create_vec_tables(conn)
    return eng


def _session():
    from sqlalchemy.orm import Session as _S
    return _S(_engine_with_vec())


def test_store_and_knn_roundtrip():
    from radar.core import vec
    s = _session()
    conn = s.connection().connection  # raw DBAPI conn
    a = np.array([1.0, 0.0] + [0.0] * 382, dtype=np.float32)
    b = np.array([0.0, 1.0] + [0.0] * 382, dtype=np.float32)
    vec.store(conn, "incident_vec", 1, a)
    vec.store(conn, "incident_vec", 2, b)
    hits = vec.knn(conn, "incident_vec", a, k=2)
    assert hits[0][0] == 1            # nearest id is the identical vector
    assert hits[0][1] == pytest.approx(0.0, abs=1e-4)  # cosine distance ~0


def test_scheduler_calls_update_stories(monkeypatch):
    import radar.core.scheduler as SCH
    from radar.models import Brand
    calls = []
    # brand/passes.py delegates to radar.brand.stories / radar.brand.pipeline
    monkeypatch.setattr("radar.brand.stories.update_stories",
                        lambda sess, brand_id: calls.append(brand_id) or {})
    monkeypatch.setattr("radar.brand.pipeline.classify_and_draft", lambda sess, bid: {})
    monkeypatch.setattr("radar.brand.pipeline.fetch_new_comments",
                        lambda sess, bid, p, t: 0)
    # Provide a real session with brand 7 so scope_for_brand can build a scope.
    s = _session()
    s.add(Brand(id=7, name="TestBrand7", keywords='[]', niche_keywords='[]'))
    s.commit()
    # exercise the per-brand post-collect block in isolation
    SCH._run_brand_pipeline(session=s, brand_id=7, provider=None, tg_provider=None)
    assert len(calls) == 1 and calls[0] == 7
