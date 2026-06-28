# backend/tests/test_intel_feed_api.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime, timezone
import uuid

# Shared client/token — set up once per session. The real radar.app is bound
# to a single engine at import time, so we boot it once against an in-memory
# shared cache and seed once. Tests read against the seeded data.
_SETUP = None


def _bootstrap():
    global _SETUP
    if _SETUP is not None:
        return _SETUP
    os.environ["ECHO_DB"] = "sqlite://"
    from radar.core.db import init_db, SessionLocal
    init_db()
    from fastapi.testclient import TestClient
    from radar.app import app
    client = TestClient(app)
    client.post("/auth/register", json={"email": "op@test.local", "password": "secret123"})
    tok = client.post("/auth/login", json={"email": "op@test.local", "password": "secret123"}).json()["token"]

    from radar.models import User
    from radar.intel.models import IntelDirection, IntelMention, IntelMentionDirection
    with SessionLocal() as s:
        u = s.query(User).filter_by(email="op@test.local").first()
        u.is_admin = True
        s.commit()
        d1 = s.query(IntelDirection).filter_by(key="bryansk").first()
        d2 = s.query(IntelDirection).filter_by(key="kharkiv").first()
        existing = s.query(IntelMention).filter_by(platform="telegram", post_id="seed-p1").first()
        if existing is None:
            m = IntelMention(direction_id=d2.id, platform="telegram", post_id="seed-p1",
                            author="@ua", side="ua", text="обстріл під Брянськом",
                            created_at=datetime.now(timezone.utc))
            s.add(m); s.flush()
            s.add_all([
                IntelMentionDirection(mention_id=m.id, direction_id=d2.id, match_type="source"),
                IntelMentionDirection(mention_id=m.id, direction_id=d1.id, match_type="geo"),
            ])
            s.commit()
    _SETUP = (client, tok)
    return _SETUP


def test_feed_returns_events_for_direction_via_m2m():
    client, tok = _bootstrap()
    r = client.get("/intel/feed?direction=bryansk",
                   headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert any(e["author"] == "@ua" and e["match_type"] == "geo" for e in data)


def test_feed_side_filter_excludes_other_side():
    client, tok = _bootstrap()
    r = client.get("/intel/feed?direction=bryansk&side=ru",
                   headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert all(e["side"] != "ua" for e in r.json())


def test_get_directions_lists_kind_and_geo_terms():
    client, tok = _bootstrap()
    r = client.get("/intel/directions", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    keys = {d["key"]: d for d in r.json()}
    assert keys["bryansk"]["kind"] == "region"
    assert "брянск" in keys["bryansk"]["geo_terms"]


def test_post_directions_creates_custom():
    client, tok = _bootstrap()
    uniq = "myline" + uuid.uuid4().hex[:6]
    r = client.post("/intel/directions",
                    headers={"Authorization": f"Bearer {tok}"},
                    json={"key": uniq, "name": "Моя линия",
                          "geo_terms": ["термин1", "термин2"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["key"] == uniq
    assert body["kind"] == "custom"
    assert "термин1" in body["geo_terms"]


def test_post_directions_rejects_duplicate_key():
    client, tok = _bootstrap()
    r = client.post("/intel/directions",
                    headers={"Authorization": f"Bearer {tok}"},
                    json={"key": "bryansk", "name": "dup", "geo_terms": []})
    assert r.status_code == 409


def test_feed_stream_yields_events_tagged_with_direction():
    """The SSE generator yields at least one event tagged with the seeded
    bryansk direction. Drained synchronously under a thread timeout — full
    SSE over TestClient hangs on infinite streams."""
    import threading
    from radar.intel.api import _feed_stream_gen
    chunks = []
    error = []

    def drain():
        try:
            for chunk in _feed_stream_gen(["bryansk", "kharkiv"], None, 24):
                chunks.append(chunk)
                if any("data:" in c for c in chunks):
                    break
        except Exception as e:
            error.append(e)

    t = threading.Thread(target=drain, daemon=True)
    t.start()
    t.join(timeout=10)
    assert not error, error
    assert any("bryansk" in c for c in chunks), chunks


def test_get_layout_returns_empty_default():
    client, tok = _bootstrap()
    # Clear any layout saved by prior tests (in-memory shared DB).
    from radar.core.db import SessionLocal
    from radar.intel.models import IntelFeedLayout
    with SessionLocal() as s:
        s.query(IntelFeedLayout).delete()
        s.commit()
    r = client.get("/intel/feed/layout",
                   headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    body = r.json()
    assert body["direction_keys"] == []


def test_put_layout_saves_and_admin_only():
    client, tok = _bootstrap()
    r = client.put("/intel/feed/layout",
                   headers={"Authorization": f"Bearer {tok}"},
                   json={"direction_keys": ["bryansk", "kharkiv"]})
    assert r.status_code == 200
    assert r.json()["direction_keys"] == ["bryansk", "kharkiv"]
    r2 = client.get("/intel/feed/layout",
                    headers={"Authorization": f"Bearer {tok}"})
    assert r2.json()["direction_keys"] == ["bryansk", "kharkiv"]


def test_put_layout_403_for_non_admin():
    # Register a second user with no admin flag.
    client, _ = _bootstrap()
    client.post("/auth/register", json={"email": "user@test.local", "password": "secret123"})
    tok = client.post("/auth/login", json={"email": "user@test.local", "password": "secret123"}).json()["token"]
    r = client.put("/intel/feed/layout",
                   headers={"Authorization": f"Bearer {tok}"},
                   json={"direction_keys": ["bryansk"]})
    assert r.status_code == 403
