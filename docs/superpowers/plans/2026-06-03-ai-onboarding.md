# AI Onboarding & Real Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Убрать все мок-данные и PapaPizza, сделать 1 бренд на пользователя, добавить AI-визард для онбординга и редактирования настроек бренда.

**Architecture:** Два новых эндпоинта на бэке (`/brands/suggest` вызывает Claude, `/brands/preview` — TikHub без записи в БД). Фронт: AIWizard-модал в 2 шага (генерация → превью), AppPage рендерит визард если нет бренда, Shell упрощается до single-brand.

**Tech Stack:** FastAPI (Python), React 18 + Vite (JSX), httpx, Claude API (`claude-haiku-4-5-20251001`), TikHub

---

## File Map

**Модифицировать:**
- `backend/radar/seed.py` — удалить весь мок, оставить только `ensure_demo_user()`
- `backend/radar/api.py` — добавить `/brands/suggest`, `/brands/preview`, 409 в `/onboarding`
- `echo-app/src/services/api.js` — добавить `suggestBrand()`, `previewBrand()`
- `echo-app/src/pages/AppPage.jsx` — убрать FEED_ITEMS, мультибренд; показывать AIWizard если нет бренда
- `echo-app/src/components/app/Shell.jsx` — убрать мультибренд-дропдаун, только название + logout
- `echo-app/src/components/app/Settings.jsx` — убрать PapaPizza хардкод, добавить кнопку AI-визарда
- `echo-app/src/data/mock.js` — убрать `FEED_ITEMS` и `BRAND`, оставить `getLaneColor`/`getLaneLabel`

**Создать:**
- `echo-app/src/components/app/AIWizard.jsx`
- `echo-app/src/components/app/aiwizard.module.css`

---

## Task 1: Сбросить БД и очистить seed.py

**Files:**
- Modify: `backend/radar/seed.py`
- Delete: `backend/echo_radar.db` (сброс данных)

- [ ] **Шаг 1: Удалить БД для чистого старта**

```bash
rm -f /Users/vovolypsi/Echo-v1/Echo-v1/backend/echo_radar.db
echo "DB deleted"
```

- [ ] **Шаг 2: Переписать seed.py — только ensure_demo_user**

Заменить весь `backend/radar/seed.py` на:

```python
"""Seed: create demo account only. No brands, no mentions."""
from __future__ import annotations
from sqlalchemy.orm import Session
from .models import Brand, User
from .auth import hash_password

DEMO_EMAIL    = "demo@echo.app"
DEMO_PASSWORD = "demo12345"


def ensure_demo_user(session: Session) -> User:
    """Idempotent: create demo login and attach orphan brands to it."""
    user = session.query(User).filter_by(email=DEMO_EMAIL).first()
    if not user:
        user = User(email=DEMO_EMAIL, password_hash=hash_password(DEMO_PASSWORD))
        session.add(user)
        session.flush()
    for b in session.query(Brand).filter(Brand.user_id.is_(None)).all():
        b.user_id = user.id
    session.commit()
    return user
```

- [ ] **Шаг 3: Проверить что бэкенд стартует без ошибок**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/backend
python3 -c "from radar import seed; print('seed OK')"
```

Ожидаемый вывод: `seed OK`

- [ ] **Шаг 4: Перезапустить бэкенд**

```bash
pkill -f "uvicorn radar.api" 2>/dev/null; sleep 1
cd /Users/vovolypsi/Echo-v1/Echo-v1/backend
for line in $(grep -E '^[A-Z_]+=.' .env); do export "$line"; done
nohup uvicorn radar.api:app --host 127.0.0.1 --port 8000 > /tmp/echo_backend.log 2>&1 &
sleep 3
python3 -c "import httpx; r=httpx.get('http://127.0.0.1:8000/health',timeout=5); print('health:', r.status_code)"
```

Ожидаемый вывод: `health: 200`

- [ ] **Шаг 5: Проверить что нет брендов**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/backend
python3 -c "
from radar import db
from radar.models import Brand, Mention
s = db.get_session()
print('brands:', s.query(Brand).count())
print('mentions:', s.query(Mention).count())
"
```

Ожидаемый вывод: `brands: 0`, `mentions: 0`

- [ ] **Шаг 6: Закоммитить**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1
git add backend/radar/seed.py
git commit -m "feat: remove all mock data — seed only creates demo account

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Backend — POST /brands/suggest

**Files:**
- Modify: `backend/radar/api.py` (после `@app.post("/onboarding")`)

- [ ] **Шаг 1: Добавить SuggestBody и эндпоинт в api.py**

Найти строку `class OnboardingBody(BaseModel):` в `backend/radar/api.py` и добавить ПЕРЕД ней:

```python
# ── AI Brand Suggest ──────────────────────────────────────────────────────────

class SuggestBody(BaseModel):
    name: str

@app.post("/brands/suggest")
def suggest_brand(body: SuggestBody, user: User = Depends(current_user)):
    """Call Claude to suggest keywords/hashtags/competitors/niche for a brand name."""
    import httpx
    from .drafts import LLM_API_KEY, LLM_API_URL
    if not LLM_API_KEY:
        raise HTTPException(503, "LLM_API_KEY not configured")

    system = (
        "Ты эксперт по SMM и мониторингу брендов в русскоязычных соцсетях (TikTok, Instagram). "
        "Отвечай ТОЛЬКО валидным JSON без пояснений и markdown-блоков."
    )
    user_msg = (
        f'Для бренда "{body.name}" подбери для мониторинга в TikTok и Instagram: '
        f'5-7 ключевых слов (на русском и латинице, вариации написания бренда), '
        f'3-5 хэштегов (с #), '
        f'3-5 прямых конкурентов (только названия компаний), '
        f'3-5 нишевых терминов для мониторинга тематики. '
        f'Ответ строго в JSON: {{"keywords":[],"hashtags":[],"competitors":[],"niche_keywords":[]}}'
    )

    def _call():
        resp = httpx.post(
            LLM_API_URL,
            headers={"x-api-key": LLM_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 300,
                  "system": system, "messages": [{"role": "user", "content": user_msg}]},
            timeout=60,
        )
        resp.raise_for_status()
        blocks = resp.json().get("content", [])
        text = next((b["text"] for b in blocks if b.get("type") == "text"), "")
        # strip markdown code fences if present
        text = text.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(text)

    try:
        data = _call()
    except (json.JSONDecodeError, KeyError):
        # retry once with stricter instruction
        try:
            data = _call()
        except Exception as e:
            log.warning("suggest_brand retry failed: %s", e)
            raise HTTPException(502, "AI suggestion failed")
    except Exception as e:
        log.warning("suggest_brand failed: %s", e)
        raise HTTPException(502, "AI suggestion failed")

    return {
        "keywords":      data.get("keywords", []),
        "hashtags":      data.get("hashtags", []),
        "competitors":   data.get("competitors", []),
        "niche_keywords": data.get("niche_keywords", []),
    }
```

- [ ] **Шаг 2: Проверить импорт**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/backend
python3 -c "import radar.api; print('api import OK')"
```

Ожидаемый вывод: `api import OK`

- [ ] **Шаг 3: Проверить живой вызов (нужен запущенный бэкенд и действующий токен)**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/backend
python3 - <<'EOF'
import httpx, json, os
for line in open('.env'):
    line=line.strip()
    if '=' in line and not line.startswith('#'):
        k,v=line.split('=',1); os.environ[k]=v

# login
r = httpx.post('http://127.0.0.1:8000/auth/login',
    json={'email':'demo@echo.app','password':'demo12345'}, timeout=15)
token = r.json()['token']

# suggest
r = httpx.post('http://127.0.0.1:8000/brands/suggest',
    headers={'Authorization': f'Bearer {token}'},
    json={'name': 'Ozon'}, timeout=70)
print('status:', r.status_code)
data = r.json()
print('keywords:', data.get('keywords'))
print('competitors:', data.get('competitors'))
EOF
```

Ожидаемый вывод: `status: 200`, непустые массивы keywords и competitors.

- [ ] **Шаг 4: Закоммитить**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1
git add backend/radar/api.py
git commit -m "feat: POST /brands/suggest — Claude AI keyword/competitor suggestions

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Backend — POST /brands/preview

**Files:**
- Modify: `backend/radar/api.py`

- [ ] **Шаг 1: Добавить PreviewBody и эндпоинт в api.py**

Найти строку `class SuggestBody(BaseModel):` и добавить ПОСЛЕ блока `suggest_brand`:

```python
class PreviewBody(BaseModel):
    keywords:  list[str] = []
    platforms: list[str] = ["tiktok", "instagram"]

@app.post("/brands/preview")
def preview_brand(body: PreviewBody, user: User = Depends(current_user)):
    """Search TikHub with given keywords and return up to 5 real posts. Nothing is stored in DB."""
    provider = _get_provider()
    posts = []
    seen = set()
    for kw in body.keywords[:2]:
        for pf in body.platforms[:2]:
            if len(posts) >= 5:
                break
            try:
                page = provider.search(kw, "keyword", None, pf)
                for p in page.posts[:3]:
                    if p.post_id not in seen:
                        seen.add(p.post_id)
                        posts.append({
                            "post_id":  p.post_id,
                            "platform": p.platform,
                            "author":   p.author,
                            "views":    p.views,
                            "likes":    p.likes,
                            "text":     p.text[:120],
                        })
            except Exception as e:
                log.warning("preview_brand search failed kw=%s pf=%s: %s", kw, pf, e)
    return {"posts": posts[:5]}
```

- [ ] **Шаг 2: Проверить живой вызов**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/backend
python3 - <<'EOF'
import httpx, json, os
for line in open('.env'):
    line=line.strip()
    if '=' in line and not line.startswith('#'):
        k,v=line.split('=',1); os.environ[k]=v

r = httpx.post('http://127.0.0.1:8000/auth/login',
    json={'email':'demo@echo.app','password':'demo12345'}, timeout=15)
token = r.json()['token']

r = httpx.post('http://127.0.0.1:8000/brands/preview',
    headers={'Authorization': f'Bearer {token}'},
    json={'keywords': ['ozon', 'озон'], 'platforms': ['tiktok', 'instagram']},
    timeout=40)
print('status:', r.status_code)
data = r.json()
print('posts found:', len(data.get('posts', [])))
for p in data.get('posts', [])[:2]:
    print(f"  [{p['platform']}] @{p['author']} — {p['text'][:50]}")
EOF
```

Ожидаемый вывод: `status: 200`, `posts found: 3-5`, реальные посты.

- [ ] **Шаг 3: Добавить 409 в /onboarding если бренд уже есть**

Найти `@app.post("/onboarding")` и добавить проверку в начало функции:

```python
@app.post("/onboarding")
def onboarding(body: OnboardingBody, user: User = Depends(current_user), session: Session = Depends(db)):
    existing = session.query(Brand).filter_by(user_id=user.id).first()
    if existing:
        raise HTTPException(409, "Brand already exists")
    b = Brand(
        user_id=user.id,
        name=body.name,
        keywords=json.dumps(body.keywords),
        hashtags=json.dumps(body.hashtags),
        competitors=json.dumps(body.competitors),
        niche_keywords=json.dumps(body.niche_keywords),
    )
    session.add(b)
    session.flush()
    _rebuild_probes(session, b)
    session.commit()
    return _brand_card(b)
```

- [ ] **Шаг 4: Перезапустить бэкенд и проверить**

```bash
pkill -f "uvicorn radar.api" 2>/dev/null; sleep 1
cd /Users/vovolypsi/Echo-v1/Echo-v1/backend
for line in $(grep -E '^[A-Z_]+=.' .env); do export "$line"; done
nohup uvicorn radar.api:app --host 127.0.0.1 --port 8000 > /tmp/echo_backend.log 2>&1 &
sleep 3
python3 -c "import httpx; print(httpx.get('http://127.0.0.1:8000/health',timeout=5).status_code)"
```

- [ ] **Шаг 5: Закоммитить**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1
git add backend/radar/api.py
git commit -m "feat: POST /brands/preview (TikHub dry-run) + 409 on duplicate onboarding

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Frontend — убрать FEED_ITEMS мок

**Files:**
- Modify: `echo-app/src/data/mock.js`
- Modify: `echo-app/src/pages/AppPage.jsx`
- Modify: `echo-app/src/components/app/Analytics.jsx`
- Modify: `echo-app/src/components/app/Queue.jsx`
- Modify: `echo-app/src/components/app/Feed.jsx`

- [ ] **Шаг 1: Очистить mock.js — убрать FEED_ITEMS и BRAND, оставить helpers**

Заменить весь `echo-app/src/data/mock.js` на:

```js
// Helpers for lane display — used by Feed, Queue, Detail components.

export function getLaneColor(lane) {
  if (lane === 'competitor') return 'var(--warn)';
  if (lane === 'niche')      return 'var(--info, #6c8ebf)';
  return 'var(--brand)';
}

export function getLaneLabel(lane, competitor) {
  if (lane === 'competitor') return competitor ? `vs ${competitor}` : 'Конкурент';
  if (lane === 'niche')      return 'Ниша';
  return 'Мой бренд';
}
```

- [ ] **Шаг 2: Убрать FEED_ITEMS из AppPage.jsx**

В `echo-app/src/pages/AppPage.jsx`:
- Удалить строку: `import { FEED_ITEMS } from '../data/mock';`
- Изменить начальное состояние feedItems: `useState(FEED_ITEMS)` → `useState([])`
- В `selectBrand`: удалить `setFeedItems(FEED_ITEMS);`

- [ ] **Шаг 3: Убрать FEED_ITEMS из Analytics.jsx**

В `echo-app/src/components/app/Analytics.jsx`:
- Удалить строку: `import { FEED_ITEMS } from '../../data/mock';`
- Найти строку с `FEED_ITEMS` как фолбэк и заменить на `[]`:

```jsx
// Было:
: [...FEED_ITEMS].filter(v => v.lane === 'brand').sort(...)...
// Стало:
: []
```

- [ ] **Шаг 4: Убрать FEED_ITEMS из Queue.jsx**

В `echo-app/src/components/app/Queue.jsx`:
- Удалить строку: `import { FEED_ITEMS, getLaneColor, getLaneLabel } from '../../data/mock';`
- Добавить: `import { getLaneColor, getLaneLabel } from '../../data/mock';`
- Найти: `const raw = buildQueue(items ?? FEED_ITEMS);`
- Заменить на: `const raw = buildQueue(items ?? []);`

- [ ] **Шаг 5: Убрать FEED_ITEMS из Feed.jsx**

В `echo-app/src/components/app/Feed.jsx`:
- Изменить строку: `import { FEED_ITEMS, getLaneColor } from '../../data/mock';`
- На: `import { getLaneColor } from '../../data/mock';`
- Найти: `export function Feed({ items: allItems = FEED_ITEMS, selectedId, onSelect })`
- Заменить на: `export function Feed({ items: allItems = [], selectedId, onSelect })`

- [ ] **Шаг 6: Проверить компиляцию**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/echo-app
npm run build 2>&1 | tail -15
```

Ожидаемый вывод: успешный build без ошибок про `FEED_ITEMS`.

- [ ] **Шаг 7: Закоммитить**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1
git add echo-app/src/data/mock.js echo-app/src/pages/AppPage.jsx echo-app/src/components/app/Analytics.jsx echo-app/src/components/app/Queue.jsx echo-app/src/components/app/Feed.jsx
git commit -m "feat: remove FEED_ITEMS mock — components fall back to empty array

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Frontend — упростить Shell.jsx (убрать мультибренд)

**Files:**
- Modify: `echo-app/src/components/app/Shell.jsx`

- [ ] **Шаг 1: Заменить Sidebar на single-brand версию**

В `echo-app/src/components/app/Shell.jsx` найти экспорт `export function Sidebar({` и заменить всю функцию целиком:

```jsx
export function Sidebar({ screen, setScreen, brand, onLogout }) {
  const negCount = 3;

  return (
    <aside className={styles.sidebar}>
      <EchoLogo />
      <nav className={styles.nav}>
        <NavItem icon="radio"    label="Лента"     active={screen === 'feed'}      badge={negCount} onClick={() => setScreen('feed')} />
        <NavItem icon="inbox"    label="Очередь"   active={screen === 'queue'}     onClick={() => setScreen('queue')} />
        <NavItem icon="pieChart" label="Аналитика" active={screen === 'analytics'} onClick={() => setScreen('analytics')} />
        <NavItem icon="settings" label="Настройки" active={screen === 'settings'}  onClick={() => setScreen('settings')} />
      </nav>
      <div className={styles.sidebarBottom}>
        <div className={styles.brandChip} style={{ cursor: 'default' }}>
          <div className={styles.brandMonogram}>
            {brand?.name?.slice(0, 2).toUpperCase() ?? '—'}
          </div>
          <div style={{ lineHeight: 1.25, flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg-1)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {brand?.name ?? '—'}
            </div>
            <div style={{ fontSize: 11, color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}>
              {brand?.niche ?? ''}
            </div>
          </div>
          <button
            onClick={onLogout}
            title="Выйти"
            style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4, color: 'var(--fg-4)' }}
          >
            <Icon name="x" size={13} color="var(--fg-4)" />
          </button>
        </div>
      </div>
    </aside>
  );
}
```

- [ ] **Шаг 2: Закоммитить**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1
git add echo-app/src/components/app/Shell.jsx
git commit -m "feat: simplify Sidebar to single-brand (remove multi-brand dropdown)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Frontend — упростить AppPage.jsx (single brand + заглушка под визард)

**Files:**
- Modify: `echo-app/src/pages/AppPage.jsx`

- [ ] **Шаг 1: Переписать AppPage.jsx**

Заменить весь файл `echo-app/src/pages/AppPage.jsx`:

```jsx
import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Sidebar, TopBar } from '../components/app/Shell';
import { Feed } from '../components/app/Feed';
import { DetailPanel, EmptyDetail } from '../components/app/Detail';
import { QueueScreen } from '../components/app/Queue';
import { AnalyticsScreen } from '../components/app/Analytics';
import { SettingsScreen } from '../components/app/Settings';
import { AIWizard } from '../components/app/AIWizard';
import * as api from '../services/api';
import styles from '../components/app/shell.module.css';

function agoStr(isoString) {
  const mins = Math.round((Date.now() - new Date(isoString)) / 60000);
  if (mins < 1)    return 'только что';
  if (mins < 60)   return `${mins} мин`;
  if (mins < 1440) return `${Math.floor(mins / 60)} ч`;
  return `${Math.floor(mins / 1440)} д`;
}

function mentionToItem(m) {
  const lane = m.source || 'brand';
  const thumbnail =
    lane === 'competitor' ? 'competitor' :
    lane === 'niche'      ? 'niche' :
    m.tone === 'negative' ? 'neg' : 'neutral';
  return {
    id:              m.id,
    lane,
    competitor:      m.competitor || null,
    opportunity:     m.opportunity || null,
    platform:        m.platform,
    author:          m.author,
    authorFollowers: m.followers,
    ago:             agoStr(m.created_at),
    title:           m.text.length > 80 ? m.text.slice(0, 80) + '…' : m.text,
    summary:         m.text,
    views:           m.views,
    likes:           m.likes || 0,
    severity:        m.severity || 0,
    negativeCommentPct: m.tone === 'negative' ? 72 : 15,
    commentsCount:   m.comments || 0,
    thumbnail,
    url:             m.url || null,
    comments:        m.draft ? [{
      id:            `c_${m.id}`,
      author:        m.author,
      followers:     m.followers,
      text:          m.text,
      sentiment:     m.tone || 'neutral',
      pendingReply:  null,
      suggestedReply: m.draft,
      status:        m.status === 'sent' ? 'approved' : 'pending',
      likes:         m.likes || 0,
      minsAgo:       Math.round((Date.now() - new Date(m.created_at)) / 60000),
    }] : [],
    _mentionId: m.id,
    status:     m.status,
  };
}

export default function AppPage() {
  const navigate = useNavigate();
  const [screen, setScreen]         = useState('feed');
  const [selectedId, setSelectedId] = useState(null);
  const [brand, setBrand]           = useState(null);
  const [brandLoaded, setBrandLoaded] = useState(false);
  const [feedItems, setFeedItems]   = useState([]);
  const [collecting, setCollecting] = useState(false);
  const [showWizard, setShowWizard] = useState(false);
  const pollRef                     = useRef(null);

  const loadFeed = useCallback(async (brandId) => {
    try {
      const inbox = await api.getInbox(brandId);
      const all = [...inbox.pr, ...inbox.smm];
      setFeedItems(all.map(mentionToItem));
    } catch (e) {
      console.warn('Failed to load inbox:', e.message);
    }
  }, []);

  const loadBrand = useCallback(async () => {
    try {
      const list = await api.getBrands();
      if (list.length > 0) {
        setBrand(list[0]);
        loadFeed(list[0].id);
      }
    } catch (e) {
      console.warn('Backend unavailable');
    }
    setBrandLoaded(true);
  }, [loadFeed]);

  useEffect(() => { loadBrand(); }, [loadBrand]);
  useEffect(() => () => clearInterval(pollRef.current), []);

  function handleLogout() {
    api.logout();
    navigate('/login', { replace: true });
  }

  async function handleCollect() {
    if (!brand || collecting) return;
    setCollecting(true);
    try { await api.collectBrand(brand.id); } catch { setCollecting(false); return; }
    let ticks = 0;
    pollRef.current = setInterval(async () => {
      ticks++;
      await loadFeed(brand.id);
      if (ticks >= 6) { clearInterval(pollRef.current); setCollecting(false); }
    }, 3000);
  }

  async function handleBrandSaved(updatedBrand) {
    setBrand(updatedBrand);
    setShowWizard(false);
    if (updatedBrand?.id) await loadFeed(updatedBrand.id);
  }

  // No brand yet → show onboarding wizard fullscreen
  if (brandLoaded && !brand) {
    return (
      <AIWizard
        mode="create"
        onSaved={handleBrandSaved}
      />
    );
  }

  const selected = feedItems.find(i => i.id === selectedId) ?? null;

  return (
    <div className={styles.app}>
      <Sidebar
        screen={screen}
        setScreen={setScreen}
        brand={brand}
        onLogout={handleLogout}
      />
      <div className={styles.main}>
        <TopBar
          title={
            screen === 'feed'      ? 'Лента' :
            screen === 'queue'     ? 'Очередь ответов' :
            screen === 'analytics' ? 'Аналитика' : 'Настройки'
          }
          sub={screen === 'feed' ? 'Instagram · TikTok · Telegram · реальные данные' : undefined}
        >
          {brand && (
            <button
              onClick={handleCollect}
              disabled={collecting}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '7px 16px', borderRadius: 'var(--r-md)',
                background: collecting ? 'var(--surface-3)' : 'var(--brand)',
                color: collecting ? 'var(--fg-3)' : '#fff',
                border: 'none', cursor: collecting ? 'default' : 'pointer',
                fontSize: 13, fontWeight: 600, fontFamily: 'var(--font-sans)',
                transition: 'all 0.15s', whiteSpace: 'nowrap',
              }}
            >
              {collecting ? '⏳ Сбор данных…' : '⚡ Собрать данные'}
            </button>
          )}
        </TopBar>

        {screen === 'feed' ? (
          <div className={styles.workspace}>
            <Feed items={feedItems} selectedId={selectedId} onSelect={setSelectedId} />
            {selected ? <DetailPanel item={selected} /> : <EmptyDetail />}
          </div>
        ) : screen === 'queue' ? (
          <div className={styles.workspace}><QueueScreen items={feedItems} /></div>
        ) : screen === 'analytics' ? (
          <div className={styles.workspace}><AnalyticsScreen brandId={brand?.id} /></div>
        ) : (
          <div className={styles.workspace}>
            <SettingsScreen
              brand={brand}
              onBrandSaved={handleBrandSaved}
              onCollect={handleCollect}
              collecting={collecting}
              onOpenWizard={() => setShowWizard(true)}
            />
          </div>
        )}
      </div>

      {showWizard && (
        <AIWizard
          mode="edit"
          brand={brand}
          onSaved={handleBrandSaved}
          onClose={() => setShowWizard(false)}
        />
      )}
    </div>
  );
}
```

- [ ] **Шаг 2: Закоммитить**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1
git add echo-app/src/pages/AppPage.jsx
git commit -m "feat: AppPage single-brand, show AIWizard when no brand exists

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Frontend — api.js новые эндпоинты

**Files:**
- Modify: `echo-app/src/services/api.js`

- [ ] **Шаг 1: Добавить suggestBrand и previewBrand в api.js**

В конец файла `echo-app/src/services/api.js` добавить:

```js
export const suggestBrand = (name) =>
  request('/brands/suggest', {
    method: 'POST',
    body: JSON.stringify({ name }),
  });

export const previewBrand = (keywords, platforms = ['tiktok', 'instagram']) =>
  request('/brands/preview', {
    method: 'POST',
    body: JSON.stringify({ keywords, platforms }),
  });
```

- [ ] **Шаг 2: Закоммитить**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1
git add echo-app/src/services/api.js
git commit -m "feat: add suggestBrand and previewBrand API helpers

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Frontend — Settings.jsx убрать PapaPizza хардкод + кнопка AI

**Files:**
- Modify: `echo-app/src/components/app/Settings.jsx`

- [ ] **Шаг 1: Убрать PapaPizza дефолты и добавить проп onOpenWizard**

В `echo-app/src/components/app/Settings.jsx`:

1. Изменить строку экспорта:
```jsx
// Было:
export function SettingsScreen({ brand, onBrandSaved, onCollect, collecting }) {
// Стало:
export function SettingsScreen({ brand, onBrandSaved, onCollect, collecting, onOpenWizard }) {
```

2. Заменить все хардкодные начальные значения:
```jsx
// Было:
const [brandName,      setBrandName]      = useState('PapaPizza');
const [brandNiche,     setBrandNiche]     = useState('Доставка еды, пиццерия');
const [brandInstagram, setBrandInstagram] = useState('@papapizza_ru');
const [brandTiktok,    setBrandTiktok]    = useState('@papapizza');
const [brandWebsite,   setBrandWebsite]   = useState('papapizza.ru');
const [keywords,   setKeywords]   = useState(['папапицца', 'papapizza', 'papa pizza', 'пицца доставка мск']);
const [hashtags,   setHashtags]   = useState(['#папапицца', '#papapizza', '#пиццамосква']);
const [exclusions, setExclusions] = useState(['домино', 'додо', 'рецепт пицца']);
const [competitors, setCompetitors] = useState(['DoDo Pizza', 'Dominos', 'Pizza Hut']);
const [niche, setNiche] = useState(['доставка пиццы москва', 'лучшая пицца']);
// Стало:
const [brandName,      setBrandName]      = useState('');
const [brandNiche,     setBrandNiche]     = useState('');
const [brandInstagram, setBrandInstagram] = useState('');
const [brandTiktok,    setBrandTiktok]    = useState('');
const [brandWebsite,   setBrandWebsite]   = useState('');
const [keywords,   setKeywords]   = useState([]);
const [hashtags,   setHashtags]   = useState([]);
const [exclusions, setExclusions] = useState([]);
const [competitors, setCompetitors] = useState([]);
const [niche, setNiche] = useState([]);
```

3. Найти в JSX заголовок секции «Мониторинг» или «Ключевые слова» и добавить кнопку рядом с ним. Найти тег `<Section title="Ключевые слова"` (или аналогичный первый раздел настроек мониторинга) и добавить перед ним кнопку AI:

```jsx
<div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
  <span style={{ fontSize: 13, color: 'var(--fg-2)' }}>Ключевые слова, конкуренты и ниша</span>
  <button
    onClick={onOpenWizard}
    style={{
      display: 'flex', alignItems: 'center', gap: 6,
      padding: '6px 12px', borderRadius: 'var(--r-md)',
      background: 'var(--surface-3)', border: '1px solid var(--line-2)',
      color: 'var(--fg-1)', cursor: 'pointer', fontSize: 12, fontWeight: 600,
      fontFamily: 'var(--font-sans)',
    }}
  >
    ✨ AI-заполнение
  </button>
</div>
```

- [ ] **Шаг 2: Закоммитить**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1
git add echo-app/src/components/app/Settings.jsx
git commit -m "feat: remove PapaPizza hardcodes from Settings, add AI wizard button

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: Frontend — AIWizard.jsx + aiwizard.module.css

**Files:**
- Create: `echo-app/src/components/app/AIWizard.jsx`
- Create: `echo-app/src/components/app/aiwizard.module.css`

- [ ] **Шаг 1: Создать aiwizard.module.css**

```css
/* echo-app/src/components/app/aiwizard.module.css */

.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 24px;
}

.modal {
  background: var(--surface-1);
  border: 1px solid var(--line-2);
  border-radius: var(--r-lg);
  width: 100%;
  max-width: 560px;
  max-height: 85vh;
  overflow-y: auto;
  padding: 28px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* Fullscreen for create mode */
.fullscreen {
  position: fixed;
  inset: 0;
  background: var(--surface-0);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  z-index: 50;
}

.card {
  background: var(--surface-1);
  border: 1px solid var(--line-2);
  border-radius: var(--r-lg);
  width: 100%;
  max-width: 520px;
  padding: 32px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.header {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.title {
  font-size: 20px;
  font-weight: 700;
  color: var(--fg-1);
}

.sub {
  font-size: 13px;
  color: var(--fg-3);
}

.nameRow {
  display: flex;
  gap: 8px;
}

.nameInput {
  flex: 1;
  padding: 10px 14px;
  border-radius: var(--r-md);
  border: 1px solid var(--line-2);
  background: var(--surface-2);
  color: var(--fg-1);
  font-size: 14px;
  font-family: var(--font-sans);
  outline: none;
}

.nameInput:focus {
  border-color: var(--brand);
}

.suggestBtn {
  padding: 10px 18px;
  border-radius: var(--r-md);
  background: var(--brand);
  color: #fff;
  border: none;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  font-family: var(--font-sans);
  white-space: nowrap;
  transition: opacity 0.15s;
}

.suggestBtn:disabled {
  opacity: 0.5;
  cursor: default;
}

.section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.sectionLabel {
  font-size: 12px;
  font-weight: 600;
  color: var(--fg-3);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-height: 32px;
}

.tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 500;
  background: var(--brand-dim, rgba(99,102,241,0.12));
  color: var(--brand-bright, #818cf8);
  border: 1px solid var(--brand-dim, rgba(99,102,241,0.2));
}

.tagX {
  background: none;
  border: none;
  cursor: pointer;
  padding: 0;
  color: inherit;
  opacity: 0.6;
  font-size: 11px;
  line-height: 1;
}

.empty {
  font-size: 13px;
  color: var(--fg-4);
  padding: 4px 0;
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 4px;
}

.cancelBtn {
  padding: 9px 18px;
  border-radius: var(--r-md);
  border: 1px solid var(--line-2);
  background: var(--surface-2);
  color: var(--fg-2);
  cursor: pointer;
  font-size: 13px;
  font-family: var(--font-sans);
}

.nextBtn {
  padding: 9px 18px;
  border-radius: var(--r-md);
  border: none;
  background: var(--brand);
  color: #fff;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  font-family: var(--font-sans);
  transition: opacity 0.15s;
}

.nextBtn:disabled {
  opacity: 0.4;
  cursor: default;
}

.previewList {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.previewCard {
  padding: 10px 14px;
  border-radius: var(--r-md);
  border: 1px solid var(--line-2);
  background: var(--surface-2);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.previewMeta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--fg-3);
}

.previewText {
  font-size: 12px;
  color: var(--fg-2);
  line-height: 1.4;
}

.platformBadge {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--surface-3);
  color: var(--fg-2);
  text-transform: uppercase;
}

.toast {
  padding: 10px 14px;
  border-radius: var(--r-md);
  background: var(--surface-3);
  border: 1px solid var(--warn, #f59e0b);
  color: var(--warn, #f59e0b);
  font-size: 12px;
}

.spinner {
  display: inline-block;
  width: 16px;
  height: 16px;
  border: 2px solid var(--line-2);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
  vertical-align: middle;
  margin-right: 6px;
}

@keyframes spin { to { transform: rotate(360deg); } }
```

- [ ] **Шаг 2: Создать AIWizard.jsx**

```jsx
// echo-app/src/components/app/AIWizard.jsx
import { useState } from 'react';
import * as api from '../../services/api';
import styles from './aiwizard.module.css';

/**
 * AIWizard — 2-step brand setup wizard.
 *
 * mode="create" → fullscreen onboarding, calls POST /onboarding
 * mode="edit"   → modal overlay, calls POST /brands/:id/config
 *
 * Props:
 *   mode:    "create" | "edit"
 *   brand:   brand object (edit mode only)
 *   onSaved: (updatedBrand) => void
 *   onClose: () => void (edit mode only)
 */
export function AIWizard({ mode, brand, onSaved, onClose }) {
  const [step, setStep]           = useState(1);         // 1 = generate, 2 = preview
  const [name, setName]           = useState(brand?.name ?? '');
  const [keywords, setKeywords]   = useState(brand?.keywords ?? []);
  const [hashtags, setHashtags]   = useState(brand?.hashtags ?? []);
  const [competitors, setCompetitors] = useState(brand?.competitors ?? []);
  const [niche, setNiche]         = useState(brand?.niche_keywords ?? []);
  const [previews, setPreviews]   = useState([]);

  const [suggesting, setSuggesting] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [saving, setSaving]       = useState(false);
  const [toast, setToast]         = useState('');

  function showToast(msg) {
    setToast(msg);
    setTimeout(() => setToast(''), 4000);
  }

  async function handleSuggest() {
    if (!name.trim()) return;
    setSuggesting(true);
    setToast('');
    try {
      const data = await api.suggestBrand(name.trim());
      if (data.keywords?.length)      setKeywords(data.keywords);
      if (data.hashtags?.length)      setHashtags(data.hashtags);
      if (data.competitors?.length)   setCompetitors(data.competitors);
      if (data.niche_keywords?.length) setNiche(data.niche_keywords);
      if (!data.keywords?.length && !data.competitors?.length) {
        showToast('AI не смог подобрать автоматически — заполните вручную.');
      }
    } catch {
      showToast('AI недоступен — заполните поля вручную и нажмите «Далее».');
    } finally {
      setSuggesting(false);
    }
  }

  async function handlePreview() {
    if (keywords.length === 0) { setStep(2); return; }
    setPreviewing(true);
    setToast('');
    try {
      const data = await api.previewBrand(keywords.slice(0, 2));
      setPreviews(data.posts ?? []);
    } catch {
      showToast('Превью недоступно — но можно сохранить без него.');
      setPreviews([]);
    } finally {
      setPreviewing(false);
      setStep(2);
    }
  }

  async function handleSave() {
    if (!name.trim()) return;
    setSaving(true);
    try {
      let result;
      if (mode === 'create') {
        result = await api.createBrand(name.trim(), keywords, hashtags, competitors, niche);
        // kick off background collect — don't block
        api.collectBrand(result.id).catch(() => {});
      } else {
        await api.updateBrandConfig(brand.id, {
          name: name.trim(), keywords, hashtags,
          exclusions: brand.exclusions ?? [],
          competitors, niche_keywords: niche,
        });
        result = { ...brand, name: name.trim(), keywords, hashtags, competitors, niche_keywords: niche };
      }
      onSaved?.(result);
    } catch (e) {
      showToast(`Ошибка сохранения: ${e.message}`);
    } finally {
      setSaving(false);
    }
  }

  function removeTag(list, setList, tag) {
    setList(list.filter(t => t !== tag));
  }

  function TagGroup({ label, list, setList }) {
    return (
      <div className={styles.section}>
        <div className={styles.sectionLabel}>{label}</div>
        <div className={styles.tags}>
          {list.length === 0
            ? <span className={styles.empty}>Пусто</span>
            : list.map(t => (
              <span key={t} className={styles.tag}>
                {t}
                <button className={styles.tagX} onClick={() => removeTag(list, setList, t)}>✕</button>
              </span>
            ))}
        </div>
      </div>
    );
  }

  const inner = (
    <>
      <div className={styles.header}>
        <div className={styles.title}>
          {mode === 'create' ? '✨ Настройка бренда' : '✨ AI-заполнение'}
        </div>
        <div className={styles.sub}>
          {step === 1
            ? 'Введите название бренда — AI подберёт ключевые слова, конкурентов и нишу'
            : 'Реальные посты по вашим ключевым словам'}
        </div>
      </div>

      {step === 1 && (
        <>
          <div className={styles.nameRow}>
            <input
              className={styles.nameInput}
              value={name}
              onChange={e => setName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSuggest()}
              placeholder="Название бренда (например: Ozon)"
              autoFocus
            />
            <button
              className={styles.suggestBtn}
              onClick={handleSuggest}
              disabled={!name.trim() || suggesting}
            >
              {suggesting ? <><span className={styles.spinner} />Подбираю…</> : 'Подобрать'}
            </button>
          </div>

          {toast && <div className={styles.toast}>{toast}</div>}

          <TagGroup label="Ключевые слова" list={keywords} setList={setKeywords} />
          <TagGroup label="Хэштеги"        list={hashtags}  setList={setHashtags} />
          <TagGroup label="Конкуренты"     list={competitors} setList={setCompetitors} />
          <TagGroup label="Ниша"           list={niche}     setList={setNiche} />

          <div className={styles.actions}>
            {mode === 'edit' && (
              <button className={styles.cancelBtn} onClick={onClose}>Отмена</button>
            )}
            <button
              className={styles.nextBtn}
              onClick={handlePreview}
              disabled={previewing || keywords.length === 0}
            >
              {previewing ? <><span className={styles.spinner} />Загружаю…</> : 'Предпросмотр постов →'}
            </button>
          </div>
        </>
      )}

      {step === 2 && (
        <>
          {toast && <div className={styles.toast}>{toast}</div>}

          {previews.length > 0 ? (
            <div className={styles.previewList}>
              {previews.map((p, i) => (
                <div key={i} className={styles.previewCard}>
                  <div className={styles.previewMeta}>
                    <span className={styles.platformBadge}>{p.platform}</span>
                    <span>@{p.author}</span>
                    {p.views > 0 && <span>{(p.views / 1000).toFixed(1)}k просм.</span>}
                  </div>
                  <div className={styles.previewText}>{p.text}</div>
                </div>
              ))}
            </div>
          ) : (
            <div className={styles.empty}>Превью недоступно — можно сохранить без него.</div>
          )}

          <div className={styles.actions}>
            <button className={styles.cancelBtn} onClick={() => setStep(1)}>← Назад</button>
            <button className={styles.nextBtn} onClick={handleSave} disabled={saving}>
              {saving ? <><span className={styles.spinner} />Сохраняю…</> :
               mode === 'create' ? 'Создать бренд' : 'Применить'}
            </button>
          </div>
        </>
      )}
    </>
  );

  if (mode === 'create') {
    return (
      <div className={styles.fullscreen}>
        <div className={styles.card}>{inner}</div>
      </div>
    );
  }

  return (
    <div className={styles.overlay}>
      <div className={styles.modal}>{inner}</div>
    </div>
  );
}
```

- [ ] **Шаг 3: Обновить createBrand в api.js чтобы передавать competitors и niche_keywords**

В `echo-app/src/services/api.js` найти `export const createBrand` и заменить:

```js
export const createBrand = (name, keywords = [], hashtags = [], competitors = [], niche_keywords = []) =>
  request('/onboarding', {
    method: 'POST',
    body: JSON.stringify({ name, keywords, hashtags, competitors, niche_keywords }),
  });
```

- [ ] **Шаг 4: Проверить компиляцию**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/echo-app
npm run build 2>&1 | tail -20
```

Ожидаемый вывод: успешный build без ошибок.

- [ ] **Шаг 5: Закоммитить**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1
git add echo-app/src/components/app/AIWizard.jsx echo-app/src/components/app/aiwizard.module.css echo-app/src/services/api.js
git commit -m "feat: AIWizard — 2-step brand setup with Claude suggestions + TikHub preview

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: Финальная проверка и пуш

- [ ] **Шаг 1: Запустить фронтенд и проверить онбординг нового пользователя**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1/echo-app
npm run dev
```

Открыть http://localhost:5173, зарегистрировать нового пользователя → убедиться что показывается AIWizard.

- [ ] **Шаг 2: Проверить demo@echo.app (без бренда)**

Войти как `demo@echo.app` / `demo12345` → должен открыться AIWizard (бренда нет).

- [ ] **Шаг 3: Пройти визард**

В поле «Название бренда» ввести «Ozon» → нажать «Подобрать» → дождаться Claude → нажать «Предпросмотр постов» → нажать «Создать бренд» → проверить что открылась основная лента.

- [ ] **Шаг 4: Проверить Settings «AI-заполнение»**

Перейти в Настройки → нажать «✨ AI-заполнение» → пройти визард в режиме edit → нажать «Применить».

- [ ] **Шаг 5: Закоммитить всё оставшееся и запушить**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1
git push origin main
```

---

## Self-Review

**Spec coverage:**
- ✅ seed.py очищен (Task 1)
- ✅ POST /brands/suggest (Task 2)
- ✅ POST /brands/preview (Task 3)
- ✅ 409 в /onboarding (Task 3)
- ✅ FEED_ITEMS убран (Task 4)
- ✅ Shell упрощён (Task 5)
- ✅ AppPage single-brand + визард при отсутствии бренда (Task 6)
- ✅ api.js новые эндпоинты (Task 7)
- ✅ Settings без PapaPizza + кнопка AI (Task 8)
- ✅ AIWizard компонент (Task 9)

**Типы согласованы:**
- `createBrand(name, keywords, hashtags, competitors, niche_keywords)` — Task 7 и Task 9 используют одну сигнатуру
- `AIWizard` получает `{ mode, brand, onSaved, onClose }` — Task 6 (AppPage) и Task 8 (Settings) вызывают с теми же props
- `onBrandSaved(updatedBrand)` — во всех местах одинаково
