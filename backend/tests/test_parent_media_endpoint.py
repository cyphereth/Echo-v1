"""GET /intel/mention/{id}/parent-media/{tg_msg_id} + media в reply_chain."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("ECHO_DB", f"sqlite:///{tmp_path/'pm.db'}")
    monkeypatch.setenv("MEDIA_CACHE_DIR", str(tmp_path / "cache"))
    from fastapi.testclient import TestClient
    from radar.app import app
    c = TestClient(app); c.__enter__()
    c.post("/auth/register", json={"email": "pm@test.local", "password": "secret123"})
    tok = c.post("/auth/login", json={"email": "pm@test.local", "password": "secret123"}).json()["token"]
    return c, {"Authorization": f"Bearer {tok}"}


def _setup_thread():
    from radar.core.db import get_session
    from radar.intel.models import IntelDirection, IntelMention, IntelThreadContext
    s = get_session()
    direction = IntelDirection(key="test-dir", name="Test Direction")
    s.add(direction); s.flush()
    reply = IntelMention(platform="telegram", post_id="chan/11", author="@chan", side="ru",
                         text="ответ", created_at=datetime.now(timezone.utc), reply_to_tg_id="10",
                         direction_id=direction.id)
    s.add(reply); s.flush()
    s.add(IntelThreadContext(mention_id=reply.id, tg_msg_id="10", role="parent", depth=1,
                             author="@chan", text="родитель", created_at=datetime.now(timezone.utc),
                             media="photo"))
    s.commit(); mid = reply.id; s.close()
    return mid


def test_parent_media_200(tmp_path, monkeypatch):
    c, h = _client(tmp_path, monkeypatch)
    mid = _setup_thread()
    import radar.intel.api as api
    monkeypatch.setattr(api, "_get_tg_provider", lambda: object())
    def fake(provider, post_id, handle, msg_id, kind):
        import pathlib
        p = pathlib.Path(os.environ["MEDIA_CACHE_DIR"]); p.mkdir(parents=True, exist_ok=True)
        f = p / "p.jpg"; f.write_bytes(b"POSTER"); return (f, "image/jpeg")
    monkeypatch.setattr(api.media_cache, "get_or_fetch", fake)
    r = c.get(f"/intel/mention/{mid}/parent-media/10", headers=h)
    assert r.status_code == 200 and r.content == b"POSTER"


def test_parent_media_404_unknown_parent(tmp_path, monkeypatch):
    c, h = _client(tmp_path, monkeypatch)
    mid = _setup_thread()
    assert c.get(f"/intel/mention/{mid}/parent-media/999", headers=h).status_code == 404
