# backend/tests/test_intel_feed_api.py
"""Tests for the Feed v2 multi-column endpoints (/intel/feed, /intel/feed/layout,
POST /intel/directions). Uses tmp_path+monkeypatch so each test gets a clean DB."""


def test_feed_returns_events_for_direction_via_m2m(tmp_path, monkeypatch):
    """A mention tagged (via m2m) to a direction shows up in that direction's feed."""
    monkeypatch.setenv("ECHO_DB", f"sqlite:///{tmp_path / 'feed1.db'}")
    import sys
    for mod in list(sys.modules):
        if mod.startswith("radar.core.db") or mod == "radar.app":
            del sys.modules[mod]
    from fastapi.testclient import TestClient
    from radar.app import app
    with TestClient(app) as client:
        client.post("/auth/register", json={"email": "op@test.local", "password": "secret123"})
        tok = client.post("/auth/login", json={"email": "op@test.local", "password": "secret123"}).json()["token"]
        from radar.core.db import SessionLocal
        from radar.intel.models import IntelDirection, IntelMention, IntelMentionDirection
        from datetime import datetime, timezone
        with SessionLocal() as s:
            d = s.query(IntelDirection).filter_by(key="bryansk").first()
            m = IntelMention(direction_id=d.id, platform="telegram", post_id="feed-p1",
                            author="@ua", side="ua", text="обстріл під Брянськом",
                            created_at=datetime.now(timezone.utc))
            s.add(m); s.flush()
            s.add(IntelMentionDirection(mention_id=m.id, direction_id=d.id, match_type="source"))
            s.commit()
        r = client.get("/intel/feed?direction=bryansk",
                       headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data) == 1
        assert data[0]["author"] == "@ua"


def test_feed_side_filter_excludes_other_side(tmp_path, monkeypatch):
    monkeypatch.setenv("ECHO_DB", f"sqlite:///{tmp_path / 'feed2.db'}")
    import sys
    for mod in list(sys.modules):
        if mod.startswith("radar.core.db") or mod == "radar.app":
            del sys.modules[mod]
    from fastapi.testclient import TestClient
    from radar.app import app
    with TestClient(app) as client:
        client.post("/auth/register", json={"email": "op@test.local", "password": "secret123"})
        tok = client.post("/auth/login", json={"email": "op@test.local", "password": "secret123"}).json()["token"]
        from radar.core.db import SessionLocal
        from radar.intel.models import IntelDirection, IntelMention, IntelMentionDirection
        from datetime import datetime, timezone
        with SessionLocal() as s:
            d = s.query(IntelDirection).filter_by(key="bryansk").first()
            m = IntelMention(direction_id=d.id, platform="telegram", post_id="feed-p2",
                            author="@ua", side="ua", text="обстріл під Брянськом",
                            created_at=datetime.now(timezone.utc))
            s.add(m); s.flush()
            s.add(IntelMentionDirection(mention_id=m.id, direction_id=d.id, match_type="source"))
            s.commit()
        r = client.get("/intel/feed?direction=bryansk&side=ru",
                       headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200
        assert r.json() == []


def test_post_directions_creates_custom(tmp_path, monkeypatch):
    monkeypatch.setenv("ECHO_DB", f"sqlite:///{tmp_path / 'feed3.db'}")
    import sys
    for mod in list(sys.modules):
        if mod.startswith("radar.core.db") or mod == "radar.app":
            del sys.modules[mod]
    from fastapi.testclient import TestClient
    from radar.app import app
    with TestClient(app) as client:
        client.post("/auth/register", json={"email": "op@test.local", "password": "secret123"})
        tok = client.post("/auth/login", json={"email": "op@test.local", "password": "secret123"}).json()["token"]
        r = client.post("/intel/directions",
                        headers={"Authorization": f"Bearer {tok}",
                                 "Content-Type": "application/json"},
                        json={"key": "myline", "name": "Моя линия",
                              "geo_terms": ["термин1", "термин2"]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["key"] == "myline"
        assert body["kind"] == "custom"
        assert "термин1" in body["geo_terms"]


def test_post_directions_rejects_duplicate_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ECHO_DB", f"sqlite:///{tmp_path / 'feed4.db'}")
    import sys
    for mod in list(sys.modules):
        if mod.startswith("radar.core.db") or mod == "radar.app":
            del sys.modules[mod]
    from fastapi.testclient import TestClient
    from radar.app import app
    with TestClient(app) as client:
        client.post("/auth/register", json={"email": "op@test.local", "password": "secret123"})
        tok = client.post("/auth/login", json={"email": "op@test.local", "password": "secret123"}).json()["token"]
        r = client.post("/intel/directions",
                        headers={"Authorization": f"Bearer {tok}",
                                 "Content-Type": "application/json"},
                        json={"key": "bryansk", "name": "dup", "geo_terms": []})
        assert r.status_code == 409


def test_get_layout_returns_empty_default(tmp_path, monkeypatch):
    monkeypatch.setenv("ECHO_DB", f"sqlite:///{tmp_path / 'feed5.db'}")
    import sys
    for mod in list(sys.modules):
        if mod.startswith("radar.core.db") or mod == "radar.app":
            del sys.modules[mod]
    from fastapi.testclient import TestClient
    from radar.app import app
    with TestClient(app) as client:
        client.post("/auth/register", json={"email": "op@test.local", "password": "secret123"})
        tok = client.post("/auth/login", json={"email": "op@test.local", "password": "secret123"}).json()["token"]
        r = client.get("/intel/feed/layout",
                       headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200
        assert r.json()["direction_keys"] == []


def test_put_layout_saves_and_admin_only(tmp_path, monkeypatch):
    monkeypatch.setenv("ECHO_DB", f"sqlite:///{tmp_path / 'feed6.db'}")
    import sys
    for mod in list(sys.modules):
        if mod.startswith("radar.core.db") or mod == "radar.app":
            del sys.modules[mod]
    # Force re-import so the engine binds to the new ECHO_DB (avoid stale engine
    # from a prior test in the same process).
    import sys
    for mod in list(sys.modules):
        if mod.startswith("radar.core.db") or mod == "radar.app":
            del sys.modules[mod]
    from fastapi.testclient import TestClient
    from radar.app import app
    with TestClient(app) as client:
        client.post("/auth/register", json={"email": "op@test.local", "password": "secret123"})
        tok = client.post("/auth/login", json={"email": "op@test.local", "password": "secret123"}).json()["token"]
        from radar.core.db import SessionLocal
        from radar.models import User
        with SessionLocal() as s:
            u = s.query(User).filter_by(email="op@test.local").first()
            u.is_admin = True
            s.commit()
        r = client.put("/intel/feed/layout",
                       headers={"Authorization": f"Bearer {tok}",
                                "Content-Type": "application/json"},
                       json={"direction_keys": ["bryansk", "kharkiv"]})
        assert r.status_code == 200, r.text
        assert r.json()["direction_keys"] == ["bryansk", "kharkiv"]
        r2 = client.get("/intel/feed/layout",
                        headers={"Authorization": f"Bearer {tok}"})
        assert r2.json()["direction_keys"] == ["bryansk", "kharkiv"]


def test_put_layout_403_for_non_admin(tmp_path, monkeypatch):
    monkeypatch.setenv("ECHO_DB", f"sqlite:///{tmp_path / 'feed7.db'}")
    import sys
    for mod in list(sys.modules):
        if mod.startswith("radar.core.db") or mod == "radar.app":
            del sys.modules[mod]
    from fastapi.testclient import TestClient
    from radar.app import app
    with TestClient(app) as client:
        client.post("/auth/register", json={"email": "user@test.local", "password": "secret123"})
        tok = client.post("/auth/login", json={"email": "user@test.local", "password": "secret123"}).json()["token"]
        r = client.put("/intel/feed/layout",
                       headers={"Authorization": f"Bearer {tok}",
                                "Content-Type": "application/json"},
                       json={"direction_keys": ["bryansk"]})
        assert r.status_code == 403


def test_feed_excludes_hidden_and_radar(tmp_path, monkeypatch):
    """Колонка Ленты v2 не показывает soft-hidden спам и посты радар-источников."""
    monkeypatch.setenv("ECHO_DB", f"sqlite:///{tmp_path / 'feed7.db'}")
    import sys
    for mod in list(sys.modules):
        if mod.startswith("radar.core.db") or mod == "radar.app":
            del sys.modules[mod]
    from fastapi.testclient import TestClient
    from radar.app import app
    with TestClient(app) as client:
        client.post("/auth/register", json={"email": "op@test.local", "password": "secret123"})
        tok = client.post("/auth/login", json={"email": "op@test.local", "password": "secret123"}).json()["token"]
        from radar.core.db import SessionLocal
        from radar.intel.models import IntelDirection, IntelMention, IntelMentionDirection
        from datetime import datetime, timezone
        with SessionLocal() as s:
            d = s.query(IntelDirection).filter_by(key="bryansk").first()
            now = datetime.now(timezone.utc)
            rows = [
                IntelMention(direction_id=d.id, platform="telegram", post_id="feed-ok",
                             author="@ua", side="ua", text="обычный пост", created_at=now),
                IntelMention(direction_id=d.id, platform="telegram", post_id="feed-hid",
                             author="@ua", side="ua", text="скрытый спам", created_at=now,
                             hidden=True),
                IntelMention(direction_id=d.id, platform="telegram", post_id="feed-rad",
                             author="@radar", side="ua", text="радарный трек", created_at=now,
                             is_radar=True),
            ]
            s.add_all(rows); s.flush()
            for m in rows:
                s.add(IntelMentionDirection(mention_id=m.id, direction_id=d.id, match_type="source"))
            s.commit()
        r = client.get("/intel/feed?direction=bryansk",
                       headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200, r.text
        ids = {e["post_id"] for e in r.json()}
        assert ids == {"feed-ok"}


def test_stream_radar_param_splits_feeds(tmp_path, monkeypatch):
    """/intel/stream: по умолчанию — только обычные посты; radar=true — только радары."""
    monkeypatch.setenv("ECHO_DB", f"sqlite:///{tmp_path / 'feed8.db'}")
    import sys
    for mod in list(sys.modules):
        if mod.startswith("radar.core.db") or mod == "radar.app":
            del sys.modules[mod]
    from fastapi.testclient import TestClient
    from radar.app import app
    with TestClient(app) as client:
        client.post("/auth/register", json={"email": "op@test.local", "password": "secret123"})
        tok = client.post("/auth/login", json={"email": "op@test.local", "password": "secret123"}).json()["token"]
        from radar.core.db import SessionLocal
        from radar.intel.models import IntelDirection, IntelMention
        from datetime import datetime, timezone
        with SessionLocal() as s:
            d = s.query(IntelDirection).filter_by(key="bryansk").first()
            now = datetime.now(timezone.utc)
            s.add_all([
                IntelMention(direction_id=d.id, platform="telegram", post_id="s-plain",
                             author="@ua", side="ua", text="обычный пост", created_at=now),
                IntelMention(direction_id=d.id, platform="telegram", post_id="s-radar",
                             author="@radar", side="ua", text="радарный трек", created_at=now,
                             is_radar=True),
            ])
            s.commit()
        hdr = {"Authorization": f"Bearer {tok}"}
        plain = {e["post_id"] for e in client.get("/intel/stream", headers=hdr).json()}
        radar = {e["post_id"] for e in client.get("/intel/stream?radar=true", headers=hdr).json()}
        assert "s-plain" in plain and "s-radar" not in plain
        assert radar == {"s-radar"}


def test_sources_is_radar_roundtrip(tmp_path, monkeypatch):
    """POST /intel/sources принимает is_radar, PATCH переключает его."""
    monkeypatch.setenv("ECHO_DB", f"sqlite:///{tmp_path / 'feed9.db'}")
    import sys
    for mod in list(sys.modules):
        if mod.startswith("radar.core.db") or mod == "radar.app":
            del sys.modules[mod]
    from fastapi.testclient import TestClient
    from radar.app import app
    with TestClient(app) as client:
        client.post("/auth/register", json={"email": "op@test.local", "password": "secret123"})
        tok = client.post("/auth/login", json={"email": "op@test.local", "password": "secret123"}).json()["token"]
        hdr = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
        r = client.post("/intel/sources", headers=hdr,
                        json={"link": "@radar_channel", "side": "ua", "kind": "channel",
                              "is_radar": True})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["is_radar"] is True
        sid = body["id"]
        r2 = client.patch(f"/intel/sources/{sid}", headers=hdr, json={"is_radar": False})
        assert r2.status_code == 200
        assert r2.json()["is_radar"] is False
