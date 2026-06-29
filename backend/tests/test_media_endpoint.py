"""GET /intel/mention/{id}/media — auth, 404 без медиа, 503 на FloodWait, 200 при успехе."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("ECHO_DB", f"sqlite:///{tmp_path/'m.db'}")
    monkeypatch.setenv("MEDIA_CACHE_DIR", str(tmp_path / "cache"))
    from fastapi.testclient import TestClient
    from radar.app import app
    c = TestClient(app)
    c.__enter__()
    c.post("/auth/register", json={"email": "m@test.local", "password": "secret123"})
    tok = c.post("/auth/login", json={"email": "m@test.local", "password": "secret123"}).json()["token"]
    return c, {"Authorization": f"Bearer {tok}"}


def _add_mention(media):
    from radar.core.db import get_session
    from radar.intel.models import IntelMention, IntelDirection
    s = get_session()
    d = s.query(IntelDirection).first()
    if d is None:
        d = IntelDirection(key="kursk", name="Курское"); s.add(d); s.flush()
    m = IntelMention(direction_id=d.id, platform="telegram", post_id="chan/42", author="@chan",
                     side="ru", text="t", created_at=datetime.now(timezone.utc), media=media)
    s.add(m); s.commit(); mid = m.id; s.close()
    return mid


def test_requires_auth(tmp_path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch)
    assert c.get("/intel/mention/1/media").status_code in (401, 403)


def test_404_when_no_media(tmp_path, monkeypatch):
    c, h = _client(tmp_path, monkeypatch)
    mid = _add_mention(None)
    assert c.get(f"/intel/mention/{mid}/media", headers=h).status_code == 404


def test_200_on_success(tmp_path, monkeypatch):
    c, h = _client(tmp_path, monkeypatch)
    mid = _add_mention("photo")
    import radar.intel.api as api
    monkeypatch.setattr(api, "_get_tg_provider", lambda: object())
    def fake_get_or_fetch(provider, post_id, handle, msg_id, kind):
        import pathlib
        p = pathlib.Path(os.environ["MEDIA_CACHE_DIR"]); p.mkdir(parents=True, exist_ok=True)
        f = p / "x.jpg"; f.write_bytes(b"JPEGBYTES")
        return (f, "image/jpeg")
    monkeypatch.setattr(api.media_cache, "get_or_fetch", fake_get_or_fetch)
    r = c.get(f"/intel/mention/{mid}/media", headers=h)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/jpeg")
    assert r.content == b"JPEGBYTES"


def test_503_on_floodwait(tmp_path, monkeypatch):
    c, h = _client(tmp_path, monkeypatch)
    mid = _add_mention("photo")
    import radar.intel.api as api
    from radar.core.providers.telegram import TelegramFloodWait
    monkeypatch.setattr(api, "_get_tg_provider", lambda: object())
    def boom(*a, **k): raise TelegramFloodWait(60)
    monkeypatch.setattr(api.media_cache, "get_or_fetch", boom)
    assert c.get(f"/intel/mention/{mid}/media", headers=h).status_code == 503
