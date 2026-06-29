# Точечная заглушка сигналов — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать куратору заглушать конкретный сюжет или целое направление, чтобы «дежурные» сюжеты перестали попадать в сигналы — не трогая источники и не снижая общую чувствительность.

**Architecture:** Два булевых флага (`IntelStory.muted`, `IntelDirection.muted`), идемпотентная миграция при старте, фильтрация в `scan_story_alerts`/`scan_direction_alerts`, REST-эндпоинты mute/unmute/list (удаляют существующие алерты при заглушке), и кнопки 🔕 в шторке сигналов и в карточке сюжета + секция «Заглушено» со снятием.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy / SQLite (backend); React + Vite (echo-app); pytest.

## Global Constraints

- Спека: `docs/superpowers/specs/2026-06-28-signal-mute-design.md`.
- Ветка: `feat/source-subject`.
- iCloud-репозиторий: **никогда `git add -A`** — стейджить только свои файлы по имени.
- Бэкенд-тесты: `python3 -m pytest` из каталога `backend/`.
- Перезапуск backend выполняет АССИСТЕНТ (`launchctl kickstart -k gui/$(id -u)/com.echo.backend`), не пользователь.
- Удаление существующих сигналов при заглушке — именно `DELETE` строк `IntelAlert`, не ack.
- `IntelMention.direction_id` остаётся NOT NULL (не трогаем).
- Сообщения коммитов завершаются строкой `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Заглушка постоянная, снимается вручную через UI (никакой авто-разглушки по времени — вне охвата).

---

### Task 1: Флаги `muted` + миграция + фильтрация скана

**Files:**
- Modify: `backend/radar/intel/models.py` (классы `IntelDirection` ~стр. 9-14, `IntelStory` ~стр. 71-87)
- Modify: `backend/radar/core/db.py` (словарь `_MIGRATIONS`, ~стр. 32-93)
- Modify: `backend/radar/intel/alerts.py` (`scan_story_alerts` ~стр. 67-81, `scan_direction_alerts` ~стр. 111-125)
- Test: `backend/tests/test_intel_alerts.py`

**Interfaces:**
- Produces: `IntelStory.muted: bool`, `IntelDirection.muted: bool` (оба default False).
- Produces: `scan_story_alerts(session)` и `scan_direction_alerts(session)` пропускают заглушённое — сигнатуры не меняются.
- Consumes: существующие хелперы тестов в `test_intel_alerts.py` — `_mem()`, `_direction(s, key, name)`, `_anomalous_story(s, direction_id)`.

- [ ] **Step 1: Написать падающие тесты**

В конец `backend/tests/test_intel_alerts.py` добавить:

```python
def test_scan_story_alerts_skips_muted_story():
    from radar.intel import alerts
    from radar.intel.models import IntelAlert
    s = _mem()
    d = _direction(s)
    st = _anomalous_story(s, d.id)
    st.muted = True
    s.flush()
    assert alerts.scan_story_alerts(s) == []
    assert s.query(IntelAlert).count() == 0


def test_scan_story_alerts_skips_story_under_muted_direction():
    from radar.intel import alerts
    from radar.intel.models import IntelAlert
    s = _mem()
    d = _direction(s)
    d.muted = True
    _anomalous_story(s, d.id)
    s.flush()
    assert alerts.scan_story_alerts(s) == []
    assert s.query(IntelAlert).count() == 0


def test_scan_direction_alerts_skips_muted_direction():
    from radar.intel import alerts
    from radar.intel.models import IntelAlert
    s = _mem()
    d = _direction(s)
    d.muted = True
    base = datetime(2026, 6, 20, 0, 0, tzinfo=timezone.utc)
    n = 0
    for h in range(3):
        _mention(s, d.id, base + timedelta(hours=h, minutes=1), f"b{n}"); n += 1
    for i in range(9):
        _mention(s, d.id, base + timedelta(hours=3, minutes=i), f"s{n}"); n += 1
    s.flush()
    assert alerts.scan_direction_alerts(s) == []
    assert s.query(IntelAlert).count() == 0
```

- [ ] **Step 2: Запустить — убедиться, что падают**

Run: `cd backend && python3 -m pytest tests/test_intel_alerts.py -k "muted" -v`
Expected: FAIL — `AttributeError: 'IntelStory' object has no attribute 'muted'` (атрибут ещё не объявлен).

- [ ] **Step 3: Добавить поля в модели**

В `backend/radar/intel/models.py`, в классе `IntelDirection` после строки `created_at: Mapped[datetime] = mapped_column(default=_now)` добавить:

```python
    muted:      Mapped[bool]     = mapped_column(Boolean, default=False, server_default="0")
```

В классе `IntelStory` сразу после строки с `is_anomaly:` добавить:

```python
    muted:            Mapped[bool]     = mapped_column(Boolean, default=False, server_default="0")
```

(`Boolean` уже импортирован в этом файле — используется в `is_anomaly`.)

- [ ] **Step 4: Зарегистрировать миграцию**

В `backend/radar/core/db.py`, в словарь `_MIGRATIONS` добавить две записи (рядом с существующей `"intel_probes"`):

```python
    "intel_stories": {
        "muted": "BOOLEAN NOT NULL DEFAULT 0",
    },
    "intel_directions": {
        "muted": "BOOLEAN NOT NULL DEFAULT 0",
    },
```

- [ ] **Step 5: Отфильтровать заглушённое в скане**

В `backend/radar/intel/alerts.py` заменить тело `scan_story_alerts` (запрос историй + цикл) на:

```python
def scan_story_alerts(session) -> list:
    """Emit an alert for every currently-anomalous active story (cooldown-deduped).
    Заглушённые сюжеты и сюжеты заглушённых направлений пропускаются."""
    out = []
    muted_dir_ids = {row[0] for row in
                     session.query(IntelDirection.id)
                     .filter(IntelDirection.muted.is_(True)).all()}
    stories = (session.query(IntelStory)
               .filter(IntelStory.is_anomaly.is_(True), IntelStory.status == "active",
                       IntelStory.muted.is_(False)).all())
    for st in stories:
        if st.direction_id in muted_dir_ids:
            continue
        pts = aggregate._points(session, st.id)
        kind, magnitude = _classify_story(pts)
        alert = _emit(session, "story", kind,
                      title=st.title or "",
                      message=_story_message(kind, magnitude, st.title or ""),
                      magnitude=magnitude, direction_id=st.direction_id, story_id=st.id)
        if alert is not None:
            out.append(alert)
    return out
```

В `scan_direction_alerts` заменить строку `if d.key == "unassigned":` на:

```python
        if d.key == "unassigned" or d.muted:
```

- [ ] **Step 6: Запустить тесты — убедиться, что проходят**

Run: `cd backend && python3 -m pytest tests/test_intel_alerts.py -v`
Expected: PASS (все, включая три новых и существующие emit/scan-тесты).

- [ ] **Step 7: Коммит**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1
git add backend/radar/intel/models.py backend/radar/core/db.py backend/radar/intel/alerts.py backend/tests/test_intel_alerts.py
git commit -m "feat(intel): mute flag on story/direction skips signal scan

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Эндпоинты mute/unmute/list + `direction_id` в payload

**Files:**
- Modify: `backend/radar/intel/api.py` (рядом с alert-эндпоинтами ~стр. 633-671)
- Modify: `backend/radar/intel/aggregate.py` (`alert_payload` ~стр. 256-263)
- Test: `backend/tests/test_intel_alerts.py`

**Interfaces:**
- Consumes: `IntelStory.muted`, `IntelDirection.muted` (Task 1); хелперы `_mem_threadsafe()`, `_client(session)`, `_direction(s)`, `_anomalous_story(s, id)` из `test_intel_alerts.py`.
- Produces (REST): `POST /intel/stories/{id}/mute`, `POST /intel/stories/{id}/unmute`, `POST /intel/directions/{id}/mute`, `POST /intel/directions/{id}/unmute`, `GET /intel/muted` → `{"stories":[{"id","title"}],"directions":[{"id","name"}]}`.
- Produces: `alert_payload` теперь содержит ключ `direction_id`.

- [ ] **Step 1: Написать падающие тесты**

В конец `backend/tests/test_intel_alerts.py` добавить:

```python
def test_mute_story_sets_flag_and_deletes_alerts():
    from radar.intel import alerts
    from radar.intel.models import IntelStory, IntelAlert
    s = _mem_threadsafe()
    d = _direction(s)
    st = _anomalous_story(s, d.id)
    alerts._emit(s, "story", "spike", title="t", message="m", magnitude=1.0,
                 direction_id=d.id, story_id=st.id)
    s.commit()
    c = _client(s)

    assert c.post(f"/intel/stories/{st.id}/mute").json()["ok"] is True
    s.expire_all()
    assert s.get(IntelStory, st.id).muted is True
    assert s.query(IntelAlert).filter_by(story_id=st.id).count() == 0

    assert c.post(f"/intel/stories/{st.id}/unmute").json()["ok"] is True
    s.expire_all()
    assert s.get(IntelStory, st.id).muted is False


def test_mute_direction_sets_flag_and_deletes_alerts():
    from radar.intel import alerts
    from radar.intel.models import IntelDirection, IntelAlert
    s = _mem_threadsafe()
    d = _direction(s)
    alerts._emit(s, "direction", "direction_burst", title="Курское",
                 message="Всплеск", magnitude=300.0, direction_id=d.id)
    s.commit()
    c = _client(s)

    assert c.post(f"/intel/directions/{d.id}/mute").json()["ok"] is True
    s.expire_all()
    assert s.get(IntelDirection, d.id).muted is True
    assert s.query(IntelAlert).filter_by(direction_id=d.id).count() == 0

    assert c.post(f"/intel/directions/{d.id}/unmute").json()["ok"] is True
    s.expire_all()
    assert s.get(IntelDirection, d.id).muted is False


def test_muted_list_returns_both():
    from radar.intel.models import IntelStory
    from datetime import datetime, timezone
    s = _mem_threadsafe()
    d = _direction(s)
    d.muted = True
    base = datetime(2026, 6, 20, tzinfo=timezone.utc)
    st = IntelStory(direction_id=d.id, title="заглушённый", muted=True,
                    first_seen_at=base, last_seen_at=base)
    s.add(st); s.commit()
    c = _client(s)

    body = c.get("/intel/muted").json()
    assert [x["title"] for x in body["stories"]] == ["заглушённый"]
    assert [x["name"] for x in body["directions"]] == ["Курское"]


def test_alert_payload_includes_direction_id():
    from radar.intel import alerts
    s = _mem_threadsafe()
    d = _direction(s)
    alerts._emit(s, "direction", "direction_burst", title="Курское",
                 message="Всплеск", magnitude=300.0, direction_id=d.id)
    s.commit()
    c = _client(s)
    listed = c.get("/intel/alerts?unread=true").json()
    assert listed[0]["direction_id"] == d.id
```

- [ ] **Step 2: Запустить — убедиться, что падают**

Run: `cd backend && python3 -m pytest tests/test_intel_alerts.py -k "mute or muted or payload_includes_direction" -v`
Expected: FAIL — 404 на новых маршрутах / `KeyError: 'direction_id'`.

- [ ] **Step 3: Добавить `direction_id` в payload**

В `backend/radar/intel/aggregate.py`, в `alert_payload`, в возвращаемый словарь добавить ключ `direction_id` (после `story_id`):

```python
    return {"id": a.id, "scope": a.scope, "story_id": a.story_id,
            "direction_id": a.direction_id,
            "direction": d.key if d else None, "kind": a.kind,
            "magnitude": a.magnitude, "title": a.title, "message": a.message,
            "at": _aware(a.fired_at).isoformat() if a.fired_at else None,
            "acknowledged": a.acknowledged_at is not None}
```

- [ ] **Step 4: Добавить эндпоинты mute/unmute/list**

В `backend/radar/intel/api.py` сразу после функции `intel_alert_ack` (~стр. 671) добавить. Убедиться, что `IntelStory` и `IntelDirection` импортированы в файле; если нет — добавить их в существующий импорт из `.models`.

```python
@router.post("/intel/stories/{story_id}/mute")
def intel_story_mute(
    story_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    """Заглушить сюжет: больше не сигналит + удалить его текущие алерты."""
    st = session.get(IntelStory, story_id)
    if st is None:
        raise HTTPException(404, "Story not found")
    st.muted = True
    session.query(IntelAlert).filter(IntelAlert.story_id == story_id).delete()
    session.commit()
    return {"ok": True}


@router.post("/intel/stories/{story_id}/unmute")
def intel_story_unmute(
    story_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    st = session.get(IntelStory, story_id)
    if st is None:
        raise HTTPException(404, "Story not found")
    st.muted = False
    session.commit()
    return {"ok": True}


@router.post("/intel/directions/{direction_id}/mute")
def intel_direction_mute(
    direction_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    """Заглушить направление: больше не сигналит + удалить все алерты этого направления."""
    d = session.get(IntelDirection, direction_id)
    if d is None:
        raise HTTPException(404, "Direction not found")
    d.muted = True
    session.query(IntelAlert).filter(IntelAlert.direction_id == direction_id).delete()
    session.commit()
    return {"ok": True}


@router.post("/intel/directions/{direction_id}/unmute")
def intel_direction_unmute(
    direction_id: int,
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    d = session.get(IntelDirection, direction_id)
    if d is None:
        raise HTTPException(404, "Direction not found")
    d.muted = False
    session.commit()
    return {"ok": True}


@router.get("/intel/muted")
def intel_muted(
    user: User = Depends(current_user),
    session: Session = Depends(db),
):
    stories = session.query(IntelStory).filter(IntelStory.muted.is_(True)).all()
    dirs = session.query(IntelDirection).filter(IntelDirection.muted.is_(True)).all()
    return {"stories": [{"id": s.id, "title": s.title} for s in stories],
            "directions": [{"id": d.id, "name": d.name} for d in dirs]}
```

- [ ] **Step 5: Запустить тесты — убедиться, что проходят**

Run: `cd backend && python3 -m pytest tests/test_intel_alerts.py -v`
Expected: PASS (все, включая четыре новых).

- [ ] **Step 6: Коммит**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1
git add backend/radar/intel/api.py backend/radar/intel/aggregate.py backend/tests/test_intel_alerts.py
git commit -m "feat(intel): mute/unmute/list endpoints + direction_id in alert payload

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: API-клиент + кнопка 🔕 в шторке сигналов + секция «Заглушено»

**Files:**
- Modify: `echo-app/src/features/intel/api.js` (объект `intelApi`, ~стр. 14-37)
- Modify: `echo-app/src/features/intel/components/AlertBell.jsx` (весь файл)
- Modify: `echo-app/src/features/intel/IntelApp.jsx` (состояние alerts ~стр. 45-90, рендер `<AlertBell ...>` ~стр. 151)

**Interfaces:**
- Consumes (REST из Task 2): `/intel/stories/{id}/mute|unmute`, `/intel/directions/{id}/mute|unmute`, `/intel/muted`; поле `direction_id` в объекте алерта.
- Produces: `intelApi.muteStory/unmuteStory/muteDirection/unmuteDirection/mutedList`.
- Produces: `<AlertBell>` принимает новые пропсы `onMute(alert)`, `muted` (`{stories,directions}`), `onUnmute(kind, id)`.

В этом репозитории фронтенд-юнит-тестов нет — проверка задачи — успешная сборка `npx vite build` и отсутствие ошибок в консоли. Это соответствует принятому в репо паттерну (так проверялись прошлые intel-фичи).

- [ ] **Step 1: Добавить методы в api.js**

В `echo-app/src/features/intel/api.js`, в объект `intelApi` (после строки с `hideMention:`) добавить:

```javascript
  muteStory:      (id) => request(`/intel/stories/${id}/mute`, { method: 'POST' }),
  unmuteStory:    (id) => request(`/intel/stories/${id}/unmute`, { method: 'POST' }),
  muteDirection:  (id) => request(`/intel/directions/${id}/mute`, { method: 'POST' }),
  unmuteDirection:(id) => request(`/intel/directions/${id}/unmute`, { method: 'POST' }),
  mutedList:      ()   => request('/intel/muted'),
```

- [ ] **Step 2: Перестроить AlertBell — строка-div + 🔕 + секция «Заглушено»**

Заменить содержимое `echo-app/src/features/intel/components/AlertBell.jsx` на:

```jsx
// Header notification bell: unread badge + dropdown of recent alerts + mute controls.
import { useState } from 'react';
import { Icon } from '../../../core/components/icons';
import { agoStrShort } from '../api';
import styles from '../intel.module.css';

export function AlertBell({ alerts = [], unreadCount = 0, onAck, onAckAll, onOpen,
                            onMute, muted = { stories: [], directions: [] }, onUnmute }) {
  const [open, setOpen] = useState(false);
  const [showMuted, setShowMuted] = useState(false);
  const mutedCount = (muted.stories?.length || 0) + (muted.directions?.length || 0);
  return (
    <div className={styles.bellWrap}>
      <button className={styles.bellBtn} onClick={() => setOpen(o => !o)} title="Сигналы">
        <Icon name="radio" size={15} />
        {unreadCount > 0 && <span className={styles.bellBadge}>{unreadCount > 99 ? '99+' : unreadCount}</span>}
      </button>
      {open && (
        <div className={styles.bellMenu}>
          <div className={styles.bellHead}>
            <span>Сигналы</span>
            {unreadCount > 0 && (
              <button className={styles.bellAckAll} onClick={() => onAckAll && onAckAll()}>
                Прочитать все
              </button>
            )}
          </div>
          {alerts.length === 0 ? (
            <div className={styles.bellEmpty}>Нет сигналов</div>
          ) : (
            alerts.slice(0, 30).map(a => (
              <div key={a.id} className={styles.bellItem} data-unread={a.acknowledged ? '0' : '1'}>
                <button className={styles.bellItemMain}
                        onClick={() => { onAck && onAck(a.id); onOpen && onOpen(a); setOpen(false); }}>
                  <span className={styles.bellItemMsg}>{a.message || a.title}</span>
                  <span className={styles.bellItemMeta}>{agoStrShort(a.at)}</span>
                </button>
                <button className={styles.bellMute}
                        title={a.scope === 'direction'
                          ? 'Не сигналить по этому направлению'
                          : 'Не сигналить по этому сюжету'}
                        onClick={() => onMute && onMute(a)}>🔕</button>
              </div>
            ))
          )}
          {mutedCount > 0 && (
            <div className={styles.bellMutedBox}>
              <button className={styles.bellMutedToggle} onClick={() => setShowMuted(v => !v)}>
                Заглушено ({mutedCount}) {showMuted ? '▾' : '▸'}
              </button>
              {showMuted && (
                <div className={styles.bellMutedList}>
                  {(muted.directions || []).map(d => (
                    <div key={`d${d.id}`} className={styles.bellMutedRow}>
                      <span className={styles.bellItemMsg}>📁 {d.name}</span>
                      <button className={styles.bellUnmute}
                              onClick={() => onUnmute && onUnmute('direction', d.id)}>вернуть</button>
                    </div>
                  ))}
                  {(muted.stories || []).map(st => (
                    <div key={`s${st.id}`} className={styles.bellMutedRow}>
                      <span className={styles.bellItemMsg}>{st.title}</span>
                      <button className={styles.bellUnmute}
                              onClick={() => onUnmute && onUnmute('story', st.id)}>вернуть</button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Подключить состояние и обработчики в IntelApp**

В `echo-app/src/features/intel/IntelApp.jsx`:

(a) Рядом с `const [alerts, setAlerts] = useState([]);` добавить:

```javascript
  const [muted, setMuted] = useState({ stories: [], directions: [] });
```

(b) В том же `useEffect`, где вызывается `intelApi.alerts(...)` (~стр. 51), добавить загрузку списка заглушённого:

```javascript
    intelApi.mutedList().then(setMuted).catch(() => {});
```

(c) Рядом с `ackAll` (~стр. 84-88) добавить обработчики mute/unmute:

```javascript
  const muteFromAlert = useCallback(async (a) => {
    // оптимистично убираем все сигналы того же объекта из ленты
    setAlerts(prev => prev.filter(x => a.scope === 'direction'
      ? x.direction_id !== a.direction_id
      : x.story_id !== a.story_id));
    try {
      if (a.scope === 'direction') await intelApi.muteDirection(a.direction_id);
      else await intelApi.muteStory(a.story_id);
      setMuted(await intelApi.mutedList());
    } catch { /* optimistic */ }
  }, []);

  const unmute = useCallback(async (kind, id) => {
    setMuted(prev => ({
      stories: kind === 'story' ? prev.stories.filter(s => s.id !== id) : prev.stories,
      directions: kind === 'direction' ? prev.directions.filter(d => d.id !== id) : prev.directions,
    }));
    try {
      if (kind === 'direction') await intelApi.unmuteDirection(id);
      else await intelApi.unmuteStory(id);
    } catch { /* optimistic */ }
  }, []);
```

(d) В рендере `<AlertBell ... />` (~стр. 151) добавить пропсы:

```jsx
          <AlertBell alerts={visibleAlerts} unreadCount={unreadCount} onAck={ackAlert} onAckAll={ackAll}
                     onOpen={openAlert} onMute={muteFromAlert} muted={muted} onUnmute={unmute} />
```

- [ ] **Step 4: Добавить стили**

В конец `echo-app/src/features/intel/intel.module.css` добавить (опираясь на существующие токены цветов проекта; значения ниже самодостаточны):

```css
.bellItem { display: flex; align-items: stretch; gap: 4px; }
.bellItemMain { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px;
  background: none; border: none; text-align: left; cursor: pointer; padding: 8px 10px; color: inherit; }
.bellMute, .bellUnmute { flex-shrink: 0; background: none; border: none; cursor: pointer;
  color: #4A6378; padding: 0 8px; font-size: 13px; }
.bellMute:hover { color: #e25a5a; }
.bellUnmute { font-size: 12px; }
.bellUnmute:hover { color: #6ea8ff; }
.bellMutedBox { border-top: 1px solid rgba(255,255,255,0.08); margin-top: 4px; }
.bellMutedToggle { width: 100%; text-align: left; background: none; border: none;
  color: #4A6378; cursor: pointer; padding: 8px 10px; font-size: 12px; }
.bellMutedList { display: flex; flex-direction: column; }
.bellMutedRow { display: flex; align-items: center; gap: 6px; padding: 4px 10px; }
.bellMutedRow .bellItemMsg { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
```

- [ ] **Step 5: Сборка — убедиться, что собирается без ошибок**

Run: `cd echo-app && npx vite build`
Expected: `✓ built in …` без ошибок компиляции/импорта.

- [ ] **Step 6: Коммит**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1
git add echo-app/src/features/intel/api.js echo-app/src/features/intel/components/AlertBell.jsx echo-app/src/features/intel/IntelApp.jsx echo-app/src/features/intel/intel.module.css
git commit -m "feat(intel): mute button in signals bell + muted list with unmute

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Кнопка 🔕 в карточке сюжета

**Files:**
- Modify: `echo-app/src/features/intel/components/IntelStories.jsx` (`deleteStory` ~стр. 60-69, карточка сюжета ~стр. 113-122)

**Interfaces:**
- Consumes: `intelApi.muteStory(id)` (Task 3).
- Produces: кнопка 🔕 в карточке сюжета, рядом с ✕-удалением; глушит сюжет и убирает его из списка.

Проверка задачи — успешная сборка `npx vite build` (фронтенд-юнит-тестов в репо нет).

- [ ] **Step 1: Добавить обработчик `muteStory`**

В `echo-app/src/features/intel/components/IntelStories.jsx`, сразу после функции `deleteStory` (~стр. 69) добавить:

```jsx
  function muteStory(id, ev) {
    ev.stopPropagation();
    setList(prev => prev.filter(s => s.id !== id));
    setSel(cur => (cur === id ? null : cur));
    intelApi.muteStory(id).catch(() => { /* optimistic */ });
  }
```

- [ ] **Step 2: Добавить кнопку в карточку сюжета**

В том же файле, в карточке сюжета, сразу после кнопки удаления (заканчивается на `>\n                ✕\n              </button>`, ~стр. 121) добавить кнопку 🔕 левее крестика:

```jsx
              <button
                onClick={(ev) => muteStory(s.id, ev)}
                title="Не сигналить по этому сюжету (источник остаётся)"
                style={{ position: 'absolute', top: 6, right: 24, background: 'none', border: 'none',
                         color: '#4A6378', cursor: 'pointer', fontSize: 12, lineHeight: 1, padding: 2 }}>
                🔕
              </button>
```

- [ ] **Step 3: Сборка — убедиться, что собирается без ошибок**

Run: `cd echo-app && npx vite build`
Expected: `✓ built in …` без ошибок.

- [ ] **Step 4: Коммит**

```bash
cd /Users/vovolypsi/Echo-v1/Echo-v1
git add echo-app/src/features/intel/components/IntelStories.jsx
git commit -m "feat(intel): mute button on story card (source kept)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Финал

После Task 4 ассистент перезапускает backend, чтобы применить миграцию `muted`:

```bash
launchctl kickstart -k gui/$(id -u)/com.echo.backend
```

Затем — `superpowers:finishing-a-development-branch` для ветки `feat/source-subject`.
