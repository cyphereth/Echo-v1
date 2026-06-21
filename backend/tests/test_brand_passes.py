"""Brand router + brand domain tests — Task 4.2.

TDD step 1: write the failing test (radar.brand.api not yet importable).
Steps 2-N: implement, verify GREEN.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# TDD anchor: brand router requires auth
# ---------------------------------------------------------------------------

def test_brand_router_requires_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("ECHO_DB", f"sqlite:///{tmp_path / 'b.db'}")
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from radar.brand.api import router
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    r = c.get("/brands")           # no token
    assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Brand stories: update_stories clusters brand mentions
# ---------------------------------------------------------------------------

def test_brand_update_stories_clusters_mentions(tmp_path, monkeypatch):
    """update_stories(session, brand_id) clusters BrandMentions into BrandStories."""
    monkeypatch.setenv("ECHO_DB", f"sqlite:///{tmp_path / 's.db'}")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.brand.models  # register brand tables
    from radar.brand.models import Brand, BrandMention, BrandStory
    from radar.brand.stories import update_stories

    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = Session(eng)

    b = Brand(name="TestBrand", keywords='["test"]')
    s.add(b); s.flush()

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    for i in range(3):
        m = BrandMention(
            brand_id=b.id, platform="tiktok", post_id=f"p{i}",
            author=f"@u{i}", text=f"test brand mention number {i} about the product",
            created_at=now, first_seen=now, is_spam=False, source="brand",
        )
        s.add(m)
    s.commit()

    # Stub embed to avoid loading the real model
    import numpy as np
    def fake_embed(text: str):
        return np.ones(384, dtype=np.float32)

    # Should not raise — story clustering runs, degenerate (all identical vecs → 1 cluster)
    update_stories(s, b.id, embed=fake_embed)
    # With 3 mentions and identical embeddings, at least one BrandStory must be created.
    count = s.query(BrandStory).count()
    assert count >= 1, f"Expected at least 1 BrandStory, got {count}"


# ---------------------------------------------------------------------------
# Brand passes: run_brand_pipeline is importable and callable
# ---------------------------------------------------------------------------

def test_run_brand_pipeline_importable():
    """Smoke: brand.passes exports the four named functions."""
    from radar.brand.passes import (
        run_brand_pipeline, run_web_pass, run_chat_monitor, run_hotwatch
    )
    assert callable(run_brand_pipeline)
    assert callable(run_web_pass)
    assert callable(run_chat_monitor)
    assert callable(run_hotwatch)


# ---------------------------------------------------------------------------
# Brand digests: build_brand_digest is importable
# ---------------------------------------------------------------------------

def test_brand_digest_importable():
    from radar.brand.digests import build_brand_digest
    assert callable(build_brand_digest)


# ---------------------------------------------------------------------------
# Brand router: /brands returns 401/403 without token (full router smoke)
# ---------------------------------------------------------------------------

def test_brand_router_all_protected_endpoints(tmp_path, monkeypatch):
    """Several brand router endpoints should all reject unauthenticated requests."""
    monkeypatch.setenv("ECHO_DB", f"sqlite:///{tmp_path / 'c.db'}")
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from radar.brand.api import router
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    for path in ["/brands", "/inbox", "/opportunities", "/search", "/analytics"]:
        r = c.get(path)
        assert r.status_code in (401, 403, 422), f"{path} → {r.status_code}"


# ---------------------------------------------------------------------------
# run_web_pass writes BrandMention (NOT legacy Mention)
# ---------------------------------------------------------------------------

def _mem_brand():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.brand.models  # register brand tables
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)


def test_run_web_pass_writes_brand_mention_not_legacy():
    """run_web_pass must store results as BrandMention only (legacy Mention table gone).

    Feed a provider stub that returns a single relevant web result,
    then assert BrandMention.count() >= 1.
    The legacy Mention table was removed in Phase 5 — its absence is the proof
    that web results cannot accidentally land there.
    """
    from types import SimpleNamespace
    from radar.brand.models import Brand, BrandMention
    from radar.brand.passes import run_web_pass

    s = _mem_brand()
    now = datetime.now(timezone.utc)
    b = Brand(name="PizzaPalace", keywords='["пицца"]',
              niche_keywords='["пицца"]', auto_collect=True)
    s.add(b); s.commit()

    # Provider returns one relevant result containing the niche keyword.
    web_result = [{"url": "https://example.com/review", "title": "лучшая пицца",
                   "content": "вкусная пицца в центре города", "published": None}]
    web_provider = SimpleNamespace(search=lambda q: web_result)

    run_web_pass(s, web_provider)

    assert s.query(BrandMention).count() >= 1, "Expected at least 1 BrandMention"


# ---------------------------------------------------------------------------
# Brand anomaly: update_stories sets BrandStory.is_anomaly when triggered
# ---------------------------------------------------------------------------

def test_brand_anomaly_detect_anomaly_sets_is_anomaly():
    """detect_anomaly with BrandStory/BrandStoryPoint models sets is_anomaly on the story."""
    from radar.brand.models import Brand, BrandStory, BrandStoryPoint
    from radar.core.anomalies import detect_anomaly, MIN_BUCKETS, MIN_VOLUME, VOLUME_FACTOR

    s = _mem_brand()
    b = Brand(name="TestBrand", keywords='["test"]')
    s.add(b); s.flush()

    now = datetime.now(timezone.utc)
    st = BrandStory(brand_id=b.id, title="Test story",
                    first_seen_at=now, last_seen_at=now)
    s.add(st); s.flush()

    # Seed MIN_BUCKETS baseline points with low volume, then one spike point.
    base_count = 1  # low baseline volume
    for i in range(MIN_BUCKETS):
        from datetime import timedelta
        s.add(BrandStoryPoint(
            story_id=st.id,
            bucket_start=now - timedelta(hours=MIN_BUCKETS - i + 1),
            mention_count=base_count,
            avg_sentiment=0.5,
            source_count=1,
        ))
    # Spike: volume well above VOLUME_FACTOR * base_count, and sentiment drops.
    spike_vol = int(base_count * VOLUME_FACTOR * 2 + MIN_VOLUME)
    s.add(BrandStoryPoint(
        story_id=st.id,
        bucket_start=now,
        mention_count=spike_vol,
        avg_sentiment=-0.5,   # big sentiment drop
        source_count=5,
    ))
    s.commit()

    result = detect_anomaly(s, st.id, BrandStory, BrandStoryPoint)
    assert result is True, "Expected anomaly to be detected"
    s.refresh(st)
    assert st.is_anomaly is True, "BrandStory.is_anomaly should be True after detect_anomaly"


# ---------------------------------------------------------------------------
# News anomaly: update_stories sets NewsStory.is_anomaly when triggered
# ---------------------------------------------------------------------------

def test_news_anomaly_detect_anomaly_sets_is_anomaly():
    """detect_anomaly with NewsStory/NewsStoryPoint models sets is_anomaly."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.news.models  # register news tables
    from radar.news.models import NewsTopic, NewsStory, NewsStoryPoint
    from radar.core.anomalies import detect_anomaly, MIN_BUCKETS, MIN_VOLUME, VOLUME_FACTOR

    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = Session(eng)

    now = datetime.now(timezone.utc)
    t = NewsTopic(name="Тест"); s.add(t); s.flush()

    st = NewsStory(topic_id=t.id, title="Test story",
                   first_seen_at=now, last_seen_at=now)
    s.add(st); s.flush()

    base_count = 1
    base_src = 1
    for i in range(MIN_BUCKETS):
        from datetime import timedelta
        s.add(NewsStoryPoint(
            story_id=st.id,
            bucket_start=now - timedelta(hours=MIN_BUCKETS - i + 1),
            mention_count=base_count,
            source_count=base_src,
        ))
    # Spike: volume >> VOLUME_FACTOR * base_count, and source_count >> SOURCE_FACTOR * base_src.
    # NewsStoryPoint has no avg_sentiment, so anomaly triggers via src_influx alone.
    spike_vol = int(base_count * VOLUME_FACTOR * 2 + MIN_VOLUME)
    from radar.core.anomalies import SOURCE_FACTOR
    spike_src = int(base_src * SOURCE_FACTOR * 2 + 1)
    s.add(NewsStoryPoint(
        story_id=st.id,
        bucket_start=now,
        mention_count=spike_vol,
        source_count=spike_src,
    ))
    s.commit()

    result = detect_anomaly(s, st.id, NewsStory, NewsStoryPoint)
    assert result is True, "Expected news anomaly to be detected"
    s.refresh(st)
    assert st.is_anomaly is True, "NewsStory.is_anomaly should be True after detect_anomaly"
