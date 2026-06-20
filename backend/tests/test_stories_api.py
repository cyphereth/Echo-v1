import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone


def test_list_and_detail(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'a.db'}")
    import importlib
    import radar.core.db as db; importlib.reload(db); db.init_db()
    # Reload brand_api FIRST so the app.include_router picks up the reloaded current_user
    import radar.brand.api as brand_api; importlib.reload(brand_api)
    import radar.api as api; importlib.reload(api)
    from fastapi.testclient import TestClient
    from radar.models import Brand, User
    from radar.brand.models import BrandStory, BrandIncident, BrandStoryPoint, BrandMention

    s = db.get_session()
    u = User(email="t@t.t", password_hash="x"); s.add(u); s.flush()
    b = Brand(id=1, user_id=u.id, name="b"); s.add(b); s.flush()
    now = datetime.now(timezone.utc)
    st = BrandStory(brand_id=1, title="кризис", first_seen_at=now, last_seen_at=now, post_count=2)
    s.add(st); s.flush()
    inc = BrandIncident(brand_id=1, story_id=st.id, title="i",
                        first_seen_at=now, last_seen_at=now)
    s.add(inc); s.flush()
    s.add(BrandMention(brand_id=1, platform="telegram", post_id="p", author="@a",
                       text="x", source="niche", incident_id=inc.id,
                       created_at=now, first_seen=now))
    s.add(BrandStoryPoint(story_id=st.id, bucket_start=now,
                          mention_count=2, avg_sentiment=-0.5, source_count=1))
    s.commit()

    # /stories?brand_id= is served by brand router — override brand_api.current_user
    api.app.dependency_overrides[brand_api.current_user] = lambda: u
    client = TestClient(api.app)

    r = client.get("/stories?brand_id=1")
    assert r.status_code == 200, r.text
    assert r.json()[0]["title"] == "кризис"
    sid = r.json()[0]["id"]

    r2 = client.get(f"/stories/{sid}")
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["title"] == "кризис"
    assert len(body["points"]) == 1
    assert body["points"][0]["mention_count"] == 2
    assert len(body["incidents"]) == 1

    api.app.dependency_overrides.clear()


def test_list_sorts_anomalous_first(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'b.db'}")
    import importlib
    import radar.core.db as db; importlib.reload(db); db.init_db()
    # Reload brand_api FIRST so the app.include_router picks up the reloaded current_user
    import radar.brand.api as brand_api; importlib.reload(brand_api)
    import radar.api as api; importlib.reload(api)
    from fastapi.testclient import TestClient
    from radar.models import Brand, User
    from radar.brand.models import BrandStory
    from datetime import datetime, timezone, timedelta

    s = db.get_session()
    u = User(email="t2@t.t", password_hash="x"); s.add(u); s.flush()
    b = Brand(id=1, user_id=u.id, name="b"); s.add(b); s.flush()
    now = datetime.now(timezone.utc)
    # "calm" is newer (would sort first by recency) but not anomalous;
    # "attack" is older but anomalous -> must come first.
    s.add(BrandStory(brand_id=1, title="calm", is_anomaly=False,
                     first_seen_at=now, last_seen_at=now))
    s.add(BrandStory(brand_id=1, title="attack", is_anomaly=True,
                     first_seen_at=now - timedelta(days=1),
                     last_seen_at=now - timedelta(days=1)))
    s.commit()

    # /stories?brand_id= is served by brand router
    api.app.dependency_overrides[brand_api.current_user] = lambda: u
    client = TestClient(api.app)
    titles = [row["title"] for row in client.get("/stories?brand_id=1").json()]
    api.app.dependency_overrides.clear()
    assert titles == ["attack", "calm"]
