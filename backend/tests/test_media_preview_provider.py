"""download_media_preview: скачивает превью-thumbnail через Telethon-клиент."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from types import SimpleNamespace


class _FakeClient:
    """Минимальный фейк Telethon-клиента: get_entity, get_messages, download_media."""
    def __init__(self, msg, blob=b"JPEGBYTES"):
        self._msg = msg
        self._blob = blob
        self.calls = []
    def get_entity(self, h):
        self.calls.append(("get_entity", h)); return SimpleNamespace(id=1)
    def get_messages(self, entity, ids=None):
        self.calls.append(("get_messages", ids)); return [self._msg]
    def download_media(self, msg, file=None, thumb=None):
        self.calls.append(("download_media", thumb)); return self._blob


def _provider(client):
    from radar.core.providers.telegram import TelegramProvider
    p = TelegramProvider(client=client)
    return p


def test_photo_returns_bytes_and_mime():
    msg = SimpleNamespace(id=42, photo=object(), video=None, document=None)
    client = _FakeClient(msg)
    p = _provider(client)
    out = p.download_media_preview("@chan", 42, "photo")
    assert out is not None
    data, mime = out
    assert data == b"JPEGBYTES"
    assert mime == "image/jpeg"
    assert any(c[0] == "download_media" for c in client.calls)


def test_file_kind_returns_none_without_download():
    msg = SimpleNamespace(id=7, photo=None, video=None, document=object())
    client = _FakeClient(msg)
    p = _provider(client)
    assert p.download_media_preview("@chan", 7, "file") is None
    assert not any(c[0] == "download_media" for c in client.calls)


def test_missing_message_returns_none():
    class Empty(_FakeClient):
        def get_messages(self, entity, ids=None): return []
    p = _provider(Empty(None))
    assert p.download_media_preview("@chan", 99, "photo") is None
