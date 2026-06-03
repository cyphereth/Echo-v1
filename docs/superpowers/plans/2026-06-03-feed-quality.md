# Feed Quality Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Починить 4 проблемы: авто-загрузка комментариев при клике, стабильный Instagram через fallback, черновики только для релевантных упоминаний, auto_collect включён по умолчанию.

**Architecture:** Все правки — точечные и минимальные. Бэкенд: `api.py` (комментарии уже авто-грузятся — проблема в медленном TikHub), `tikhub.py` (v3 fallback для IG), `collector.py` (_matches: keyword только в тексте, не в хэштегах), `api.py` onboarding (auto_collect=True). Фронт: Detail.jsx уже делает `useEffect` + `getComments` — нужно добавить loading state чтобы пользователь видел что идёт загрузка.

**Tech Stack:** FastAPI (Python), React 18, httpx, TikHub API

---

## File Map

**Модифицировать:**
- `backend/radar/providers/tikhub.py` — IG fallback v2→v3
- `backend/radar/collector.py` — `_matches`: keyword только в тексте
- `backend/radar/api.py` — `POST /onboarding`: auto_collect=True по умолчанию
- `echo-app/src/components/app/Detail.jsx` — loading state для комментариев

---

## Task 1: Instagram v3 fallback (стабильный IG-сбор)

**Files:**
- Modify: `backend/radar/providers/tikhub.py`

Текущее состояние: `_search_instagram()` использует только `v2/fetch_hashtag_posts`, который даёт 400 на каждый 2-3 запрос.
Решение: при 400 — retry через `v3/general_search` (другой путь, другой параметр `query` вместо `keyword`, другой формат ответа).

- [ ] **Шаг 1: Прочитай tikhub.py**

```bash
cat /Users/vovolypsi/Echo-v1/Echo-v1/backend/radar/providers/tikhub.py
```

- [ ] **Шаг 2: Заменить `_search_instagram` на версию с fallback**

Найди метод `def _search_instagram(self, query: str, cursor: Optional[str]) -> SearchPage:` и замени целиком:

```python
def _search_instagram(self, query: str, cursor: Optional[str]) -> SearchPage:
    # Cap at 1 page — IG pagination tokens expire immediately and cause 400.
    if cursor:
        return SearchPage(posts=[], next_cursor=None)
    kw = query.lstrip("#")
    # Try v2 first; fall back to v3/general_search on 400.
    try:
        resp = httpx.get(
            f"{BASE_URL}/api/v1/instagram/v2/fetch_hashtag_posts",
            headers=self._headers,
            params={"keyword": kw, "feed_type": "top"},
            timeout=25,
        )
        if resp.status_code == 400:
            raise httpx.HTTPStatusError("v2 400", request=resp.request, response=resp)
        resp.raise_for_status()
        body  = resp.json()
        data  = body.get("data", {}) or {}
        items = (data.get("data", {}) or {}).get("items", []) or []
        posts = [p for item in items if (p := self._safe_parse_ig(item)) is not None]
        return SearchPage(posts=posts, next_cursor=None)
    except httpx.HTTPStatusError:
        pass  # fall through to v3

    # v3/general_search fallback
    try:
        resp = httpx.get(
            f"{BASE_URL}/api/v1/instagram/v3/general_search",
            headers=self._headers,
            params={"query": kw, "enable_metadata": "True"},
            timeout=25,
        )
        resp.raise_for_status()
    except Exception as e:
        log.warning("IG v3 fallback failed for %r: %s", kw, e)
        return SearchPage(posts=[], next_cursor=None)

    body  = resp.json()
    data  = body.get("data", {}) or {}
    # v3 general_search returns mixed results: users, hashtags, posts
    # Posts are under data.medias or data.media_list or data.items
    items = (data.get("medias") or data.get("media_list") or
             data.get("items") or [])
    posts = [p for item in items if (p := self._safe_parse_ig(item)) is not None]
    return SearchPage(posts=posts, next_cursor=None)

def _safe_parse_ig(self, item: dict):
    """Parse an IG item dict into a Post, return None on any error."""
    try:
        return _parse_ig_post(item)
    except Exception:
        return None
```

- [ ] **Шаг 3: Проверить импорт**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/backend && python3 -c "from radar.providers.tikhub import TikHubProvider; print('OK')"
```

Ожидаемый вывод: `OK`

- [ ] **Шаг 4: Проверить что оба пути работают**

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
page = p.search('ozon', 'keyword', None, 'instagram')
print(f'IG posts: {len(page.posts)}')
if page.posts:
    print(f'  first: @{page.posts[0].author} | {page.posts[0].text[:50]!r}')
EOF
```

Ожидаемый вывод: `IG posts: 5+` (хотя бы несколько постов).

- [ ] **Шаг 5: Закоммитить**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1
git add backend/radar/providers/tikhub.py
git commit -m "fix: Instagram v3/general_search fallback when v2/fetch_hashtag_posts returns 400

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: _matches — keyword только в тексте, не в хэштегах (качество очереди)

**Files:**
- Modify: `backend/radar/collector.py`

Проблема: пост @galyawb рекламирует Wildberries, но пишет `#ozon #озон` в хэштегах → попадает в ленту Ozon, Claude генерирует черновик. Это нерелевантно.
Решение: для бренд-проб ключевые слова (`keywords`) должны совпадать только в тексте (не в хэштегах). Хэштеги бренда (`hashtags`) совпадают только с хэштегами поста. Competitor/niche правила не трогаем.

- [ ] **Шаг 1: Прочитай collector.py**

```bash
cat /Users/vovolypsi/Echo-v1/Echo-v1/backend/radar/collector.py
```

- [ ] **Шаг 2: Изменить _matches для brand source**

Найди функцию `def _matches(post: Post, brand: Brand, probe: Probe) -> bool:` и замени блок `if probe.source == "brand":`:

```python
    if probe.source == "brand":
        keywords      = [k.lower() for k in brand.keywords_list()]
        hashtags      = [h.lower().lstrip("#") for h in brand.hashtags_list()]
        post_hashtags = [h.lower().lstrip("#") for h in post.hashtags]
        # Strip hashtags from text so keyword match requires mention in caption body.
        text_no_tags  = " ".join(w for w in post.text.split() if not w.startswith("#")).lower()
        return (
            any(kw in text_no_tags for kw in keywords) or
            any(ht in post_hashtags for ht in hashtags)
        )
```

Изменение: `any(kw in text_lower for kw in keywords)` → `any(kw in text_no_tags for kw in keywords)`.
Keywords теперь ищутся только в тексте без хэштегов. Hashtags бренда по-прежнему матчатся с хэштегами поста.

- [ ] **Шаг 3: Проверить логику на примере**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/backend
python3 - <<'EOF'
import sys; sys.path.insert(0, '.')
from radar.collector import _matches
from radar.providers.base import Post
from radar.models import Brand
from datetime import datetime, timezone
import json

brand = Brand()
brand.keywords     = json.dumps(['ozon', 'озон'])
brand.hashtags     = json.dumps(['#ozon', '#озон'])
brand.exclusions   = json.dumps([])
brand.competitors  = json.dumps([])
brand.niche_keywords = json.dumps([])

class FakeProbe:
    source = 'brand'
    label  = None
    query  = 'ozon'

def post(text, hashtags):
    return Post(post_id='1', platform='tiktok', author='a', followers=0,
                text=text, hashtags=hashtags,
                created_at=datetime.now(timezone.utc), likes=0, views=0, comments=0, shares=0)

probe = FakeProbe()
# Should match: ozon in text
print('ozon in text:', _matches(post('купил на ozon вчера', []), brand, probe))
# Should NOT match: ozon only in hashtag
print('ozon only hashtag:', _matches(post('реклама Wildberries', ['ozon', 'вб']), brand, probe))
# Should match: brand hashtag #ozon in post hashtags
print('#ozon in hashtags:', _matches(post('смотрите платье', ['ozon', 'мода']), brand, probe))
EOF
```

Ожидаемый вывод:
```
ozon in text: True
ozon only hashtag: False
#ozon in hashtags: True
```

- [ ] **Шаг 4: Закоммитить**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1
git add backend/radar/collector.py
git commit -m "fix: brand keywords only match caption text, not hashtag-only posts

Prevents posts that spam #ozon/#озон in hashtags while promoting competitors
from appearing in the brand mention feed.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: auto_collect=True по умолчанию для новых брендов

**Files:**
- Modify: `backend/radar/api.py`

Сейчас `auto_collect` по умолчанию `False`. Новый пользователь создаёт бренд через визард и не получает данных пока не нажмёт кнопку вручную.

- [ ] **Шаг 1: Найти строку onboarding в api.py**

```bash
grep -n "auto_collect\|OnboardingBody\|def onboarding" /Users/vovolypsi/Echo-v1/Echo-v1/backend/radar/api.py | head -10
```

- [ ] **Шаг 2: Добавить auto_collect=True в Brand при onboarding**

Найди `def onboarding(` и блок создания Brand:

```python
    b = Brand(
        user_id=user.id,
        name=body.name,
        keywords=json.dumps(body.keywords),
        hashtags=json.dumps(body.hashtags),
        competitors=json.dumps(body.competitors),
        niche_keywords=json.dumps(body.niche_keywords),
    )
```

Замени на:

```python
    b = Brand(
        user_id=user.id,
        name=body.name,
        keywords=json.dumps(body.keywords),
        hashtags=json.dumps(body.hashtags),
        competitors=json.dumps(body.competitors),
        niche_keywords=json.dumps(body.niche_keywords),
        auto_collect=True,
    )
```

- [ ] **Шаг 3: Включить auto_collect для уже созданного Ozon**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/backend
python3 - <<'EOF'
from radar import db
from radar.models import Brand
s = db.get_session()
b = s.query(Brand).first()
if b:
    b.auto_collect = True
    s.commit()
    print(f"auto_collect={b.auto_collect} for brand '{b.name}'")
EOF
```

Ожидаемый вывод: `auto_collect=True for brand 'Ozon'`

- [ ] **Шаг 4: Проверить через API**

Перезапустить backend и убедиться что /brands возвращает auto_collect=true:

```bash
pkill -f "uvicorn radar.api" 2>/dev/null; sleep 1
cd /Users/vovolypsi/Echo-v1/Echo-v1/backend
for line in $(grep -E '^[A-Z_]+=.' .env); do export "$line"; done
nohup uvicorn radar.api:app --host 127.0.0.1 --port 8000 > /tmp/echo_backend.log 2>&1 &
sleep 5
python3 - <<'PYEOF'
import httpx, os
for line in open('.env'):
    line=line.strip()
    if '=' in line and not line.startswith('#'):
        k,v=line.split('=',1); os.environ[k]=v
r = httpx.post('http://127.0.0.1:8000/auth/login', json={'email':'demo@echo.app','password':'demo12345'}, timeout=10)
token = r.json()['token']
brands = httpx.get('http://127.0.0.1:8000/brands', headers={'Authorization': f'Bearer {token}'}, timeout=10).json()
print('auto_collect:', brands[0].get('auto_collect'))
PYEOF
```

Ожидаемый вывод: `auto_collect: True`

- [ ] **Шаг 5: Закоммитить**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1
git add backend/radar/api.py
git commit -m "feat: auto_collect=True by default for new brands on onboarding

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Loading state для комментариев в Detail.jsx

**Files:**
- Modify: `echo-app/src/components/app/Detail.jsx`

Проблема: комментарии загружаются через `getComments(item.id)` в useEffect, но нет спиннера — пользователь видит пустой список и думает что комментариев нет.
Решение: добавить `loadingComments` state, показывать «Загружаю комментарии…» пока идёт запрос.

- [ ] **Шаг 1: Прочитай Detail.jsx**

```bash
sed -n '100,145p' /Users/vovolypsi/Echo-v1/Echo-v1/echo-app/src/components/app/Detail.jsx
```

- [ ] **Шаг 2: Добавить loadingComments state и спиннер**

Найди в Detail.jsx:
```jsx
  const [comments, setComments] = useState(item.comments);
  const isReal = typeof item.id === 'number';
```

Замени на:
```jsx
  const [comments, setComments] = useState(item.comments);
  const [loadingComments, setLoadingComments] = useState(false);
  const isReal = typeof item.id === 'number';
```

Затем найди useEffect:
```jsx
  useEffect(() => {
    setComments(item.comments);
    if (!isReal) return;
    let alive = true;
    api.getComments(item.id)
      .then(data => { if (alive && Array.isArray(data) && data.length) setComments(data); })
      .catch(() => { /* keep fallback */ });
    return () => { alive = false; };
  }, [item.id]);
```

Замени на:
```jsx
  useEffect(() => {
    setComments(item.comments);
    if (!isReal) return;
    let alive = true;
    setLoadingComments(true);
    api.getComments(item.id)
      .then(data => {
        if (!alive) return;
        if (Array.isArray(data) && data.length) setComments(data);
      })
      .catch(() => {})
      .finally(() => { if (alive) setLoadingComments(false); });
    return () => { alive = false; };
  }, [item.id]);
```

Затем найди в JSX раздел `{/* Comments list */}` и добавь перед списком комментариев:
```jsx
      {/* Comments list */}
      {loadingComments && (
        <div style={{ padding: '12px 16px', fontSize: 12, color: 'var(--fg-4)' }}>
          Загружаю комментарии…
        </div>
      )}
```

- [ ] **Шаг 3: Проверить билд**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/echo-app && npm run build 2>&1 | tail -5
```

Ожидаемый вывод: `✓ built in ...ms`

- [ ] **Шаг 4: Закоммитить**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1
git add echo-app/src/components/app/Detail.jsx
git commit -m "feat: show loading state while comments fetch from TikHub

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Push + финальная проверка

- [ ] **Шаг 1: Push**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1 && git push origin main 2>&1 | tail -3
```

- [ ] **Шаг 2: Перезапустить backend если ещё не запущен**

```bash
pkill -f "uvicorn radar.api" 2>/dev/null; sleep 1
cd /Users/vovolypsi/Echo-v1/Echo-v1/backend
for line in $(grep -E '^[A-Z_]+=.' .env); do export "$line"; done
nohup uvicorn radar.api:app --host 127.0.0.1 --port 8000 > /tmp/echo_backend.log 2>&1 &
sleep 5
python3 -c "import httpx; print(httpx.get('http://127.0.0.1:8000/health',timeout=5).status_code)"
```

- [ ] **Шаг 3: Проверить IG-сбор**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/backend
python3 - <<'EOF'
import httpx; import os
for line in open('.env'):
    line=line.strip()
    if '=' in line and not line.startswith('#'):
        k,v=line.split('=',1); os.environ[k]=v
r = httpx.post('http://127.0.0.1:8000/auth/login', json={'email':'demo@echo.app','password':'demo12345'}, timeout=10)
token = r.json()['token']
r = httpx.get('http://127.0.0.1:8000/debug/tikhub?keyword=ozon&platform=instagram',
    headers={'Authorization': f'Bearer {token}'}, timeout=40)
print('IG debug:', r.status_code, 'posts:', r.json().get('posts_found', 0))
EOF
```

Ожидаемый вывод: `IG debug: 200 posts: 3+`

- [ ] **Шаг 4: Запустить сбор и проверить качество ленты**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/backend
python3 - <<'EOF'
import os, time
for line in open('.env'):
    line=line.strip()
    if '=' in line and not line.startswith('#'):
        k,v=line.split('=',1); os.environ[k]=v
import httpx
r = httpx.post('http://127.0.0.1:8000/auth/login', json={'email':'demo@echo.app','password':'demo12345'}, timeout=10)
token = r.json()['token']
headers = {'Authorization': f'Bearer {token}'}
brand_id = httpx.get('http://127.0.0.1:8000/brands', headers=headers, timeout=10).json()[0]['id']
httpx.post(f'http://127.0.0.1:8000/brands/{brand_id}/collect', headers=headers, timeout=10)
print('collect triggered')
EOF
```

Затем через 2 минуты: открыть http://localhost:5173, войти, проверить что:
- В ленте нет постов которые просто используют #ozon в хэштегах без упоминания в тексте
- Клик на пост показывает «Загружаю комментарии…» а затем реальные комментарии
- Scheduler автоматически собирает данные (auto_collect включён)

---

## Self-Review

**Spec coverage:**
- ✅ Комментарии авто-загрузка — Task 4 (loading state), комментарии уже грузятся через useEffect
- ✅ Instagram стабильный — Task 1 (v3 fallback)
- ✅ Качество очереди — Task 2 (keyword только в тексте)
- ✅ auto_collect по умолчанию — Task 3

**Placeholder scan:** Нет.

**Type consistency:** `SearchPage`, `Post` — из `base.py`, без изменений. `_safe_parse_ig` — новый метод в `TikHubProvider`. `loadingComments` — новый state в `DetailPanel`.
