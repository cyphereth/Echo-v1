"""Дисковый кэш превью медиа. Скачивает thumbnail через провайдер один раз на post_id,
затем отдаёт путь из кэша. Каталог — MEDIA_CACHE_DIR (env), по умолчанию backend/.media_cache/."""
from __future__ import annotations
import os
import re
import pathlib

_DEFAULT_DIR = pathlib.Path(__file__).resolve().parents[2] / ".media_cache"
CACHE_DIR = pathlib.Path(os.getenv("MEDIA_CACHE_DIR", str(_DEFAULT_DIR)))

_MIME_EXT = {"image/jpeg": ".jpg", "image/png": ".png"}
_SANITIZE = re.compile(r"[^A-Za-z0-9_.-]")


def _ext(mime: str) -> str:
    return _MIME_EXT.get(mime, ".bin")


def cache_path(post_id: str, mime: str = "image/jpeg") -> pathlib.Path:
    """Детерминированный путь файла кэша для post_id (слэши/спецсимволы → '_')."""
    safe = _SANITIZE.sub("_", post_id)
    return CACHE_DIR / f"{safe}{_ext(mime)}"


def get_or_fetch(provider, post_id: str, handle: str, msg_id: int, kind: str):
    """(path, mime) из кэша или после скачивания через провайдер; None если превью нет.
    Бросает TelegramFloodWait наружу (провайдер пробрасывает)."""
    # Попадание: любой ранее записанный файл для этого post_id.
    for mime, ext in _MIME_EXT.items():
        p = cache_path(post_id, mime)
        if p.exists():
            return (p, mime)
    result = provider.download_media_preview(handle, msg_id, kind)
    if result is None:
        return None
    data, mime = result
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = cache_path(post_id, mime)
    p.write_bytes(data)
    return (p, mime)
