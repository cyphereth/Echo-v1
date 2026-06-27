# Hover-предпросмотр медиа в ленте intel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** При наведении на иконку медиа в ленте intel показывать превью фото / постер видео (своё вложение и медиа родителя треда), не уходя в Telegram.

**Architecture:** Ленивое скачивание превью через Telethon по требованию + дисковый кэш + два авторизованных байт-эндпоинта; фронт грузит медиа через `fetch` с Bearer-заголовком, подставляет `objectURL` в `<img>` внутри hover-поповера. Тип медиа родителя добавляется в `intel_thread_context`.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, SQLite, Telethon, pytest + fastapi.testclient; React (echo-app), CSS-modules.

## Global Constraints

- Ответы пользователю — на русском.
- Бэкенд перезапускает АССИСТЕНТ через `launchctl kickstart -k gui/$(id -u)/com.echo.backend`, НЕ пользователь.
- Сообщения коммитов заканчиваются строкой: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Работаем в текущем каталоге (без worktree). Интерпретатор — `python3`. Ветка: `feat/intel-media-preview`.
- Python-тесты: `python3 -m pytest` из каталога `backend/`.
- Превью — постер/сжатый размер, НЕ оригинал; видео → thumbnail (`image/jpeg`).
- Эндпоинты авторизуются `Depends(current_user)` (Bearer-заголовок); фронт тянет через `fetch`+blob (НЕ токен в URL).
- Провайдер достаётся в эндпоинтах через `radar.brand.api._get_tg_provider()` (синглог; может вернуть `None`).
- `media` в БД — `"photo"|"video"|"file"|None`. Превью только для `photo`/`video`.
- FloodWait не валит ленту: эндпоинт → 503.

---

### Task 1: Провайдер — `download_media_preview`

**Files:**
- Modify: `backend/radar/core/providers/telegram.py` (добавить метод в класс `TelegramProvider`, рядом с `fetch_thread_context`)
- Test: `backend/tests/test_media_preview_provider.py`

**Interfaces:**
- Produces: `TelegramProvider.download_media_preview(self, handle: str, msg_id: int, kind: str) -> tuple[bytes, str] | None` — возвращает `(bytes, mime)` превью (`image/jpeg`) для `photo`/`video`, иначе `None`. Бросает `TelegramFloodWait`.

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_media_preview_provider.py`:

```python
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
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd backend && python3 -m pytest tests/test_media_preview_provider.py -v`
Expected: FAIL — `AttributeError: 'TelegramProvider' object has no attribute 'download_media_preview'`.

- [ ] **Step 3: Реализовать метод**

В `backend/radar/core/providers/telegram.py`, в классе `TelegramProvider`, сразу после метода `fetch_thread_context` добавить:

```python
    def download_media_preview(self, handle: str, msg_id: int, kind: str) -> "tuple[bytes, str] | None":
        """Скачать превью-thumbnail медиа сообщения. (bytes, mime) или None.

        photo/video → наибольший thumbnail (постер), mime image/jpeg. file и отсутствие
        превью → None. Бросает TelegramFloodWait (как fetch_thread_context)."""
        if kind not in ("photo", "video"):
            return None
        h = handle if (not handle or handle.startswith("@") or handle.startswith("#")) else f"@{handle}"
        try:
            entity = self._await(self._client.get_entity(int(h[1:]) if h.startswith("#") else h))
            msgs = self._await(self._client.get_messages(entity, ids=[int(msg_id)]))
        except TelegramFloodWait:
            raise
        except Exception as e:
            log.warning("download_media_preview: lookup failed (%s/%s): %s", h, msg_id, type(e).__name__)
            return None
        msg = msgs[0] if msgs else None
        if msg is None:
            return None
        try:
            # thumb=-1 → наибольший доступный thumbnail (постер), не оригинал.
            data = self._await(self._client.download_media(msg, file=bytes, thumb=-1))
        except TelegramFloodWait:
            raise
        except Exception as e:
            log.warning("download_media_preview: download failed (%s/%s): %s", h, msg_id, type(e).__name__)
            return None
        if not data:
            return None
        return (data, "image/jpeg")
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd backend && python3 -m pytest tests/test_media_preview_provider.py -v`
Expected: PASS (3 passed).

Примечание: `TelegramProvider(client=...)` уже поддерживается (см. конструктор — ветка с переданным `client`). `_await` при синхронном фейке вернёт значение как есть (проверить: если `_await` ожидает awaitable — фейк возвращает обычные значения; если тест упадёт на `_await`, обернуть возвраты фейка не нужно — `_await` в коде проекта обрабатывает уже-готовые значения. Если всё же падает, реализатор адаптирует фейк, добавив `async def` методы и оставив поведение эквивалентным).

- [ ] **Step 5: Коммит**

```bash
git add backend/radar/core/providers/telegram.py backend/tests/test_media_preview_provider.py
git commit -m "$(cat <<'EOF'
feat(intel): download_media_preview — thumbnail-постер медиа

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Дисковый кэш превью

**Files:**
- Create: `backend/radar/intel/media_cache.py`
- Test: `backend/tests/test_media_cache.py`
- Modify: `.gitignore` (добавить `backend/.media_cache/`)

**Interfaces:**
- Consumes: `provider.download_media_preview(handle, msg_id, kind) -> tuple[bytes, str] | None` (Task 1).
- Produces:
  - `cache_path(post_id: str, mime: str = "image/jpeg") -> pathlib.Path` — детерминированный путь файла.
  - `get_or_fetch(provider, post_id: str, handle: str, msg_id: int, kind: str) -> tuple[pathlib.Path, str] | None` — `(path, mime)` из кэша или после скачивания; `None` если превью нет. Бросает `TelegramFloodWait` наружу.

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_media_cache.py`:

```python
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
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd backend && python3 -m pytest tests/test_media_cache.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'radar.intel.media_cache'`.

- [ ] **Step 3: Реализовать модуль**

Создать `backend/radar/intel/media_cache.py`:

```python
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
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd backend && python3 -m pytest tests/test_media_cache.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Добавить кэш в .gitignore**

В корневой `.gitignore` добавить строку (если её нет):

```
backend/.media_cache/
```

- [ ] **Step 6: Коммит**

```bash
git add backend/radar/intel/media_cache.py backend/tests/test_media_cache.py .gitignore
git commit -m "$(cat <<'EOF'
feat(intel): дисковый кэш превью медиа (media_cache)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Эндпоинт превью своего вложения

**Files:**
- Modify: `backend/radar/intel/api.py` (новый GET-маршрут; импорт `FileResponse`, `media_cache`, `_get_tg_provider`, `_handle_for`)
- Test: `backend/tests/test_media_endpoint.py`

**Interfaces:**
- Consumes: `media_cache.get_or_fetch` (Task 2); `radar.brand.api._get_tg_provider()`; `context_pass._handle_for(mention)`; `current_user` dependency.
- Produces: `GET /intel/mention/{mention_id}/media` → `FileResponse` (200), либо 401/404/503.

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_media_endpoint.py`:

```python
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
    from radar.intel.models import IntelMention
    s = get_session()
    m = IntelMention(platform="telegram", post_id="chan/42", author="@chan", side="ru",
                     text="t", created_at=datetime.now(timezone.utc), media=media)
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
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd backend && python3 -m pytest tests/test_media_endpoint.py -v`
Expected: FAIL — 404/500 на маршрут, которого ещё нет (или AttributeError на `api.media_cache`).

- [ ] **Step 3: Реализовать эндпоинт**

В `backend/radar/intel/api.py`:

1. Добавить импорты (рядом с существующими):

```python
from fastapi.responses import StreamingResponse, FileResponse
from . import media_cache
from .context_pass import _handle_for, _parse_handle_and_msg_id
```

2. Добавить хелпер и маршрут (в конце файла, среди других `@router.get`):

```python
def _preview_or_error(provider, post_id: str, handle: str, msg_id: int, kind: str):
    """Общая обвязка кэша+провайдера для media-эндпоинтов. Возвращает FileResponse или
    HTTPException-совместимый ответ через raise."""
    from .media_cache import get_or_fetch
    from ..core.providers.telegram import TelegramFloodWait
    if kind not in ("photo", "video"):
        raise HTTPException(404, "no previewable media")
    if provider is None:
        raise HTTPException(503, "provider unavailable")
    try:
        res = media_cache.get_or_fetch(provider, post_id, handle, msg_id, kind)
    except TelegramFloodWait:
        raise HTTPException(503, "rate-limited, try later")
    if res is None:
        raise HTTPException(404, "preview unavailable")
    path, mime = res
    return FileResponse(str(path), media_type=mime,
                        headers={"Cache-Control": "private, max-age=86400"})


@router.get("/intel/mention/{mention_id}/media")
def intel_mention_media(
    mention_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    """Превью фото/постер видео, прикреплённого к самому упоминанию."""
    from .brand_provider_shim import get_tg_provider  # see step 3.3
    m = session.get(IntelMention, mention_id)
    if m is None:
        raise HTTPException(404, "mention not found")
    handle = _handle_for(m)
    _, msg_id = _parse_handle_and_msg_id(m.post_id)
    return _preview_or_error(get_tg_provider(), m.post_id, handle, int(msg_id), m.media or "")
```

3. Вместо несуществующего shim — импортировать провайдер-аксессор напрямую. Заменить строку `from .brand_provider_shim import get_tg_provider` на:

```python
    from ..brand.api import _get_tg_provider as get_tg_provider
```

(Импорт внутри функции — чтобы избежать循环-импорта на уровне модуля; тест мокает `api._get_tg_provider`, поэтому также добавить модульный алиас: в начало `api.py`, после других импортов, добавить `from ..brand.api import _get_tg_provider`. Тогда тестовый `monkeypatch.setattr(api, "_get_tg_provider", ...)` работает, а в эндпоинте использовать `_get_tg_provider()` напрямую, без локального импорта.)

Итоговый эндпоинт (используем модульный `_get_tg_provider`):

```python
@router.get("/intel/mention/{mention_id}/media")
def intel_mention_media(
    mention_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    """Превью фото/постер видео, прикреплённого к самому упоминанию."""
    m = session.get(IntelMention, mention_id)
    if m is None:
        raise HTTPException(404, "mention not found")
    handle = _handle_for(m)
    _, msg_id = _parse_handle_and_msg_id(m.post_id)
    return _preview_or_error(_get_tg_provider(), m.post_id, handle, int(msg_id), m.media or "")
```

И добавить в начало `api.py` (после `from .spam_filter import ...`):

```python
from ..brand.api import _get_tg_provider
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd backend && python3 -m pytest tests/test_media_endpoint.py -v`
Expected: PASS (4 passed). Если падает циклический импорт `from ..brand.api import _get_tg_provider` на уровне модуля — перенести импорт внутрь эндпоинта и `_preview_or_error`, а в тесте мокать через `monkeypatch.setattr` объект, на который реально ссылается код (реализатор выбирает рабочий вариант, сохраняя контракт теста: мок провайдера и `media_cache.get_or_fetch`).

- [ ] **Step 5: Коммит**

```bash
git add backend/radar/intel/api.py backend/tests/test_media_endpoint.py
git commit -m "$(cat <<'EOF'
feat(intel): GET /intel/mention/{id}/media — превью своего вложения

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Тип медиа родителя в треде (модель + миграция + заполнение)

**Files:**
- Modify: `backend/radar/intel/models.py` (поле `media` в `IntelThreadContext`)
- Modify: `backend/radar/core/db.py` (`_MIGRATIONS`)
- Modify: `backend/radar/core/providers/telegram.py` (`fetch_thread_context` → `media` в parents)
- Modify: `backend/radar/intel/context_pass.py` (`enrich_context` и `_resolve_locally` пишут `media`)
- Test: `backend/tests/test_thread_media.py`

**Interfaces:**
- Consumes: `_media_kind` (существующий, в telegram.py).
- Produces: `IntelThreadContext.media: Optional[str]`; `fetch_thread_context(...)["parents"][i]["media"]`; parent-строки контекста несут `media`.

- [ ] **Step 1: Написать падающие тесты**

Создать `backend/tests/test_thread_media.py`:

```python
"""Тред несёт тип медиа родителя: модель, fetch_thread_context, _resolve_locally."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone
from types import SimpleNamespace


def _sess():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from radar.models import Base
    import radar.intel.models  # noqa
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    return Session(eng)


def _m(s, post_id, reply_to=None, media=None):
    from radar.intel.models import IntelMention
    m = IntelMention(platform="telegram", post_id=post_id, author="@u", side="ru",
                     text="t", created_at=datetime.now(timezone.utc),
                     reply_to_tg_id=reply_to, media=media)
    s.add(m); s.flush()
    return m


def test_thread_context_has_media_column():
    from radar.intel.models import IntelThreadContext
    ctx = IntelThreadContext(mention_id=1, tg_msg_id="5", role="parent", depth=1,
                             author="@a", text="x", created_at=datetime.now(timezone.utc),
                             media="photo")
    assert ctx.media == "photo"


def test_resolve_locally_copies_parent_media():
    from radar.intel import passes  # noqa регистрирует модели
    from radar.intel.context_pass import _resolve_locally
    from radar.intel.models import IntelThreadContext
    s = _sess()
    root = _m(s, "ns/10", reply_to=None, media="photo")     # родитель с фото
    reply = _m(s, "ns/11", reply_to="10")
    s.commit()
    assert _resolve_locally(s, reply) is True
    row = s.query(IntelThreadContext).filter_by(mention_id=reply.id, tg_msg_id="10").one()
    assert row.media == "photo"


def test_fetch_thread_context_includes_media():
    from radar.core.providers.telegram import TelegramProvider
    # сообщение-родитель с фото
    parent = SimpleNamespace(id=10, message="родитель", date=datetime.now(timezone.utc),
                             sender=None, sender_id=1, reply_to_msg_id=None,
                             photo=object(), video=None, document=None)
    class Client:
        def get_entity(self, h): return SimpleNamespace(id=1)
        def get_messages(self, entity, ids=None, **kw):
            if ids: return [parent]
            return []
    p = TelegramProvider(client=Client())
    out = p.fetch_thread_context("@chan", reply_to_tg_id="10", current_tg_id="11")
    assert out["parents"], "ожидался родитель"
    assert out["parents"][0]["media"] == "photo"
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd backend && python3 -m pytest tests/test_thread_media.py -v`
Expected: FAIL — у `IntelThreadContext` нет `media`; в parents нет ключа `media`.

- [ ] **Step 3: Добавить поле в модель**

В `backend/radar/intel/models.py`, в классе `IntelThreadContext`, после строки `text: ...` добавить:

```python
    media:      Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # тип вложения родителя: photo|video|file
```

(Убедиться, что `Optional` импортирован в файле — он уже используется для `IntelMention.media`.)

- [ ] **Step 4: Добавить миграцию**

В `backend/radar/core/db.py` в словарь `_MIGRATIONS` добавить запись:

```python
    "intel_thread_context": {
        "media": "TEXT",
    },
```

- [ ] **Step 5: `fetch_thread_context` возвращает media родителей**

В `backend/radar/core/providers/telegram.py`, в `fetch_thread_context`, в блоке формирования элемента `parents.append({...})` добавить ключ `media`:

```python
            parents.append({
                "tg_msg_id": str(msg.id),
                "depth": depth,
                "author": _author(msg),
                "text": getattr(msg, "message", "") or "",
                "created_at": msg.date,
                "media": _media_kind(msg),
            })
```

- [ ] **Step 6: `context_pass` пишет media**

В `backend/radar/intel/context_pass.py`:

В `_resolve_locally`, где создаётся `IntelThreadContext(... role="parent" ...)` для локальных предков, добавить `media=anc.media`:

```python
        ctx = IntelThreadContext(
            mention_id=mention.id,
            tg_msg_id=anc_tg_id,
            role="parent",
            depth=d,
            author=anc.author or "",
            text=anc.text or "",
            created_at=anc.created_at,
            media=anc.media,
        )
```

В `enrich_context`, где создаётся `IntelThreadContext` для сетевых `parents`, добавить `media=p.get("media")`:

```python
            ctx = IntelThreadContext(
                mention_id=mention.id,
                tg_msg_id=p["tg_msg_id"],
                role="parent",
                depth=p["depth"],
                author=p.get("author", ""),
                text=p.get("text", ""),
                created_at=p["created_at"],
                media=p.get("media"),
            )
```

- [ ] **Step 7: Запустить — убедиться, что проходит**

Run: `cd backend && python3 -m pytest tests/test_thread_media.py tests/test_intel_hide.py tests/test_context_pass_partial.py -v`
Expected: PASS (новые + регрессия треда зелёные).

- [ ] **Step 8: Коммит**

```bash
git add backend/radar/intel/models.py backend/radar/core/db.py backend/radar/core/providers/telegram.py backend/radar/intel/context_pass.py backend/tests/test_thread_media.py
git commit -m "$(cat <<'EOF'
feat(intel): тип медиа родителя в треде (модель+миграция+заполнение)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Эндпоинт превью медиа родителя + media в thread-ответе

**Files:**
- Modify: `backend/radar/intel/api.py` (новый GET + `media` в `reply_chain`)
- Test: `backend/tests/test_parent_media_endpoint.py`

**Interfaces:**
- Consumes: `_preview_or_error` (Task 3), `IntelThreadContext` (с `media` из Task 4), `_handle_for`, `_parent_post_id`.
- Produces: `GET /intel/mention/{mention_id}/parent-media/{tg_msg_id}` → FileResponse/401/404/503; `reply_chain[i]["media"]` в thread-ответе.

- [ ] **Step 1: Написать падающий тест**

Создать `backend/tests/test_parent_media_endpoint.py`:

```python
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
    from radar.intel.models import IntelMention, IntelThreadContext
    s = get_session()
    reply = IntelMention(platform="telegram", post_id="chan/11", author="@chan", side="ru",
                         text="ответ", created_at=datetime.now(timezone.utc), reply_to_tg_id="10")
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
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `cd backend && python3 -m pytest tests/test_parent_media_endpoint.py -v`
Expected: FAIL — маршрута нет.

- [ ] **Step 3: Реализовать эндпоинт + media в reply_chain**

В `backend/radar/intel/api.py`:

1. Новый маршрут (рядом с `intel_mention_media`):

```python
@router.get("/intel/mention/{mention_id}/parent-media/{tg_msg_id}")
def intel_parent_media(
    mention_id: int,
    tg_msg_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    """Превью медиа родительского сообщения треда (tg_msg_id) этого упоминания."""
    m = session.get(IntelMention, mention_id)
    if m is None:
        raise HTTPException(404, "mention not found")
    ctx = (session.query(IntelThreadContext)
           .filter(IntelThreadContext.mention_id == mention_id,
                   IntelThreadContext.tg_msg_id == tg_msg_id,
                   IntelThreadContext.role == "parent")
           .first())
    if ctx is None:
        raise HTTPException(404, "parent not in thread")
    handle = _handle_for(m)
    # post_id родителя в namespace упоминания (composite для чатов / bare для каналов)
    from .context_pass import _parent_post_id
    parent_post_id = _parent_post_id(m, tg_msg_id)
    return _preview_or_error(_get_tg_provider(), parent_post_id, handle, int(tg_msg_id), ctx.media or "")
```

2. В функции, которая строит `reply_chain` (где формируется список dict'ов с `tg_msg_id/depth/author/text/created_at`), добавить ключ `media`:

```python
    reply_chain = sorted(
        [{"tg_msg_id": r.tg_msg_id, "depth": r.depth,
          "author": r.author, "text": r.text,
          "media": r.media,
          "created_at": aggregate._aware(r.created_at).isoformat()}
         for r in rows if r.role == "parent"],
        key=lambda x: x["depth"],
        reverse=True,
    )
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `cd backend && python3 -m pytest tests/test_parent_media_endpoint.py tests/test_intel_thread_context.py -v`
Expected: PASS (новые + существующий thread-context тест зелёные).

- [ ] **Step 5: Коммит**

```bash
git add backend/radar/intel/api.py backend/tests/test_parent_media_endpoint.py
git commit -m "$(cat <<'EOF'
feat(intel): эндпоинт превью медиа родителя + media в reply_chain

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Фронт — компонент MediaPreview + интеграция

**Files:**
- Create: `echo-app/src/features/intel/components/MediaPreview.jsx`
- Modify: `echo-app/src/features/intel/components/IntelHome.jsx` (~263-269 — заменить статичный span иконки)
- Modify: `echo-app/src/features/intel/components/ThreadContext.jsx` (иконка+превью для parent с media)
- Modify: `echo-app/src/features/intel/intel.module.css` (стили поповера)

**Interfaces:**
- Consumes: эндпоинты Task 3/5; `getToken` из `../../core/api/client`.
- Produces: `<MediaPreview kind url label />` React-компонент.

Примечание: автотест-раннера для JS в проекте нет — проверка ручная (Step 4). Реализатор НЕ добавляет JS-тест-фреймворк (вне области).

- [ ] **Step 1: Создать компонент**

Создать `echo-app/src/features/intel/components/MediaPreview.jsx`:

```jsx
import { useState, useRef, useCallback, useEffect } from 'react';
import { getToken } from '../../../core/api/client';

const ICON = { photo: '📷', video: '🎬', file: '📎' };
const TITLE = { photo: 'Прикреплено фото', video: 'Прикреплено видео', file: 'Прикреплён файл' };
const HOVER_DELAY = 200;

// Hover-превью медиа: лениво тянет картинку через fetch+Bearer, кладёт objectURL в <img>.
// Для file — просто иконка без поповера.
export default function MediaPreview({ kind, url, label }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState('idle'); // idle | loading | ready | error
  const [src, setSrc] = useState(null);
  const timer = useRef(null);
  const objUrl = useRef(null);

  const load = useCallback(async () => {
    if (state === 'ready' || state === 'loading') return;
    setState('loading');
    try {
      const token = getToken();
      const res = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
      if (!res.ok) throw new Error(String(res.status));
      const blob = await res.blob();
      objUrl.current = URL.createObjectURL(blob);
      setSrc(objUrl.current);
      setState('ready');
    } catch {
      setState('error');
    }
  }, [url, state]);

  const onEnter = () => {
    if (kind === 'file') return;
    timer.current = setTimeout(() => { setOpen(true); load(); }, HOVER_DELAY);
  };
  const onLeave = () => { clearTimeout(timer.current); setOpen(false); };

  useEffect(() => () => {
    clearTimeout(timer.current);
    if (objUrl.current) URL.revokeObjectURL(objUrl.current);
  }, []);

  return (
    <span style={{ position: 'relative', marginRight: 4, cursor: kind === 'file' ? 'default' : 'zoom-in' }}
          title={TITLE[kind] || ''} onMouseEnter={onEnter} onMouseLeave={onLeave}>
      {ICON[kind] || '📎'}
      {open && kind !== 'file' && (
        <span style={{
          position: 'absolute', bottom: '120%', left: 0, zIndex: 50,
          background: '#0b0f14', border: '1px solid #1e2a36', borderRadius: 8,
          padding: 4, minWidth: 160, minHeight: 90, boxShadow: '0 8px 24px rgba(0,0,0,.5)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          {state === 'loading' && <span style={{ fontSize: 11, color: '#7c8b99' }}>загрузка…</span>}
          {state === 'error' && <span style={{ fontSize: 11, color: '#7c8b99' }}>превью недоступно ↗ TG</span>}
          {state === 'ready' && (
            <span style={{ position: 'relative', display: 'inline-flex' }}>
              <img src={src} alt={label || ''} style={{ maxWidth: 260, maxHeight: 200, borderRadius: 6, display: 'block' }} />
              {kind === 'video' && (
                <span style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
                               justifyContent: 'center', fontSize: 28, color: '#fff', textShadow: '0 2px 6px #000' }}>▶</span>
              )}
            </span>
          )}
        </span>
      )}
    </span>
  );
}
```

- [ ] **Step 2: Интегрировать в IntelHome.jsx**

В `echo-app/src/features/intel/components/IntelHome.jsx` импортировать сверху:

```jsx
import MediaPreview from './MediaPreview';
```

Заменить блок (строки ~263-269):

```jsx
                    {e.media && (
                      <span title={e.media === 'video' ? 'Прикреплено видео'
                                  : e.media === 'photo' ? 'Прикреплено фото' : 'Прикреплён файл'}
                            style={{ marginRight: 4 }}>
                        {e.media === 'video' ? '🎬' : e.media === 'photo' ? '📷' : '📎'}
                      </span>
                    )}
```

на:

```jsx
                    {e.media && (
                      <MediaPreview kind={e.media} url={`/intel/mention/${e.id}/media`} label={e.text} />
                    )}
```

- [ ] **Step 3: Интегрировать в ThreadContext.jsx**

В `echo-app/src/features/intel/components/ThreadContext.jsx`:

1. Импорт сверху: `import MediaPreview from './MediaPreview';`
2. Найти рендер элемента `reply_chain` (где выводится `author`/`text` родителя) и перед текстом родителя добавить (там, где доступны `mentionId` и элемент `r` с `r.tg_msg_id`/`r.media`):

```jsx
{r.media && (
  <MediaPreview kind={r.media}
    url={`/intel/mention/${mentionId}/parent-media/${r.tg_msg_id}`}
    label={r.text} />
)}
```

(Реализатор находит точное место по существующей разметке reply_chain; `mentionId` — проп компонента, `r` — текущий элемент цепочки.)

- [ ] **Step 4: Ручная проверка (нет JS-тест-раннера)**

Собрать фронт и убедиться, что нет ошибок сборки:

Run: `cd echo-app && npm run build 2>&1 | tail -20`
Expected: сборка без ошибок (компонент импортируется, JSX валиден).

Если `npm run build` недоступен в окружении — реализатор отмечает это в отчёте и проверяет синтаксис через `node --check` по возможности; визуальная проверка hover остаётся за пользователем после перезапуска.

- [ ] **Step 5: Коммит**

```bash
git add echo-app/src/features/intel/components/MediaPreview.jsx echo-app/src/features/intel/components/IntelHome.jsx echo-app/src/features/intel/components/ThreadContext.jsx echo-app/src/features/intel/intel.module.css
git commit -m "$(cat <<'EOF'
feat(intel-ui): hover-превью медиа (MediaPreview) в ленте и треде

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Интеграция и перезапуск

**Files:** нет изменений кода — операционный шаг.

- [ ] **Step 1: Полный прогон backend-тестов**

Run: `cd backend && python3 -m pytest tests/ -q`
Expected: все зелёные (включая новые media-тесты).

- [ ] **Step 2: Перезапуск бэкенда (выполняет АССИСТЕНТ)**

Run: `launchctl kickstart -k gui/$(id -u)/com.echo.backend`
Expected: бэкенд поднят с новыми эндпоинтами.

- [ ] **Step 3: Дымовая проверка эндпоинта (требует авторизации; опционально)**

Проверить, что маршрут зарегистрирован (без токена — 401/403, не 404):

Run: `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/intel/mention/1/media`
Expected: `401` или `403` (маршрут существует, нужна авторизация), НЕ `404`.

---

## Self-Review

**Spec coverage:**
- §1 провайдер скачивает превью → Task 1. ✓
- §2 дисковый кэш → Task 2. ✓
- §3 эндпоинты (своё + родитель), auth Depends(current_user), 404/503 → Task 3 (своё) + Task 5 (родитель). ✓
- §4 тред: media в IntelThreadContext, миграция, fetch_thread_context, context_pass, reply_chain → Task 4 + Task 5 (reply_chain). ✓
- §5 фронт MediaPreview + интеграция в IntelHome/ThreadContext, fetch+blob, getToken → Task 6. ✓
- §6 ошибки/лимиты (FloodWait→503, кэш ≤1 скачивание) → Task 1 (проброс), Task 2 (кэш), Task 3 (503). ✓
- §7 тесты → есть в Task 1/2/3/4/5; фронт — ручная проверка (нет JS-раннера), отмечено. ✓
- За рамками (видео-плеер, полноразмер, LRU, file-превью) — не включено, соответствует спеке. ✓

**Placeholder scan:** код приведён целиком; в Task 3 Step 3 явно описаны два варианта разрешения циклического импорта (модульный алиас `_get_tg_provider` либо локальный импорт) — это не плейсхолдер, а конкретная инструкция с рабочим контрактом теста.

**Type consistency:** `download_media_preview(handle, msg_id, kind) -> (bytes, mime)|None` единообразно (Task 1↔2). `get_or_fetch(provider, post_id, handle, msg_id, kind) -> (Path, mime)|None` единообразно (Task 2↔3↔5). `IntelThreadContext.media` (Task 4) используется в Task 5/6. `MediaPreview({kind, url, label})` — одинаково в Task 6 интеграциях. Маршруты `/intel/mention/{id}/media` и `/intel/mention/{id}/parent-media/{tg_msg_id}` совпадают между бэкендом (Task 3/5) и фронтом (Task 6).
