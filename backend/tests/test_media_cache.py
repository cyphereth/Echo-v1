"""media_cache: дисковый кэш превью. Попадание не трогает провайдер; промах — качает."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class _Prov:
    def __init__(self, result):
        self.result = result
        self.calls = 0
    def download_media_preview(self, handle, msg_id, kind):
        self.calls += 1
        return self.result


def test_miss_fetches_and_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_CACHE_DIR", str(tmp_path))
    import importlib
    from radar.intel import media_cache
    importlib.reload(media_cache)
    prov = _Prov((b"JPEGBYTES", "image/jpeg"))
    out = media_cache.get_or_fetch(prov, "chan/42", "@chan", 42, "photo")
    assert out is not None
    path, mime = out
    assert path.exists() and path.read_bytes() == b"JPEGBYTES"
    assert mime == "image/jpeg"
    assert prov.calls == 1


def test_hit_does_not_call_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_CACHE_DIR", str(tmp_path))
    import importlib
    from radar.intel import media_cache
    importlib.reload(media_cache)
    prov = _Prov((b"JPEGBYTES", "image/jpeg"))
    media_cache.get_or_fetch(prov, "chan/42", "@chan", 42, "photo")  # warm
    prov2 = _Prov((b"OTHER", "image/jpeg"))
    out = media_cache.get_or_fetch(prov2, "chan/42", "@chan", 42, "photo")
    assert out is not None and out[0].read_bytes() == b"JPEGBYTES"
    assert prov2.calls == 0, "кэш-хит не должен звать провайдер"


def test_none_when_no_preview(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_CACHE_DIR", str(tmp_path))
    import importlib
    from radar.intel import media_cache
    importlib.reload(media_cache)
    prov = _Prov(None)
    assert media_cache.get_or_fetch(prov, "chan/9", "@chan", 9, "photo") is None
    assert prov.calls == 1
