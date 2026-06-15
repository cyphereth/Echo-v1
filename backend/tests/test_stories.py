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


def _mk(s, **kw):
    from radar.models import Mention
    d = dict(brand_id=1, platform="telegram", post_id="p", author="@a",
             text="t", source="niche", is_spam=False,
             created_at=datetime.now(timezone.utc))
    d.update(kw)
    m = Mention(**d); s.add(m); s.flush(); return m


def _fake_embed(mapping):
    """Return an embed() stub mapping text -> 384-vec (first dims set)."""
    import numpy as np
    def _e(texts):
        out = np.zeros((len(texts), 384), dtype=np.float32)
        for i, t in enumerate(texts):
            for j, val in enumerate(mapping[t]):
                out[i, j] = val
        return out
    return _e


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


def test_init_db_loads_vec_and_migrates(tmp_path, monkeypatch):
    db_file = tmp_path / "t.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    import importlib, radar.db as db
    importlib.reload(db)            # pick up env + re-register listeners
    db.init_db()
    with db.engine.connect() as c:
        # vec table usable
        c.exec_driver_sql("SELECT count(*) FROM mention_vec")
        # incident_id column added to mentions
        cols = {r[1] for r in c.exec_driver_sql("PRAGMA table_info(mentions)")}
        assert "incident_id" in cols


def test_dedup_collapses_near_duplicates(monkeypatch):
    import radar.stories as S
    s = _session()
    now = datetime.now(timezone.utc)
    m1 = _mk(s, post_id="a", text="пожар на заводе", created_at=now)
    m2 = _mk(s, post_id="b", text="пожар завод дубль", created_at=now + timedelta(minutes=5))
    m3 = _mk(s, post_id="c", text="концерт в парке", created_at=now + timedelta(minutes=6))
    s.commit()
    monkeypatch.setattr(S.embeddings, "embed", _fake_embed({
        "пожар на заводе":   [1.0, 0.0, 0.0],
        "пожар завод дубль": [0.99, 0.01, 0.0],   # near-duplicate of m1
        "концерт в парке":   [0.0, 1.0, 0.0],     # different
    }))
    S.update_stories(s, brand_id=1)
    s.refresh(m1); s.refresh(m2); s.refresh(m3)
    assert m1.incident_id == m2.incident_id          # collapsed
    assert m3.incident_id != m1.incident_id          # separate incident
    from radar.models import Incident
    assert s.query(Incident).count() == 2


def test_incidents_link_into_one_story(monkeypatch):
    import radar.stories as S
    from radar.models import Story
    s = _session()
    now = datetime.now(timezone.utc)
    # two NON-duplicate but topically-close incidents (sim ~0.8, below INCIDENT_SIM,
    # above STORY_SIM) → same story.
    _mk(s, post_id="a", text="скандал день1", created_at=now)
    _mk(s, post_id="b", text="скандал день2", created_at=now + timedelta(days=1))
    s.commit()
    monkeypatch.setattr(S.embeddings, "embed", _fake_embed({
        "скандал день1": [1.0, 0.0, 0.0],
        "скандал день2": [0.82, 0.57, 0.0],   # cos≈0.82: new incident, same story
    }))
    S.update_stories(s, brand_id=1)
    stories = s.query(Story).all()
    assert len(stories) == 1
    assert stories[0].post_count == 2


def test_recompute_points_buckets_by_hour(monkeypatch):
    import radar.stories as S
    from radar.models import StoryPoint
    s = _session()
    base = datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc)
    # 2 mentions same hour (one + / one -), 1 next hour; all same topic → 1 story
    _mk(s, post_id="a", text="тема x", author="@u1", tone="positive", created_at=base + timedelta(minutes=2))
    _mk(s, post_id="b", text="тема x две", author="@u2", tone="negative", created_at=base + timedelta(minutes=40))
    _mk(s, post_id="c", text="тема x три", author="@u1", tone="neutral", created_at=base + timedelta(hours=1, minutes=5))
    s.commit()
    monkeypatch.setattr(S.embeddings, "embed", _fake_embed({
        "тема x":     [1.0, 0.0, 0.0],
        "тема x две": [0.999, 0.01, 0.0],
        "тема x три": [0.999, 0.0, 0.01],
    }))
    S.update_stories(s, brand_id=1)
    pts = s.query(StoryPoint).order_by(StoryPoint.bucket_start).all()
    assert len(pts) == 2
    assert pts[0].mention_count == 2
    assert pts[0].avg_sentiment == 0.0      # (+1 + -1)/2
    assert pts[0].source_count == 2         # @u1, @u2
    assert pts[1].mention_count == 1
    assert pts[1].source_count == 1


def test_scheduler_calls_update_stories(monkeypatch):
    import radar.scheduler as SCH
    calls = []
    monkeypatch.setattr("radar.stories.update_stories",
                        lambda sess, bid: calls.append(bid) or {})
    monkeypatch.setattr("radar.pipeline.classify_and_draft", lambda sess, bid: {})
    monkeypatch.setattr("radar.pipeline.fetch_new_comments",
                        lambda sess, bid, p, t: 0)
    # exercise the per-brand post-collect block in isolation
    SCH._run_brand_pipeline(session=object(), brand_id=7, provider=None, tg_provider=None)
    assert calls == [7]
