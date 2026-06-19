"""Tests for radar.news.passes (topic TG + web passes) and the /news router.

Ported from tests/test_topic_tg.py — that file will be deleted once these are green.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone, timedelta


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mem():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from radar.news.models import Base as NewsBase
    from radar.models import Base as LegacyBase
    eng = create_engine("sqlite:///:memory:")
    LegacyBase.metadata.create_all(eng)
    NewsBase.metadata.create_all(eng)
    return _S(eng)


def _post(pid, text, author="@ch", created=None):
    from radar.core.providers.base import Post
    return Post(post_id=pid, platform="telegram", author=author, followers=5000,
                text=text, hashtags=[], created_at=created or datetime.now(timezone.utc),
                likes=1, views=10, comments=0, shares=0)


# ── /news router smoke test (TDD anchor) ──────────────────────────────────────

def test_news_router_lists_topics(monkeypatch, tmp_path):
    """Smoke: the /news router returns 200 + list for /news/topics."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 't.db'}")
    import importlib
    import radar.core.db as db_mod; importlib.reload(db_mod); db_mod.init_db()
    from fastapi import FastAPI
    from radar.news.api import router
    from fastapi.testclient import TestClient

    import radar.api as api_mod; importlib.reload(api_mod)
    from radar.models import User
    s = db_mod.get_session()
    u = User(email="pass@t.t", password_hash="x"); s.add(u); s.flush(); s.commit()

    app = FastAPI()
    app.include_router(router)
    # Override the dependency so no auth header is needed in this smoke test
    from radar.news import api as news_api
    news_api.router.dependencies.clear()

    from radar.core.db import get_session as _gs
    def _override_db():
        yield s

    app2 = FastAPI()
    from fastapi import Depends
    from radar.news.api import router as r2
    app2.include_router(r2)
    from radar.news import api as na
    app2.dependency_overrides[na.current_user] = lambda: u
    app2.dependency_overrides[na.db] = _override_db

    client = TestClient(app2)
    resp = client.get("/news/topics")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    s.close()


# ── run_topic_tg_pass ─────────────────────────────────────────────────────────

def test_run_topic_tg_pass_iterates_autocollect_topics(monkeypatch):
    from radar.news.models import NewsTopic
    from radar.news import passes as P
    s = _mem()
    s.add(NewsTopic(id=1, name="Экономика", kind="default", auto_collect=True,
                    keywords='["инфляция"]', niche_keywords='["инфляция"]'))
    s.add(NewsTopic(id=2, name="Приват", kind="search", auto_collect=False,
                    keywords='["x"]', niche_keywords='["x"]'))
    s.flush(); s.commit()
    monkeypatch.setattr("radar.news.passes.ensure_topic_channels_discovered",
                        lambda sess, t, prov, **k: 0)
    monkeypatch.setattr("radar.news.passes.ensure_topic_global_probe",
                        lambda sess, t: None)
    monkeypatch.setattr("radar.news.passes.collect_probe",
                        lambda sess, probe, prov: 0)
    clustered = []
    monkeypatch.setattr("radar.news.passes.update_stories",
                        lambda sess, topic_id: clustered.append(topic_id) or {})
    P.run_topic_tg_pass(s, tg_provider=object())
    assert clustered == [1]


def test_run_topic_tg_pass_noop_without_provider(monkeypatch):
    from radar.news.models import NewsTopic
    from radar.news import passes as P
    s = _mem()
    s.add(NewsTopic(id=1, name="Экономика", auto_collect=True,
                    keywords='["инфляция"]', niche_keywords='["инфляция"]'))
    s.flush(); s.commit()
    called = []
    monkeypatch.setattr("radar.news.passes.ensure_topic_global_probe",
                        lambda sess, t: called.append(t.id))
    P.run_topic_tg_pass(s, tg_provider=None)
    assert called == []


def test_telegram_floodwait_is_runtimeerror():
    from radar.core.providers.telegram import TelegramFloodWait
    e = TelegramFloodWait(42)
    assert isinstance(e, RuntimeError)
    assert e.seconds == 42 and "42" in str(e)


def test_run_topic_tg_pass_caps_and_rotates_channels(monkeypatch):
    from radar.news.models import NewsTopic, NewsProbe
    from radar.news import passes as P
    s = _mem()
    s.add(NewsTopic(id=1, name="Эк", kind="default", auto_collect=True,
                    keywords='["k"]', niche_keywords='["k"]'))
    s.flush()
    now = datetime.now(timezone.utc)
    for i in range(5):  # c0 is least-recently-run (smallest next_run_at)
        s.add(NewsProbe(topic_id=1, platform="telegram", kind="channel", query=f"@c{i}",
                        label="test", next_run_at=now + timedelta(seconds=i), interval_sec=3600))
    s.commit()
    monkeypatch.setattr("radar.news.passes.ensure_topic_channels_discovered", lambda *a, **k: 0)
    monkeypatch.setattr("radar.news.passes.ensure_topic_global_probe", lambda *a, **k: None)
    monkeypatch.setattr("radar.news.passes.update_stories", lambda *a, **k: {})
    monkeypatch.setattr(P, "MAX_TOPIC_CHANNELS_PER_RUN", 2)
    read = []
    monkeypatch.setattr("radar.news.passes.collect_probe",
                        lambda sess, probe, prov: read.append(probe.query) or 0)
    P.run_topic_tg_pass(s, tg_provider=object())
    assert read == ["@c0", "@c1"]  # only the 2 least-recently-run
    # pushed to the back of the rotation
    c0 = s.query(NewsProbe).filter_by(query="@c0").one()
    c4 = s.query(NewsProbe).filter_by(query="@c4").one()
    assert c0.next_run_at > c4.next_run_at


def test_run_topic_tg_pass_aborts_on_floodwait(monkeypatch):
    from radar.news.models import NewsTopic, NewsProbe
    from radar.news import passes as P
    from radar.core.providers.telegram import TelegramFloodWait
    s = _mem()
    s.add(NewsTopic(id=1, name="Эк", auto_collect=True,
                    keywords='["k"]', niche_keywords='["k"]'))
    s.flush()
    for i in range(3):
        s.add(NewsProbe(topic_id=1, platform="telegram", kind="channel", query=f"@c{i}",
                        label="t"))
    s.commit()
    monkeypatch.setattr("radar.news.passes.ensure_topic_channels_discovered", lambda *a, **k: 0)
    monkeypatch.setattr("radar.news.passes.ensure_topic_global_probe", lambda *a, **k: None)
    monkeypatch.setattr("radar.news.passes.update_stories", lambda *a, **k: {})
    monkeypatch.setattr(P, "MAX_TOPIC_CHANNELS_PER_RUN", 10)
    calls = []
    def boom(sess, probe, prov):
        calls.append(probe.query)
        raise TelegramFloodWait(30)
    monkeypatch.setattr("radar.news.passes.collect_probe", boom)
    P.run_topic_tg_pass(s, tg_provider=object())
    assert len(calls) == 1  # aborted after first flood


# ── run_topic_web_pass ────────────────────────────────────────────────────────

def test_run_topic_web_pass_collects_and_clusters(monkeypatch):
    from radar.news.models import NewsTopic
    from radar.news import passes as P
    s = _mem()
    s.add(NewsTopic(id=1, name="Рынок", auto_collect=True,
                    keywords='["рубль"]', niche_keywords='["рубль"]'))
    s.flush(); s.commit()
    collected = []
    clustered = []
    monkeypatch.setattr("radar.news.passes.collect_web",
                        lambda sess, topic_id, prov: collected.append(topic_id) or 1)
    monkeypatch.setattr("radar.news.passes.update_stories",
                        lambda sess, topic_id: clustered.append(topic_id) or {})
    P.run_topic_web_pass(s, web_provider=object())
    assert collected == [1]
    assert clustered == [1]


def test_run_topic_web_pass_noop_without_mentions(monkeypatch):
    from radar.news.models import NewsTopic
    from radar.news import passes as P
    s = _mem()
    s.add(NewsTopic(id=1, name="Рынок", auto_collect=True,
                    keywords='["рубль"]', niche_keywords='["рубль"]'))
    s.flush(); s.commit()
    clustered = []
    monkeypatch.setattr("radar.news.passes.collect_web",
                        lambda sess, topic_id, prov: 0)   # no new mentions
    monkeypatch.setattr("radar.news.passes.update_stories",
                        lambda sess, topic_id: clustered.append(topic_id) or {})
    P.run_topic_web_pass(s, web_provider=object())
    assert clustered == []   # update_stories NOT called when collect_web returns 0
