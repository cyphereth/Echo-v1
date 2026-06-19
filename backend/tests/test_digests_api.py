import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone


def test_generate_and_list_digests(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'d.db'}")
    import importlib
    import radar.core.db as db; importlib.reload(db); db.init_db()
    import radar.digests as D; importlib.reload(D)
    import radar.api as api; importlib.reload(api)
    from fastapi.testclient import TestClient
    from radar.models import Story, StoryPoint, Brand, User

    s = db.get_session()
    u = User(email="d@d.d", password_hash="x"); s.add(u); s.flush()
    b = Brand(id=1, user_id=u.id, name="b"); s.add(b); s.flush()
    now = datetime.now(timezone.utc)
    st = Story(brand_id=1, title="t", status="active", post_count=5,
               first_seen_at=now, last_seen_at=now)
    s.add(st); s.flush()
    s.add(StoryPoint(story_id=st.id, bucket_start=now, mention_count=5,
                     avg_sentiment=-0.2, source_count=2))
    s.commit()

    # stub the LLM call (no network). D was reloaded above; api imports build_daily_digest
    # from .digests at call time, so patching D.llm.complete is what matters.
    monkeypatch.setattr(D.llm, "complete", lambda *a, **k: "ГОТОВО")

    api.app.dependency_overrides[api.current_user] = lambda: u
    client = TestClient(api.app)

    r = client.post("/brands/1/digest")
    assert r.status_code == 200, r.text
    assert r.json()["body"] == "ГОТОВО"

    r2 = client.get("/brands/1/digests")
    assert r2.status_code == 200
    assert len(r2.json()) == 1 and r2.json()[0]["kind"] == "digest"
    api.app.dependency_overrides.clear()
