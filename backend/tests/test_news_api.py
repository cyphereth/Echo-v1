import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'t.db'}")
    import importlib
    import radar.core.db as db; importlib.reload(db); db.init_db()
    import radar.seed as seed; importlib.reload(seed)
    import radar.news.api as news_api; importlib.reload(news_api)
    import radar.api as api; importlib.reload(api)
    from fastapi.testclient import TestClient
    from radar.models import User
    s = db.get_session()
    seed.ensure_default_topics(s)
    u = User(email="u1@t.t", password_hash="x"); s.add(u); s.flush(); s.commit()
    # Override both the main app's current_user and the news router's current_user
    api.app.dependency_overrides[api.current_user] = lambda: u
    api.app.dependency_overrides[news_api.current_user] = lambda: u
    return api, TestClient(api.app), s, u


def test_news_topics_defaults_and_private(monkeypatch, tmp_path):
    api, client, s, u = _client(monkeypatch, tmp_path)
    # GET /news/topics returns NewsTopic rows (seeded by ensure_default_topics)
    r = client.get("/news/topics")
    assert r.status_code == 200
    names = {t["name"] for t in r.json()}
    assert {"Экономика", "Геополитика", "Военное"} <= names
    # create a private NewsTopic
    r2 = client.post("/news/topics", json={"name": "Моя тема", "keywords": ["крипта"]})
    assert r2.status_code == 200, r2.text
    assert "id" in r2.json()
    api.app.dependency_overrides.clear()


def test_inbox_shows_unlaned_topic_mentions(monkeypatch, tmp_path):
    """Topic web mentions skip the brand draft pipeline, so they carry no lane.
    The feed must still surface them (treated as smm).
    Uses legacy Topic + Mention models since /inbox is served from radar/api.py."""
    from datetime import datetime, timezone
    import json as _j
    api, client, s, u = _client(monkeypatch, tmp_path)
    # Use legacy Topic model (inbox endpoint queries legacy Mention/Topic)
    from radar.models import Topic, Mention
    t = Topic(user_id=u.id, kind="search", name="Рынок",
              keywords=_j.dumps(["рубль"], ensure_ascii=False),
              niche_keywords=_j.dumps(["рубль"], ensure_ascii=False), auto_collect=True)
    s.add(t); s.flush()
    s.add(Mention(topic_id=t.id, platform="web", post_id="w1", author="news.ru",
                  text="свежая новость про рубль", source="niche", lane=None,
                  is_spam=False, created_at=datetime.now(timezone.utc)))
    s.commit()
    body = client.get(f"/inbox?topic_id={t.id}").json()
    texts = {c["text"] for c in body["pr"] + body["smm"]}
    assert "свежая новость про рубль" in texts
    api.app.dependency_overrides.clear()


def test_sources_panel_list_add_delete(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    api, client, s, u = _client(monkeypatch, tmp_path)
    # Use the news-domain NewsTopic "Экономика" (seeded by ensure_default_topics)
    from radar.news.models import NewsTopic
    from radar.models import Probe, Mention
    t = s.query(NewsTopic).filter_by(name="Экономика").first()
    s.add(Probe(topic_id=t.id, platform="telegram", kind="channel", query="@junk", source="niche", label="Junk"))
    s.flush()
    now = datetime.now(timezone.utc)
    s.add(Mention(topic_id=t.id, platform="telegram", post_id="m1", author="@junk",
                  text="мусор из канала", source="niche", created_at=now))
    # Web mentions are tracked via NewsMention in the news router; for the source panel
    # web row, add a NewsMention (the sources endpoint queries NewsMention for web domains)
    from radar.news.models import NewsMention
    s.add(NewsMention(topic_id=t.id, platform="web", post_id="w1", author="rbc.ru",
                      text="новость", source="global", created_at=now))
    s.commit()

    # list: channel probe + web domain, with counts
    body = client.get(f"/topics/{t.id}/sources").json()
    by_handle = {x["handle"]: x for x in body}
    assert by_handle["@junk"]["mention_count"] == 1 and by_handle["@junk"]["kind"] == "channel"
    assert by_handle["rbc.ru"]["kind"] == "web"

    # add a channel
    r = client.post(f"/topics/{t.id}/sources", json={"handle": "@interfaxonline"})
    assert r.status_code == 200, r.text
    handles = {x["handle"] for x in client.get(f"/topics/{t.id}/sources").json()}
    assert "@interfaxonline" in handles
    # duplicate add → 409
    assert client.post(f"/topics/{t.id}/sources", json={"handle": "@interfaxonline"}).status_code == 409

    # delete the junk probe → probe + its mentions gone
    pid = by_handle["@junk"]["id"]
    assert client.delete(f"/topics/{t.id}/sources/{pid}").status_code == 200
    handles2 = {x["handle"] for x in client.get(f"/topics/{t.id}/sources").json()}
    assert "@junk" not in handles2
    assert s.query(Mention).filter_by(author="@junk").count() == 0
    api.app.dependency_overrides.clear()


def test_private_topic_not_readable_by_other_user(monkeypatch, tmp_path):
    """A private NewsTopic should not be accessible by another user.
    Tests via GET /news/topics (news router) — the router enforces user_id ownership."""
    import radar.news.api as news_api
    api, client, s, u = _client(monkeypatch, tmp_path)
    # Create a private topic as user u
    r_create = client.post("/news/topics", json={"name": "Секрет", "keywords": ["x"]})
    assert r_create.status_code == 200
    tid = r_create.json()["id"]
    # Switch to another user — the topic should NOT appear in their list
    from radar.models import User
    other = User(email="u2@t.t", password_hash="x"); s.add(other); s.flush(); s.commit()
    api.app.dependency_overrides[api.current_user] = lambda: other
    api.app.dependency_overrides[news_api.current_user] = lambda: other
    r = client.get("/news/topics")
    assert r.status_code == 200
    ids = {t["id"] for t in r.json()}
    assert tid not in ids  # private topic not visible to other user
    api.app.dependency_overrides.clear()
