import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone
import pytest


def _mem():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _S
    from radar.models import Base
    import radar.news.models  # register news tables
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return _S(eng)


def _story_with_sources(s, authors):
    """A topic (news-domain) story with one incident and a mention per author."""
    from radar.news.models import NewsTopic, NewsStory, NewsIncident, NewsMention
    now = datetime.now(timezone.utc)
    t = NewsTopic(id=1, name="Тест", kind="search",
                  keywords='["тест"]', niche_keywords='["тест"]', auto_collect=True)
    s.add(t); s.flush()
    st = NewsStory(id=1, topic_id=1, title="Взрыв на заводе", status="active",
                   first_seen_at=now, last_seen_at=now, post_count=len(authors))
    s.add(st); s.flush()
    inc = NewsIncident(id=1, topic_id=1, story_id=1, title="Взрыв на заводе",
                       post_count=len(authors), first_seen_at=now, last_seen_at=now)
    s.add(inc); s.flush()
    for i, a in enumerate(authors):
        s.add(NewsMention(topic_id=1, incident_id=1, platform="telegram", post_id=f"p{i}",
                          author=a, text="Сообщают о взрыве на заводе", created_at=now))
    s.flush()
    return st


# ── cross-verification ──────────────────────────────────────────────────────────

def test_recompute_verification_counts_distinct_sources():
    import radar.news.stories as ST
    s = _mem()
    st = _story_with_sources(s, ["@a", "@a", "@b", "news.ru", ""])  # blank ignored, @a dedup
    ST._recompute_verification(s, st.topic_id)
    s.refresh(st)
    assert st.source_count == 3
    assert st.verified is True   # >= VERIFY_MIN_SOURCES (3)


def test_recompute_verification_below_threshold_not_verified():
    import radar.news.stories as ST
    s = _mem()
    st = _story_with_sources(s, ["@a", "@b"])   # only 2 distinct sources
    ST._recompute_verification(s, st.topic_id)
    s.refresh(st)
    assert st.source_count == 2
    assert st.verified is False


# ── fake-detection (LLM) ────────────────────────────────────────────────────────

def test_assess_credibility_parses_verdict(monkeypatch):
    import radar.news.credibility as CR
    s = _mem()
    st = _story_with_sources(s, ["@a"])
    seen = {}
    def _fake(system, user, **k):
        seen["user"] = user
        return '{"verdict": "suspect", "note": "единственный источник, нет подтверждений"}'
    monkeypatch.setattr(CR.llm, "complete", _fake)
    CR.assess_credibility(s, st)
    assert st.credibility == "suspect"
    assert "источник" in st.credibility_note
    assert "Взрыв" in seen["user"]   # story content fed to the model


def test_assess_credibility_malformed_defaults_unrated(monkeypatch):
    import radar.news.credibility as CR
    s = _mem()
    st = _story_with_sources(s, ["@a"])
    monkeypatch.setattr(CR.llm, "complete", lambda system, user, **k: "не могу определить")
    CR.assess_credibility(s, st)
    assert st.credibility == "unrated"
    assert st.credibility_note   # keeps the raw note


def test_assess_credibility_raises_without_key(monkeypatch):
    import radar.news.credibility as CR
    s = _mem()
    st = _story_with_sources(s, ["@a"])
    def _boom(*a, **k):
        raise CR.llm.LLMNotConfigured("no key")
    monkeypatch.setattr(CR.llm, "complete", _boom)
    with pytest.raises(CR.llm.LLMNotConfigured):
        CR.assess_credibility(s, st)


# ── API ─────────────────────────────────────────────────────────────────────────

def _api(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'c.db'}")
    import importlib
    import radar.core.db as db; importlib.reload(db); db.init_db()
    import radar.seed as seed; importlib.reload(seed)
    # Reload news_api FIRST so the app.include_router picks up the reloaded current_user
    import radar.news.api as news_api; importlib.reload(news_api)
    import radar.app as api; importlib.reload(api)
    from fastapi.testclient import TestClient
    from radar.models import User
    s = db.get_session()
    seed.ensure_default_topics(s)
    u = User(email="c@c.c", password_hash="x"); s.add(u); s.flush(); s.commit()
    # /news/stories/* is served by news router — override news_api.current_user
    api.app.dependency_overrides[news_api.current_user] = lambda: u
    return api, news_api, TestClient(api.app), s, u


def _topic_story(s, topic_id=1):
    """Create a NewsStory (news-domain) for a NewsTopic."""
    from radar.news.models import NewsTopic, NewsStory, NewsIncident, NewsMention
    now = datetime.now(timezone.utc)
    # Ensure the NewsTopic exists (seed creates id=1,2,3… — re-use or create)
    t = s.get(NewsTopic, topic_id)
    if t is None:
        t = NewsTopic(id=topic_id, name="Тест", kind="search",
                      keywords='["тест"]', niche_keywords='["тест"]',
                      auto_collect=True)
        s.add(t); s.flush()
    st = NewsStory(topic_id=topic_id, title="Сюжет про экономику", status="active",
                   source_count=3, verified=True, first_seen_at=now, last_seen_at=now, post_count=3)
    s.add(st); s.flush()
    inc = NewsIncident(topic_id=topic_id, story_id=st.id, title="Инцидент",
                       post_count=3, first_seen_at=now, last_seen_at=now)
    s.add(inc); s.flush()
    for i, a in enumerate(["@a", "@b", "@c"]):
        s.add(NewsMention(topic_id=topic_id, incident_id=inc.id, platform="telegram",
                          post_id=f"m{i}", author=a, text="Новость про экономику", created_at=now))
    s.commit()
    return st


def test_storyout_has_credibility_fields(monkeypatch, tmp_path):
    api, news_api, client, s, u = _api(monkeypatch, tmp_path)
    _topic_story(s, topic_id=1)
    body = client.get("/news/stories?topic_id=1").json()
    assert len(body) == 1
    row = body[0]
    assert row["source_count"] == 3 and row["verified"] is True
    assert row["credibility"] == "unrated"
    api.app.dependency_overrides.clear()


def test_get_topic_story_detail_ok(monkeypatch, tmp_path):
    """Regression: story detail must work for topic stories (brand_id NULL)."""
    api, news_api, client, s, u = _api(monkeypatch, tmp_path)
    st = _topic_story(s, topic_id=1)
    r = client.get(f"/news/stories/{st.id}")
    assert r.status_code == 200, r.text
    assert r.json()["verified"] is True
    api.app.dependency_overrides.clear()


def test_assess_endpoint_updates_credibility(monkeypatch, tmp_path):
    api, news_api, client, s, u = _api(monkeypatch, tmp_path)
    st = _topic_story(s, topic_id=1)
    import radar.news.credibility as CR
    monkeypatch.setattr(CR.llm, "complete",
                        lambda system, user, **k: '{"verdict":"credible","note":"много источников"}')
    r = client.post(f"/news/stories/{st.id}/assess")
    assert r.status_code == 200, r.text
    assert r.json()["credibility"] == "credible"
    assert "источник" in r.json()["credibility_note"]
    api.app.dependency_overrides.clear()


def test_story_detail_lists_sources_first_seen(monkeypatch, tmp_path):
    api, news_api, client, s, u = _api(monkeypatch, tmp_path)
    st = _topic_story(s, topic_id=1)   # authors @a,@b,@c, all same time
    body = client.get(f"/news/stories/{st.id}").json()
    authors = {x["author"] for x in body["sources"]}
    assert authors == {"@a", "@b", "@c"}
    assert all("first_seen" in x and x["count"] >= 1 for x in body["sources"])
    api.app.dependency_overrides.clear()


def test_summarize_endpoint_sets_summary(monkeypatch, tmp_path):
    api, news_api, client, s, u = _api(monkeypatch, tmp_path)
    st = _topic_story(s, topic_id=1)
    import radar.news.credibility as CR
    monkeypatch.setattr(CR.llm, "complete",
                        lambda system, user, **k: "На заводе произошёл взрыв, есть пострадавшие.")
    r = client.post(f"/news/stories/{st.id}/summarize")
    assert r.status_code == 200, r.text
    assert "взрыв" in r.json()["summary"]
    assert "взрыв" in client.get(f"/news/stories/{st.id}").json()["summary"]
    api.app.dependency_overrides.clear()
