# Hover-предпросмотр медиа в ленте intel — дизайн

Дата: 2026-06-27
Ветка: `feat/intel-media-preview` (от `feat/intel-thread-context`)

## Проблема

В ленте у постов с вложением показывается иконка 📷/🎬/📎 (`e.media`), но чтобы
увидеть само фото/видео, нужно переходить по ссылке «↗ TG». Хочется навести курсор
на иконку и сразу увидеть превью — фото или постер видео — не уходя в Telegram.
Охват: вложение самого поста **и** медиа родительского сообщения в reply-треде
(«ответ на фото»).

## Ключевое ограничение

В БД хранится только **тип** вложения (`media`: `"photo"|"video"|"file"|None`), ни URL,
ни байтов. У Telegram нет публичных ссылок на медиа — файл достаётся только скачиванием
через Telethon-клиент по `(handle, msg_id)`, и это сетевой запрос под лимитами FloodWait.
Поэтому фича = скачивание превью по требованию + дисковый кэш + авторизованный
байт-эндпоинт + hover-поповер во фронте.

`<img src>` не умеет слать заголовок `Authorization`, поэтому фронт грузит медиа через
`fetch` с Bearer-заголовком (тот же паттерн, что у live-стрима — `streamLiveEvents`
использует `fetch`, а не `EventSource`), получает `blob` и подставляет `URL.createObjectURL`
в `<img src>`. Так эндпоинты сохраняют стандартную авторизацию `current_user` (Header) без
токена в URL.

## Решение (ленивое скачивание + дисковый кэш)

Отклонённые альтернативы: префетч превью на этапе сбора (шторм скачиваний и FloodWait
для непросмотренных постов — дорого, YAGNI); прокси-редирект на URL Telegram (публичных
URL нет — невозможно).

### 1. Провайдер: скачивание превью

Новый метод в `backend/radar/core/providers/telegram.py`:

```python
def download_media_preview(self, handle: str, msg_id: int, kind: str) -> tuple[bytes, str] | None:
    """Скачать превью-размер медиа сообщения. Возвращает (bytes, mime) или None.
    photo -> сжатый размер; video/gif -> thumbnail-постер (image/jpeg);
    file/без превью -> None. Бросает TelegramFloodWait наружу."""
```

Внутри: `get_entity(h)` → `get_messages(entity, ids=[msg_id])` → для photo
`download_media(msg, thumb=-1)` (наибольший доступный thumbnail-размер, не оригинал);
для video/gif/video_note — `download_media(msg, thumb=-1)` (постер). Возвращает байты в
память (`download_media(..., file=bytes)`) и mime `image/jpeg`. `file` и отсутствие
thumbnail → `None`. `TelegramFloodWait` пробрасывается (как в `fetch_thread_context`).
`handle` нормализуется как в `search_chat` (`@`/`#`).

### 2. Дисковый кэш

Новый модуль `backend/radar/intel/media_cache.py`:

```python
def cache_path(post_id: str) -> Path        # детерминированный путь по post_id
def get_or_fetch(provider, post_id, handle, msg_id, kind) -> Path | None
```

`get_or_fetch`: если файл уже в кэше — вернуть путь, провайдер НЕ вызывается; иначе
вызвать `provider.download_media_preview`, при непустом результате записать файл и вернуть
путь, при `None` — вернуть `None`. Каталог — `MEDIA_CACHE_DIR` (env, по умолчанию
`backend/.media_cache/`), создаётся при старте. `post_id` санитизируется в имя файла
(слэши/спецсимволы → `_`), расширение по mime. Чистый модуль, провайдер мокается в тестах.
`.media_cache/` добавляется в `.gitignore`.

### 3. Эндпоинты (`backend/radar/intel/api.py`)

- `GET /intel/mention/{id}/media` — превью своего вложения упоминания.
- `GET /intel/mention/{id}/parent-media/{tg_msg_id}` — превью медиа родителя
  из треда (tg_msg_id — id родительского сообщения в той же группе/канале).

Общая логика обоих:
- Auth: `user: User = Depends(current_user)` (Bearer-заголовок), как у прочих intel-GET;
  нет/битый → 401.
- Найти упоминание (404 если нет). Определить `kind` (`mention.media` для своего;
  `IntelThreadContext.media` для родителя по `tg_msg_id`) и `handle`/`msg_id`
  (используется `_handle_for` / namespace упоминания, как в `context_pass`).
- `kind` пустой или `file` → 404.
- `media_cache.get_or_fetch(...)`:
  - путь есть → `FileResponse` с mime + `Cache-Control: private, max-age=86400`;
  - `None` → 404;
  - `TelegramFloodWait` → 503 (поповер покажет «недоступно»).

### 4. Тред: тип медиа родителя

- Миграция: добавить запись `"intel_thread_context": {"media": "TEXT"}` в словарь
  `_MIGRATIONS` в `backend/radar/core/db.py` (идемпотентный `ALTER TABLE ADD COLUMN` на
  старте — тот же механизм, что добавил `intel_mentions.media`). Плюс поле `media`
  (nullable Text) в модель `IntelThreadContext`.
- `provider.fetch_thread_context` возвращает `media` (через `_media_kind`) в каждом
  элементе `parents`; `context_pass.enrich_context` пишет его в `IntelThreadContext.media`.
- `context_pass._resolve_locally` пишет `media` parent-строк из `parent.media` (своё поле
  упоминания-родителя уже известно).
- `intel_story_detail` / thread-ответ (`reply_chain`) включает `media` в каждый элемент.

### 5. Фронт: общий hover-поповер

Новый компонент `echo-app/src/features/intel/components/MediaPreview.jsx`:
- Пропсы: `kind` (`photo|video`), `url` (путь эндпоинта), `label`.
- Рендерит иконку (📷/🎬). На `mouseenter` с задержкой ~200мс лениво грузит медиа через
  `fetch(url, { headers: { Authorization: 'Bearer ' + getToken() } })` → `blob` →
  `URL.createObjectURL` → `<img src>` в плавающем поповере; спиннер на время загрузки;
  «превью недоступно» при ошибке/не-200. Для видео — постер + бейдж ▶. На `mouseleave`
  поповер скрывается. objectURL кэшируется в памяти на время сессии (повторный hover
  мгновенный), освобождается при размонтировании.
- `getToken` импортируется из `../../core/api/client` (как в `api.js`).

Интеграция:
- `IntelHome.jsx`: заменить статичный `<span>` иконки на `<MediaPreview>` с
  `url=/intel/mention/{e.id}/media`.
- `ThreadContext.jsx`: для parent-строки с `media` показать `<MediaPreview>` с
  `url=/intel/mention/{mentionId}/parent-media/{tg_msg_id}`.

### 6. Ошибки и лимиты

FloodWait никогда не валит ленту: эндпоинт → 503, поповер → «превью недоступно, открой в
TG ↗». Throttle переиспользует `_await`. Дисковый кэш гарантирует ≤1 скачивание на медиа.

### 7. Тесты (`python3 -m pytest` из `backend/`)

- `media_cache.get_or_fetch`: (a) попадание в кэш не вызывает провайдер; (b) промах —
  вызывает провайдер и пишет файл; (c) провайдер вернул `None` → результат `None`, файл не
  создан. Провайдер — мок.
- Эндпоинты (`TestClient`): 401 без/с битым токеном; 404 при пустом/`file` media;
  503 при `TelegramFloodWait` (мок провайдера); 200 + корректный `Content-Type` при успехе
  (мок `get_or_fetch`/провайдера, без реальной сети).
- `fetch_thread_context` (мок Telethon-сообщений): элементы `parents` несут `media`.
- `_resolve_locally`: parent-строки `IntelThreadContext` получают `media` из родителя.
- Фронт: smoke на `MediaPreview` (если есть JS-тест-раннер; иначе ручная проверка —
  отметить в плане).

## За рамками (YAGNI)

- Воспроизводимое видео в поповере (только постер); полноразмерное фото (только превью —
  полное по клику «↗ TG»).
- Префетч/прогрев кэша; вытеснение по размеру (LRU) — кэш растёт по факту просмотров;
  при необходимости чистится вручную. Лимит размера — отдельная задача, если понадобится.
- Превью для `file`-вложений (документы) — иконка 📎 без поповера.
