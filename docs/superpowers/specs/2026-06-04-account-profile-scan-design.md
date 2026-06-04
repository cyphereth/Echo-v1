# Account Profile Scan — Design

**Date:** 2026-06-04
**Status:** Approved

## Overview

Дать пользователю ввести ссылки на TikTok/Instagram аккаунты бренда. Echo сканирует посты бренда и комментарии под ними, через Claude выводит полный профиль: название, голос (tone-примеры), ключевые слова, хэштеги, конкурентов, нишу, тональность аудитории. Профиль автозаполняет онбординг-визард.

## Constraints / Технические факты

- TikHub **не отдаёт** «комментарии, оставленные пользователем под чужими видео» для TikTok/Instagram (есть только для LinkedIn/Reddit). Поэтому пункт «под чьими видео комментирует бренд» не реализуем напрямую — конкурентов/нишу выводит Claude из реального контента бренда (гибрид).
- Доступно: `fetch_user_profile`/`fetch_user_info_by_username` (профиль), `fetch_user_posts` (посты бренда), `fetch_video_comments` (комментарии под постом → аудитория + ответы бренда).

## Backend

### Провайдер (base.py / tikhub.py / mock.py)

Новые методы в `SearchProvider`:
```python
def fetch_profile(self, username: str, platform: str = "tiktok") -> dict:
    """{name, bio, followers, username} — пустой dict если не найден."""
    return {}

def fetch_user_posts(self, username: str, platform: str = "tiktok", limit: int = 15) -> list[Post]:
    """Посты аккаунта. [] если недоступно."""
    return []
```

**TikHub реализация:**
- TikTok профиль: `GET /api/v1/tiktok/web/fetch_user_profile?uniqueId=<username>`
- TikTok посты: `GET /api/v1/tiktok/web/fetch_user_post?secUid=<...>` (secUid берётся из профиля)
- IG профиль: `GET /api/v1/instagram/v1/fetch_user_info_by_username?username=<username>`
- IG посты: `GET /api/v1/instagram/v1/fetch_user_posts?username=<username>`
- Каждый метод: try/except, при ошибке возвращает `{}` / `[]` и логирует warning.

**MockProvider:** возвращает фейковый профиль (`name="MockBrand"`, 1000 подписчиков) и 5 фейковых постов — для e2e теста без реального API.

### Хелпер _parse_handle

```python
def _parse_handle(s: str) -> str:
    """Вытаскивает username из @name, URL tiktok/instagram, или сырой строки."""
    s = s.strip()
    if not s:
        return ""
    # URL → последний сегмент пути
    if "/" in s:
        import re
        m = re.search(r'(?:tiktok\.com/@|instagram\.com/)([^/?#]+)', s)
        if m:
            return m.group(1).lstrip("@")
        s = s.rstrip("/").split("/")[-1]
    return s.lstrip("@")
```

### POST /brands/profile-scan

```
Auth: Bearer
Body: { "tiktok": str = "", "instagram": str = "" }
Response: {
  "name": str,
  "voice_description": str,
  "tone_examples": [str],
  "keywords": [str],
  "hashtags": [str],
  "competitors": [str],
  "niche_keywords": [str],
  "audience_sentiment": {"positive": int, "negative": int, "neutral": int},
  "scanned": {"tiktok": bool, "instagram": bool}  # какие платформы реально прочитались
}
```

Логика:
1. Для каждой непустой платформы: `handle = _parse_handle(...)`, `fetch_profile`, `fetch_user_posts(limit=15)`.
2. Топ-3 поста по (likes+views): `fetch_comments(post_id, None, platform)` → собрать тексты комментариев + ответы бренда (комментарии где `author.lower() == handle.lower()`).
3. Если ни одна платформа не прочиталась → `HTTPException(422, "No accounts could be read")`.
4. Собрать всё в текст, вызвать `_profile_with_claude(...)` (см. ниже).
5. Вернуть профиль + `scanned`.

Timeout: эндпоинт долгий (Claude + ~10 TikHub запросов) — на фронте спиннер.

### _profile_with_claude

Новая функция (рядом с suggest_brand). Модель `claude-haiku-4-5-20251001`, max_tokens 600, timeout 60, retry 1 раз на невалидный JSON (паттерн как в `/brands/suggest`).

Системный промпт:
> Ты аналитик бренда. На основе реального контента аккаунта в соцсетях определи профиль для мониторинга упоминаний и генерации ответов. Отвечай ТОЛЬКО валидным JSON без markdown.

Пользовательский промпт (заполняется собранными данными):
```
Профиль: {name}, {bio}, {followers} подписчиков
Посты бренда (тексты + хэштеги):
{posts joined}
Реальные ответы бренда на комментарии (если есть):
{brand_replies joined}
Тональность комментариев аудитории: {pos} поз / {neg} нег / {neu} нейтр

Верни JSON: {"name","voice_description","tone_examples":[3 примера голоса],"keywords":[5-7],"hashtags":[3-5],"competitors":[3-5],"niche_keywords":[3-5],"audience_sentiment":{"positive","negative","neutral"}}
```

`tone_examples`: если есть реальные ответы бренда — Claude берёт их; иначе выводит из стиля постов.

### Изменения onboarding / createBrand

- `OnboardingBody` + поле `tone_examples: list[str] = []`.
- `onboarding()`: сохранять `tone_examples=json.dumps(body.tone_examples)` в Brand.
- (`Brand.tone_examples` уже существует, идёт в `generate_draft` → черновики звучат как бренд.)

## Frontend

### api.js
```js
export const scanProfile = (tiktok, instagram) =>
  request('/brands/profile-scan', {
    method: 'POST',
    body: JSON.stringify({ tiktok, instagram }),
  });
```
`createBrand` — добавить параметр `tone_examples = []` в тело.

### AIWizard.jsx — 3 шага (было 2)

**Шаг 0 «Аккаунты бренда»** (новый, первый):
- Поля «TikTok» и «Instagram» (@username или ссылка), можно одно или оба
- Кнопка «Анализировать аккаунты» → `scanProfile` → спиннер «Анализирую аккаунты бренда…»
- Под кнопкой: «Echo прочитает посты и комментарии, чтобы понять голос бренда и темы»
- Ссылка «Заполнить вручную по названию →» → переход в режим текущего Шага 1 с пустыми полями (название + Claude suggest)
- После успешного скана → заполняет name/keywords/hashtags/competitors/niche/toneExamples/voice/audience → Шаг 1

**Шаг 1 «Проверьте профиль»** (текущий, дополнен):
- Название (редактируемо)
- TagGroups: keywords, hashtags, competitors, niche (как сейчас)
- Новый блок «Голос бренда»: `voice_description` текст + tone-примеры тегами (удаляемые)
- Новая плашка «Аудитория: {pos}% 👍 / {neg}% 👎» (информативно, если есть)
- Кнопка «Предпросмотр постов →»

**Шаг 2 «Превью»** (без изменений) → «Создать бренд» (передаёт tone_examples).

Состояние визарда: `step` 0|1|2, добавить `tiktokUrl`, `instagramUrl`, `voiceDescription`, `audienceSentiment`, `scanning`.

## Error Handling

| Ситуация | Поведение |
|----------|-----------|
| Одна платформа недоступна/приватна | Пропустить, профиль из второй, тост |
| Обе недоступны | 422 → тост «Не удалось прочитать аккаунты», переход на ручной путь |
| TikHub rate-limit на постах | Использовать что собрали |
| Комментарии не достались | Профиль без реальных ответов, голос из постов |
| Claude невалидный JSON | 1 retry → тост «AI-анализ недоступен» + ручной путь |

## Testing

- Юнит `_parse_handle`: `@ozon`, `https://tiktok.com/@ozon`, `https://instagram.com/ozon.ru/`, `ozon` → все дают чистый username.
- E2e скан через MockProvider: возвращает фейк-профиль + посты → `/brands/profile-scan` отдаёт валидный профиль (Claude или фолбэк).
- Билд фронта проходит.

## What Changes

| Файл | Изменение |
|------|-----------|
| `backend/radar/providers/base.py` | +`fetch_profile`, +`fetch_user_posts` (дефолты) |
| `backend/radar/providers/tikhub.py` | реализация обоих методов для TT+IG |
| `backend/radar/providers/mock.py` | фейк-профиль и посты |
| `backend/radar/api.py` | `_parse_handle`, `POST /brands/profile-scan`, `_profile_with_claude`, `tone_examples` в onboarding |
| `echo-app/src/services/api.js` | `scanProfile`, `createBrand` +tone_examples |
| `echo-app/src/components/app/AIWizard.jsx` | Шаг 0 + голос/аудитория в Шаге 1 |
| `echo-app/src/components/app/aiwizard.module.css` | стили полей аккаунтов + блок голоса |
