# Account Profile Scan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Пользователь вводит ссылки на TikTok/Instagram аккаунты бренда → Echo сканирует посты и комментарии → Claude выводит полный профиль (название, голос, ключевые слова, конкуренты, ниша, тональность аудитории) → автозаполняет онбординг-визард.

**Architecture:** Бэкенд получает новые методы провайдера `fetch_profile`/`fetch_user_posts` (TikHub TT+IG, защитные парсеры). Эндпоинт `POST /brands/profile-scan` собирает данные и через Claude (`_profile_with_claude`) возвращает структурированный профиль. Фронт: AIWizard получает Шаг 0 «Аккаунты бренда» перед текущими шагами.

**Tech Stack:** FastAPI, SQLAlchemy, httpx, Claude API (`claude-haiku-4-5-20251001`), React 18 + Vite

---

## File Map

**Модифицировать:**
- `backend/radar/providers/base.py` — +`fetch_profile`, +`fetch_user_posts` (дефолты)
- `backend/radar/providers/tikhub.py` — реализация для TT+IG
- `backend/radar/providers/mock.py` — фейк-профиль и посты
- `backend/radar/api.py` — `_parse_handle`, `_profile_with_claude`, `POST /brands/profile-scan`, `tone_examples` в onboarding
- `echo-app/src/services/api.js` — `scanProfile`, `createBrand` +tone_examples
- `echo-app/src/components/app/AIWizard.jsx` — Шаг 0 + голос/аудитория
- `echo-app/src/components/app/aiwizard.module.css` — стили

**Создать:**
- `backend/tests/test_profile_scan.py` — юнит `_parse_handle` + e2e скан через mock

---

## Task 1: Провайдер — fetch_profile + fetch_user_posts (base + mock)

**Files:**
- Modify: `backend/radar/providers/base.py`
- Modify: `backend/radar/providers/mock.py`

- [ ] **Шаг 1: Добавить дефолтные методы в SearchProvider (base.py)**

В `backend/radar/providers/base.py` в класс `SearchProvider` после `fetch_comments` добавить:

```python
    def fetch_profile(self, username: str, platform: str = "tiktok") -> dict:
        """Account profile: {name, bio, followers, username, _secuid?, _userid?}. Empty dict if unavailable."""
        return {}

    def fetch_user_posts(self, username: str, platform: str = "tiktok", limit: int = 15) -> list["Post"]:
        """Posts authored by the account. Empty list if unavailable."""
        return []
```

- [ ] **Шаг 2: Реализовать в MockProvider (mock.py)**

В `backend/radar/providers/mock.py` в класс `MockProvider` добавить методы (в конец класса):

```python
    def fetch_profile(self, username: str, platform: str = "tiktok") -> dict:
        return {
            "name": f"Mock {username.title()}",
            "bio": "Демо-бренд для тестов",
            "followers": 12000,
            "username": username,
        }

    def fetch_user_posts(self, username: str, platform: str = "tiktok", limit: int = 15) -> list[Post]:
        now = datetime.now(timezone.utc)
        return [Post(
            post_id=f"{platform}_{username}_own_{i}",
            platform=platform,
            author=username,
            followers=12000,
            text=f"Пост бренда {username} №{i}: {_FLAVORS[i % len(_FLAVORS)]} #бренд",
            hashtags=["бренд"],
            created_at=now - timedelta(hours=i + 1),
            likes=(i + 1) * 200, views=(i + 1) * 8000,
            comments=(i + 1) * 25, shares=(i + 1) * 5,
        ) for i in range(min(limit, 5))]
```

- [ ] **Шаг 3: Проверить импорт**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/backend && python3 -c "from radar.providers.mock import MockProvider; p=MockProvider(); print(p.fetch_profile('ozon')); print(len(p.fetch_user_posts('ozon')))"
```

Ожидаемый вывод: dict с `name`, и `5`.

- [ ] **Шаг 4: Закоммитить**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1
git add backend/radar/providers/base.py backend/radar/providers/mock.py
git commit -m "feat: fetch_profile + fetch_user_posts provider methods (base + mock)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Провайдер — TikHub реализация fetch_profile + fetch_user_posts

**Files:**
- Modify: `backend/radar/providers/tikhub.py`

Подтверждённые формы ответов:
- TT профиль: `GET /api/v1/tiktok/web/fetch_user_profile?uniqueId=<u>` → `data.userInfo.user.{secUid,nickname}`, `data.userInfo.stats.followerCount`, `data.userInfo.user.signature` (bio)
- TT посты: `GET /api/v1/tiktok/web/fetch_user_post?secUid=<s>&count=<n>` → `data.itemList[]` (формат как `_parse_tiktok_post`)
- IG профиль: `GET /api/v1/instagram/v1/fetch_user_info_by_username?username=<u>` → `data.user.{id,full_name,username,biography}`, `data.user.edge_followed_by.count`
- IG посты: `GET /api/v1/instagram/v1/fetch_user_posts?user_id=<id>&count=<n>` → `data.items[]` (формат как `_parse_ig_post`)

- [ ] **Шаг 1: Прочитать tikhub.py**

```bash
cat /Users/vovolypsi/Echo-v1/Echo-v1/backend/radar/providers/tikhub.py
```

- [ ] **Шаг 2: Добавить fetch_profile в TikHubProvider**

В класс `TikHubProvider` (после `fetch_comments`, до module-level парсеров) добавить:

```python
    # ── Account profile + own posts ───────────────────────────────────────────
    def fetch_profile(self, username: str, platform: str = "tiktok") -> dict:
        try:
            if platform == "instagram":
                resp = httpx.get(
                    f"{BASE_URL}/api/v1/instagram/v1/fetch_user_info_by_username",
                    headers=self._headers, params={"username": username}, timeout=25,
                )
                resp.raise_for_status()
                u = ((resp.json().get("data", {}) or {}).get("user", {}) or {})
                followers = (u.get("edge_followed_by", {}) or {}).get("count", 0) or u.get("follower_count", 0) or 0
                return {
                    "name": u.get("full_name") or username,
                    "bio": u.get("biography", "") or "",
                    "followers": followers,
                    "username": u.get("username") or username,
                    "_userid": str(u.get("id") or u.get("pk") or ""),
                }
            # tiktok
            resp = httpx.get(
                f"{BASE_URL}/api/v1/tiktok/web/fetch_user_profile",
                headers=self._headers, params={"uniqueId": username}, timeout=25,
            )
            resp.raise_for_status()
            ui = (resp.json().get("data", {}) or {}).get("userInfo", {}) or {}
            user = ui.get("user", {}) or {}
            stats = ui.get("stats", {}) or {}
            return {
                "name": user.get("nickname") or username,
                "bio": user.get("signature", "") or "",
                "followers": stats.get("followerCount", 0) or 0,
                "username": user.get("uniqueId") or username,
                "_secuid": user.get("secUid", "") or "",
            }
        except Exception as e:
            log.warning("fetch_profile failed (%s/%s): %s", platform, username, e)
            return {}

    def fetch_user_posts(self, username: str, platform: str = "tiktok", limit: int = 15) -> list[Post]:
        try:
            prof = self.fetch_profile(username, platform)
            if platform == "instagram":
                uid = prof.get("_userid")
                if not uid:
                    return []
                resp = httpx.get(
                    f"{BASE_URL}/api/v1/instagram/v1/fetch_user_posts",
                    headers=self._headers, params={"user_id": uid, "count": limit}, timeout=25,
                )
                resp.raise_for_status()
                data = resp.json().get("data", {}) or {}
                items = data.get("items") or data.get("medias") or []
                return [p for it in items if (p := self._safe_parse_ig(it)) is not None][:limit]
            # tiktok
            secuid = prof.get("_secuid")
            if not secuid:
                return []
            resp = httpx.get(
                f"{BASE_URL}/api/v1/tiktok/web/fetch_user_post",
                headers=self._headers, params={"secUid": secuid, "count": limit}, timeout=25,
            )
            resp.raise_for_status()
            data = resp.json().get("data", {}) or {}
            items = data.get("itemList") or data.get("aweme_list") or []
            out = []
            for it in items:
                try:
                    out.append(_parse_tiktok_post(it))
                except Exception:
                    continue
            return out[:limit]
        except Exception as e:
            log.warning("fetch_user_posts failed (%s/%s): %s", platform, username, e)
            return []
```

- [ ] **Шаг 3: Проверить импорт**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/backend && python3 -c "from radar.providers.tikhub import TikHubProvider; print('OK')"
```

Ожидаемый вывод: `OK`

- [ ] **Шаг 4: Живой smoke-тест (rate-limit допустим — главное нет крэша)**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/backend
python3 - <<'EOF'
import os
for line in open('.env'):
    line=line.strip()
    if '=' in line and not line.startswith('#'):
        k,v=line.split('=',1); os.environ[k]=v
from radar.providers.tikhub import TikHubProvider
p = TikHubProvider(os.environ['TIKHUB_TOKEN'])
prof = p.fetch_profile('ozon', 'tiktok')
print('TT profile:', {k: prof.get(k) for k in ('name','followers')} if prof else 'empty (ok if rate-limited)')
EOF
```

Ожидаемый вывод: профиль с name/followers, ИЛИ `empty` (не должно быть исключения).

- [ ] **Шаг 5: Закоммитить**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1
git add backend/radar/providers/tikhub.py
git commit -m "feat: TikHub fetch_profile + fetch_user_posts for TikTok & Instagram

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: _parse_handle + юнит-тест

**Files:**
- Modify: `backend/radar/api.py`
- Create: `backend/tests/test_profile_scan.py`

- [ ] **Шаг 1: Написать тест (создать backend/tests/test_profile_scan.py)**

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from radar.api import _parse_handle


def test_parse_handle_at_username():
    assert _parse_handle("@ozon") == "ozon"

def test_parse_handle_plain():
    assert _parse_handle("ozon") == "ozon"

def test_parse_handle_tiktok_url():
    assert _parse_handle("https://www.tiktok.com/@ozon") == "ozon"

def test_parse_handle_instagram_url():
    assert _parse_handle("https://www.instagram.com/ozon.ru/") == "ozon.ru"

def test_parse_handle_empty():
    assert _parse_handle("") == ""
    assert _parse_handle("   ") == ""
```

- [ ] **Шаг 2: Запустить тест — убедиться что падает**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/backend && python3 -m pytest tests/test_profile_scan.py -v 2>&1 | tail -10
```

Ожидаемый вывод: FAIL (`ImportError` / `_parse_handle` не существует).

- [ ] **Шаг 3: Добавить _parse_handle в api.py**

В `backend/radar/api.py` рядом с другими хелперами (например после `_post_url`) добавить:

```python
import re as _re

def _parse_handle(s: str) -> str:
    """Extract a username from @name, a tiktok/instagram URL, or a raw string."""
    s = (s or "").strip()
    if not s:
        return ""
    if "/" in s:
        m = _re.search(r'(?:tiktok\.com/@|instagram\.com/)([^/?#]+)', s)
        if m:
            return m.group(1).lstrip("@")
        s = s.rstrip("/").split("/")[-1]
    return s.lstrip("@")
```

- [ ] **Шаг 4: Запустить тест — убедиться что проходит**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/backend && python3 -m pytest tests/test_profile_scan.py -v 2>&1 | tail -12
```

Ожидаемый вывод: 5 passed.

- [ ] **Шаг 5: Закоммитить**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1
git add backend/radar/api.py backend/tests/test_profile_scan.py
git commit -m "feat: _parse_handle helper for account URLs + unit tests

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: _profile_with_claude + POST /brands/profile-scan

**Files:**
- Modify: `backend/radar/api.py`

- [ ] **Шаг 1: Добавить _profile_with_claude в api.py**

После `suggest_brand` (или рядом с `_parse_handle`) добавить:

```python
def _profile_with_claude(name_hint: str, bio: str, followers: int,
                         posts_text: list[str], brand_replies: list[str],
                         sentiment: dict) -> dict:
    """Distill a brand profile from scanned account content via Claude. Returns {} on failure."""
    import httpx as _httpx
    from .drafts import LLM_API_KEY, LLM_API_URL
    if not LLM_API_KEY:
        return {}

    system = (
        "Ты аналитик бренда. На основе реального контента аккаунта в соцсетях определи "
        "профиль для мониторинга упоминаний и генерации ответов. Отвечай ТОЛЬКО валидным JSON без markdown."
    )
    posts_block   = "\n".join(f"- {t[:200]}" for t in posts_text[:15]) or "(нет постов)"
    replies_block = "\n".join(f"- {r[:200]}" for r in brand_replies[:5]) or "(нет ответов бренда)"
    user_msg = (
        f"Профиль: {name_hint}, {bio[:200]}, {followers} подписчиков\n"
        f"Посты бренда:\n{posts_block}\n"
        f"Реальные ответы бренда на комментарии:\n{replies_block}\n"
        f"Тональность аудитории: {sentiment.get('positive',0)} поз / "
        f"{sentiment.get('negative',0)} нег / {sentiment.get('neutral',0)} нейтр\n\n"
        'Верни JSON: {"name":"","voice_description":"","tone_examples":[],'
        '"keywords":[],"hashtags":[],"competitors":[],"niche_keywords":[]}'
    )

    def _call():
        resp = _httpx.post(
            LLM_API_URL,
            headers={"x-api-key": LLM_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 600,
                  "system": system, "messages": [{"role": "user", "content": user_msg}]},
            timeout=60,
        )
        resp.raise_for_status()
        blocks = resp.json().get("content", [])
        text = next((b["text"] for b in blocks if b.get("type") == "text"), "")
        text = text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(text)

    try:
        return _call()
    except (json.JSONDecodeError, KeyError):
        try:
            return _call()
        except Exception as e:
            log.warning("_profile_with_claude retry failed: %s", e)
            return {}
    except Exception as e:
        log.warning("_profile_with_claude failed: %s", e)
        return {}
```

- [ ] **Шаг 2: Добавить ScanBody и эндпоинт POST /brands/profile-scan**

Рядом с `SuggestBody` / `PreviewBody` в api.py добавить:

```python
class ScanBody(BaseModel):
    tiktok:    str = ""
    instagram: str = ""

@app.post("/brands/profile-scan")
def profile_scan(body: ScanBody, user: User = Depends(current_user)):
    """Scan brand's own accounts → Claude-distilled profile for onboarding."""
    provider = _get_provider()
    platforms = []
    if body.tiktok.strip():
        platforms.append(("tiktok", _parse_handle(body.tiktok)))
    if body.instagram.strip():
        platforms.append(("instagram", _parse_handle(body.instagram)))
    if not platforms:
        raise HTTPException(400, "Provide at least one account")

    name_hint, bio, followers = "", "", 0
    posts_text: list[str] = []
    brand_replies: list[str] = []
    sentiment = {"positive": 0, "negative": 0, "neutral": 0}
    scanned = {"tiktok": False, "instagram": False}

    for platform, handle in platforms:
        if not handle:
            continue
        prof = provider.fetch_profile(handle, platform)
        if not prof:
            continue
        scanned[platform] = True
        name_hint = name_hint or prof.get("name", "")
        bio = bio or prof.get("bio", "")
        followers = max(followers, prof.get("followers", 0))

        posts = provider.fetch_user_posts(handle, platform, limit=15)
        posts_text.extend(p.text for p in posts if p.text)

        # Audience + brand replies from top-3 posts by engagement.
        top = sorted(posts, key=lambda p: (p.likes + p.views), reverse=True)[:3]
        for p in top:
            for c in provider.fetch_comments(p.post_id, None, platform):
                if c.author.lower() == handle.lower():
                    brand_replies.append(c.text)
                # crude sentiment tally by keyword presence
                t = c.text.lower()
                if any(w in t for w in ("отлично", "супер", "спасибо", "люблю", "класс", "👍", "❤")):
                    sentiment["positive"] += 1
                elif any(w in t for w in ("ужас", "плохо", "обман", "верните", "кошмар", "👎")):
                    sentiment["negative"] += 1
                else:
                    sentiment["neutral"] += 1

    if not any(scanned.values()):
        raise HTTPException(422, "No accounts could be read")

    profile = _profile_with_claude(name_hint, bio, followers, posts_text, brand_replies, sentiment)
    return {
        "name":              profile.get("name") or name_hint,
        "voice_description": profile.get("voice_description", ""),
        "tone_examples":     profile.get("tone_examples", []) or brand_replies[:3],
        "keywords":          profile.get("keywords", []),
        "hashtags":          profile.get("hashtags", []),
        "competitors":       profile.get("competitors", []),
        "niche_keywords":    profile.get("niche_keywords", []),
        "audience_sentiment": sentiment,
        "scanned":           scanned,
    }
```

- [ ] **Шаг 3: Проверить импорт**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/backend && python3 -c "import radar.api; print('OK')"
```

Ожидаемый вывод: `OK`

- [ ] **Шаг 4: E2e скан через mock (без реального TikHub)**

Дописать в `backend/tests/test_profile_scan.py`:

```python
def test_profile_scan_with_mock(monkeypatch):
    """profile_scan returns a profile when provider is the mock (no real TikHub)."""
    from radar import api
    from radar.providers.mock import MockProvider
    monkeypatch.setattr(api, "_get_provider", lambda: MockProvider())

    class FakeUser:
        id = 1
    body = api.ScanBody(tiktok="@testbrand", instagram="")
    result = api.profile_scan(body, user=FakeUser())
    assert result["scanned"]["tiktok"] is True
    assert result["name"]  # non-empty
    assert "audience_sentiment" in result
```

Запустить:
```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/backend && python3 -m pytest tests/test_profile_scan.py -v 2>&1 | tail -12
```

Ожидаемый вывод: все passed (6 total). Примечание: `_profile_with_claude` вернёт `{}` без LLM-ключа в тест-окружении — эндпоинт всё равно отдаёт профиль с `name=name_hint` и tone_examples из brand_replies, тест это проверяет.

- [ ] **Шаг 5: Закоммитить**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1
git add backend/radar/api.py backend/tests/test_profile_scan.py
git commit -m "feat: POST /brands/profile-scan — Claude-distilled brand profile from account scan

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: onboarding принимает tone_examples

**Files:**
- Modify: `backend/radar/api.py`

- [ ] **Шаг 1: Добавить tone_examples в OnboardingBody**

Найти `class OnboardingBody(BaseModel):` и добавить поле:

```python
class OnboardingBody(BaseModel):
    name:           str
    keywords:       list[str] = []
    hashtags:       list[str] = []
    competitors:    list[str] = []
    niche_keywords: list[str] = []
    tone_examples:  list[str] = []
```

- [ ] **Шаг 2: Сохранять tone_examples в onboarding**

В функции `onboarding`, в создании `Brand(...)`, добавить строку `tone_examples=json.dumps(body.tone_examples),`:

```python
    b = Brand(
        user_id=user.id,
        name=body.name,
        keywords=json.dumps(body.keywords),
        hashtags=json.dumps(body.hashtags),
        competitors=json.dumps(body.competitors),
        niche_keywords=json.dumps(body.niche_keywords),
        tone_examples=json.dumps(body.tone_examples),
        auto_collect=True,
    )
```

- [ ] **Шаг 3: Проверить + перезапустить backend**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/backend && python3 -c "import radar.api; print('OK')"
pkill -f "uvicorn radar.api" 2>/dev/null; sleep 2
for line in $(grep -E '^[A-Z_]+=.' .env); do export "$line"; done
nohup uvicorn radar.api:app --host 127.0.0.1 --port 8000 > /tmp/echo_backend.log 2>&1 &
sleep 6
python3 -c "import httpx; print('health:', httpx.get('http://127.0.0.1:8000/health',timeout=5).status_code)"
```

Ожидаемый вывод: `OK`, затем `health: 200`.

- [ ] **Шаг 4: Закоммитить**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1
git add backend/radar/api.py
git commit -m "feat: onboarding accepts and stores tone_examples

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: api.js — scanProfile + createBrand tone_examples

**Files:**
- Modify: `echo-app/src/services/api.js`

- [ ] **Шаг 1: Добавить scanProfile и обновить createBrand**

В `echo-app/src/services/api.js`:

Найти `export const createBrand = ...` и заменить на:
```js
export const createBrand = (name, keywords = [], hashtags = [], competitors = [], niche_keywords = [], tone_examples = []) =>
  request('/onboarding', {
    method: 'POST',
    body: JSON.stringify({ name, keywords, hashtags, competitors, niche_keywords, tone_examples }),
  });
```

Добавить в конец файла:
```js
export const scanProfile = (tiktok, instagram) =>
  request('/brands/profile-scan', {
    method: 'POST',
    body: JSON.stringify({ tiktok, instagram }),
  });
```

- [ ] **Шаг 2: Проверить билд**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/echo-app && npm run build 2>&1 | tail -4
```

Ожидаемый вывод: `✓ built in ...ms`

- [ ] **Шаг 3: Закоммитить**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1
git add echo-app/src/services/api.js
git commit -m "feat: scanProfile API helper + createBrand tone_examples param

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: AIWizard — Шаг 0 «Аккаунты бренда» + голос/аудитория

**Files:**
- Modify: `echo-app/src/components/app/AIWizard.jsx`
- Modify: `echo-app/src/components/app/aiwizard.module.css`

Текущий AIWizard: `step` 1=генерация, 2=превью. Делаем: `step` 0=аккаунты, 1=проверка, 2=превью. В режиме `edit` (из Settings) скан-шаг тоже доступен, но можно сразу прыгнуть на 1 (поля уже заполнены из бренда).

- [ ] **Шаг 1: Прочитать AIWizard.jsx**

```bash
cat /Users/vovolypsi/Echo-v1/Echo-v1/echo-app/src/components/app/AIWizard.jsx
```

- [ ] **Шаг 2: Добавить state для скана**

Найти блок `useState` в начале `AIWizard` и добавить после `const [previews, setPreviews] = useState([]);`:

```jsx
  const [tiktokUrl, setTiktokUrl]   = useState('');
  const [instagramUrl, setInstagramUrl] = useState('');
  const [voiceDescription, setVoiceDescription] = useState('');
  const [toneExamples, setToneExamples] = useState(brand?.tone_examples ?? []);
  const [audience, setAudience]     = useState(null);
  const [scanning, setScanning]     = useState(false);
```

Изменить начальный шаг: `const [step, setStep] = useState(mode === 'edit' ? 1 : 0);` (новый бренд начинает со скана, редактирование — сразу с проверки).

- [ ] **Шаг 3: Добавить handleScan**

После `handleSuggest` добавить:

```jsx
  async function handleScan() {
    if (!tiktokUrl.trim() && !instagramUrl.trim()) return;
    setScanning(true);
    setToast('');
    try {
      const data = await api.scanProfile(tiktokUrl.trim(), instagramUrl.trim());
      if (data.name) setName(data.name);
      if (data.keywords?.length)       setKeywords(data.keywords);
      if (data.hashtags?.length)       setHashtags(data.hashtags);
      if (data.competitors?.length)    setCompetitors(data.competitors);
      if (data.niche_keywords?.length) setNiche(data.niche_keywords);
      if (data.tone_examples?.length)  setToneExamples(data.tone_examples);
      if (data.voice_description)      setVoiceDescription(data.voice_description);
      if (data.audience_sentiment)     setAudience(data.audience_sentiment);
      setStep(1);
    } catch (e) {
      const msg = String(e.message || '');
      if (msg.includes('422')) {
        showToast('Не удалось прочитать аккаунты — заполните вручную по названию.');
      } else {
        showToast('Ошибка анализа аккаунтов — попробуйте ручной режим.');
      }
    } finally {
      setScanning(false);
    }
  }
```

- [ ] **Шаг 4: Обновить handleSave чтобы передавать toneExamples**

Найти в `handleSave` вызов `api.createBrand(...)` и заменить на:
```jsx
        result = await api.createBrand(name.trim(), keywords, hashtags, competitors, niche, toneExamples);
```

И в ветке `edit` (updateBrandConfig) добавить `tone_examples: toneExamples,` в объект конфига:
```jsx
        await api.updateBrandConfig(brand.id, {
          name: name.trim(), keywords, hashtags,
          exclusions: brand.exclusions ?? [],
          competitors, niche_keywords: niche,
          tone_examples: toneExamples,
        });
```

- [ ] **Шаг 5: Добавить рендер Шага 0 в JSX**

Найти `{step === 1 && (` и добавить ПЕРЕД ним блок Шага 0:

```jsx
      {step === 0 && (
        <>
          <div className={styles.section}>
            <div className={styles.sectionLabel}>TikTok аккаунт</div>
            <input
              className={styles.nameInput}
              value={tiktokUrl}
              onChange={e => setTiktokUrl(e.target.value)}
              placeholder="@ozon или ссылка"
            />
          </div>
          <div className={styles.section}>
            <div className={styles.sectionLabel}>Instagram аккаунт</div>
            <input
              className={styles.nameInput}
              value={instagramUrl}
              onChange={e => setInstagramUrl(e.target.value)}
              placeholder="@ozon.ru или ссылка"
            />
          </div>

          {toast && <div className={styles.toast}>{toast}</div>}

          <div style={{ fontSize: 12, color: 'var(--fg-4)' }}>
            Echo прочитает посты и комментарии, чтобы понять голос бренда и темы
          </div>

          <div className={styles.actions}>
            <button className={styles.cancelBtn} onClick={() => setStep(1)}>
              Заполнить вручную по названию →
            </button>
            <button
              className={styles.nextBtn}
              onClick={handleScan}
              disabled={scanning || (!tiktokUrl.trim() && !instagramUrl.trim())}
            >
              {scanning ? <><span className={styles.spinner} />Анализирую аккаунты…</> : 'Анализировать аккаунты'}
            </button>
          </div>
        </>
      )}
```

- [ ] **Шаг 6: Добавить блок голоса+аудитории в Шаг 1**

В рендере `{step === 1 && (` найти `<TagGroup label="Ниша" ...` (последний TagGroup) и добавить ПОСЛЕ него:

```jsx
          {voiceDescription && (
            <div className={styles.section}>
              <div className={styles.sectionLabel}>Голос бренда</div>
              <div style={{ fontSize: 13, color: 'var(--fg-2)' }}>{voiceDescription}</div>
            </div>
          )}
          {toneExamples.length > 0 && (
            <div className={styles.section}>
              <div className={styles.sectionLabel}>Примеры голоса</div>
              <div className={styles.tags}>
                {toneExamples.map((t, i) => (
                  <span key={i} className={styles.tag} style={{ maxWidth: '100%' }}>
                    {t.length > 60 ? t.slice(0, 60) + '…' : t}
                    <button className={styles.tagX}
                      onClick={() => setToneExamples(toneExamples.filter((_, j) => j !== i))}>✕</button>
                  </span>
                ))}
              </div>
            </div>
          )}
          {audience && (audience.positive + audience.negative + audience.neutral) > 0 && (
            <div style={{ fontSize: 12, color: 'var(--fg-4)' }}>
              Аудитория: {audience.positive} 👍 · {audience.negative} 👎 · {audience.neutral} 😐
            </div>
          )}
```

- [ ] **Шаг 7: Добавить кнопку «Назад к аккаунтам» в actions Шага 1**

В `{step === 1 && (` найти блок `<div className={styles.actions}>` и заменить кнопку «Отмена»/первую кнопку так, чтобы для create-режима была кнопка назад на скан. Найти:
```jsx
          <div className={styles.actions}>
            {mode === 'edit' && (
              <button className={styles.cancelBtn} onClick={onClose}>Отмена</button>
            )}
```
Заменить на:
```jsx
          <div className={styles.actions}>
            {mode === 'edit'
              ? <button className={styles.cancelBtn} onClick={onClose}>Отмена</button>
              : <button className={styles.cancelBtn} onClick={() => setStep(0)}>← К аккаунтам</button>}
```

- [ ] **Шаг 8: Обновить подзаголовок для Шага 0**

Найти в JSX `<div className={styles.sub}>` с тернарником про step и заменить на:
```jsx
        <div className={styles.sub}>
          {step === 0
            ? 'Введите ссылки на аккаунты бренда — Echo проанализирует контент'
            : step === 1
            ? 'Проверьте профиль бренда перед запуском'
            : 'Реальные посты по вашим ключевым словам'}
        </div>
```

- [ ] **Шаг 9: Проверить билд**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/echo-app && npm run build 2>&1 | tail -4
```

Ожидаемый вывод: `✓ built in ...ms`

- [ ] **Шаг 10: Закоммитить**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1
git add echo-app/src/components/app/AIWizard.jsx echo-app/src/components/app/aiwizard.module.css
git commit -m "feat: AIWizard Step 0 account scan + voice/audience in review step

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Финальная проверка + push

- [ ] **Шаг 1: Запустить все backend-тесты**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/backend && python3 -m pytest tests/test_profile_scan.py -v 2>&1 | tail -12
```

Ожидаемый вывод: все passed.

- [ ] **Шаг 2: E2e через работающий backend (mock или реальный)**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/backend
python3 - <<'EOF'
import os, httpx
for line in open('.env'):
    line=line.strip()
    if '=' in line and not line.startswith('#'):
        k,v=line.split('=',1); os.environ[k]=v
r = httpx.post('http://127.0.0.1:8000/auth/login', json={'email':'demo@echo.app','password':'demo12345'}, timeout=15)
token = r.json()['token']
r = httpx.post('http://127.0.0.1:8000/brands/profile-scan',
    headers={'Authorization': f'Bearer {token}'},
    json={'tiktok': '@ozon', 'instagram': ''}, timeout=90)
print('scan status:', r.status_code)
if r.status_code == 200:
    d = r.json()
    print('  name:', d.get('name'))
    print('  scanned:', d.get('scanned'))
    print('  keywords:', d.get('keywords', [])[:5])
EOF
```

Ожидаемый вывод: `scan status: 200` с name и scanned (либо 422 если оба аккаунта недоступны из-за rate-limit — приемлемо, повторить).

- [ ] **Шаг 3: Push**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1 && git push origin main 2>&1 | tail -3
```

- [ ] **Шаг 4: Браузерная проверка**

Открыть http://localhost:5173, зарегистрировать новый аккаунт → Шаг 0 визарда показывает поля TikTok/Instagram → ввести `@ozon` → «Анализировать аккаунты» → дождаться → Шаг 1 показывает название, keywords, голос → создать бренд.

---

## Self-Review

**Spec coverage:**
- ✅ Провайдер fetch_profile/fetch_user_posts — Task 1 (base+mock), Task 2 (tikhub)
- ✅ _parse_handle — Task 3
- ✅ _profile_with_claude + /brands/profile-scan — Task 4
- ✅ Аудитория + ответы бренда из топ-постов — Task 4 (внутри profile_scan)
- ✅ tone_examples в onboarding — Task 5
- ✅ scanProfile + createBrand — Task 6
- ✅ AIWizard Шаг 0 + голос/аудитория — Task 7
- ✅ Тесты _parse_handle + e2e mock — Task 3, Task 4
- ✅ Гибрид (Claude конкуренты/ниша из реального контента) — Task 4 промпт

**Placeholder scan:** нет TBD/TODO.

**Type consistency:**
- `fetch_profile(username, platform) -> dict`, `fetch_user_posts(username, platform, limit) -> list[Post]` — Task 1/2 согласованы
- `_parse_handle(s) -> str` — Task 3, используется в Task 4
- `_profile_with_claude(name_hint, bio, followers, posts_text, brand_replies, sentiment) -> dict` — Task 4
- `scanProfile(tiktok, instagram)`, `createBrand(..., tone_examples)` — Task 6, используются в Task 7
- Профиль-ответ ключи (`name, voice_description, tone_examples, keywords, hashtags, competitors, niche_keywords, audience_sentiment, scanned`) — Task 4 отдаёт, Task 7 читает — совпадают
