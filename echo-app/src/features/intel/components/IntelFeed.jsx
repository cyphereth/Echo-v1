// Лента событий v2 — TweetDeck-style multi-column live feed.
// One column per direction; posts land by source-subscription OR geo-text match.
// Up to ~8 columns visible; layout persists to localStorage with a backend
// "боевой дефолт" fallback.
import { useCallback, useEffect, useRef, useState } from 'react';
import { intelApi } from '../api';
import { FeedColumn } from './FeedColumn';
import { ColumnPicker } from './ColumnPicker';
import styles from '../intel.module.css';

const LS_KEY = 'echo.intel.feed.columns';

// Ключ треда: настоящий корень (thread_root_id), иначе сам пост — свой корень.
const threadKey = (e) => e.thread_root_id ?? e.id;

// Свернуть плоский список событий (newest-first) в тредовые карточки.
// Якорь = ПЕРВЫЙ увиденный пост треда (по времени), последующие ответы копятся
// в _thread. Карточки сортируются по последней активности (свежие сверху).
function groupThreads(events) {
  const byKey = new Map();
  for (const e of [...events].reverse()) {   // oldest → newest, чтобы якорь = первый
    const k = threadKey(e);
    const card = byKey.get(k);
    if (!card) byKey.set(k, { ...e, _tkey: k, _thread: [], _last: e.created_at });
    else if (card.id !== e.id && !card._thread.some(r => r.id === e.id)) {
      card._thread.push(e);
      card._last = e.created_at;
    }
  }
  return [...byKey.values()].sort((a, b) => (b._last > a._last ? 1 : b._last < a._last ? -1 : 0));
}
const WINDOWS = [['1h', '1ч'], ['24h', '24ч'], ['7d', '7д']];
const SIDES = [[null, '🇷🇺+🇺🇦'], ['ru', '🇷🇺'], ['ua', '🇺🇦']];

export function IntelFeed() {
  const [allDirs, setAllDirs]         = useState([]);
  const [activeKeys, setActiveKeys]   = useState([]);
  const [win, setWin]                 = useState('24h');
  const [side, setSide]               = useState(null);
  const [showRadar, setShowRadar]     = useState(false);  // включать радарные источники в общую ленту
  const [expandThreads, setExpandThreads] = useState(false); // развернуть треды во всех колонках
  const [eventsByKey, setEventsByKey] = useState({});
  const [hiddenIds, setHiddenIds]     = useState(() => new Set());
  const [pausedKeys, setPausedKeys]   = useState(() => new Set()); // колонки под курсором
  const [bufCounts, setBufCounts]     = useState({});              // сколько событий ждёт во время паузы
  const esRef        = useRef(null);
  const pausedRef    = useRef(new Set()); // актуальное состояние для SSE-колбэка
  const bufferRef    = useRef({});        // {key: [событие,...]} — буфер на время паузы

  // В спам: оптимистично прячем пост во всех колонках + запоминаем как пример мусора.
  const handleSpam = useCallback((e, ev) => {
    ev.stopPropagation();
    setHiddenIds(prev => { const n = new Set(prev); n.add(e.id); return n; });
    Promise.all([
      intelApi.addSpam({ kind: 'example', value: e.text || '', author: e.author || null, source_post_id: e.post_id || null }),
      intelApi.hideMention(e.id),
    ]).catch(() => { /* optimistic — пост остаётся скрытым в любом случае */ });
  }, []);

  // Load direction catalog + initial layout (localStorage → backend default).
  useEffect(() => {
    intelApi.directions().then(setAllDirs).catch(() => {});
    const stored = localStorage.getItem(LS_KEY);
    let parsed = null;
    if (stored) {
      try { parsed = JSON.parse(stored); } catch { parsed = null; }
    }
    // Если в localStorage что-то есть и не пусто — используем.
    if (parsed && parsed.length > 0) {
      setActiveKeys(parsed);
      return;
    }
    // Иначе спрашиваем backend (там боевой дефолт или сохранённый admin-расклад).
    intelApi.getLayout().then(l => {
      const keys = l.direction_keys || [];
      setActiveKeys(keys);
      if (keys.length) localStorage.setItem(LS_KEY, JSON.stringify(keys));
    }).catch(() => {});
  }, []);

  // Persist to localStorage on change.
  useEffect(() => {
    if (activeKeys.length) localStorage.setItem(LS_KEY, JSON.stringify(activeKeys));
  }, [activeKeys]);

  const dirByName = Object.fromEntries(allDirs.map(d => [d.key, d]));

  // Initial history per column when the set of columns or filters change.
  useEffect(() => {
    setEventsByKey({});
    let alive = true;
    Promise.all(activeKeys.map(k =>
      intelApi.feed(k, { window: win, side, include_radar: showRadar || undefined }).then(rows => [k, groupThreads(rows)]).catch(() => [k, []])
    )).then(pairs => { if (alive) setEventsByKey(Object.fromEntries(pairs)); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeKeys.join(','), win, side, showRadar]);

  // Влить одно событие в колонку. Если тред уже в колонке — не плодим строку, а
  // подклеиваем ответ к якорной карточке, поднимаем её наверх и мигаем. Иначе —
  // новая карточка сверху. Подсветку снимаем через 1.2с.
  const applyEvent = useCallback((ev) => {
    const k = threadKey(ev);
    setEventsByKey(prev => {
      const list = prev[ev.direction] || [];
      const idx = list.findIndex(c => c._tkey === k);
      if (idx >= 0) {
        const card = list[idx];
        // дубль: пост уже якорь или уже в подклейке треда
        if (card.id === ev.id || (card._thread || []).some(r => r.id === ev.id)) return prev;
        const updated = { ...card, _thread: [...(card._thread || []), ev],
                          _last: ev.created_at, _new: true };
        const rest = list.filter((_, i) => i !== idx);
        return { ...prev, [ev.direction]: [updated, ...rest].slice(0, 200) };
      }
      return { ...prev, [ev.direction]:
        [{ ...ev, _tkey: k, _thread: [], _last: ev.created_at, _new: true }, ...list].slice(0, 200) };
    });
    setTimeout(() => {
      setEventsByKey(prev => ({
        ...prev,
        [ev.direction]: (prev[ev.direction] || []).map(c =>
          c._tkey === k ? { ...c, _new: false } : c),
      }));
    }, 1200);
  }, []);

  // SSE subscription — one connection for all columns.
  useEffect(() => {
    if (!activeKeys.length) return;
    const es = intelApi.feedStream(activeKeys, { window: win, side, include_radar: showRadar || undefined }, (ev) => {
      // Колонка под курсором заморожена — копим события в буфер, не дёргаем строки
      // под указателем. На уходе курсора (onColLeave) буфер вливается разом.
      if (pausedRef.current.has(ev.direction)) {
        (bufferRef.current[ev.direction] ||= []).push(ev);
        setBufCounts(prev => ({ ...prev, [ev.direction]: (bufferRef.current[ev.direction] || []).length }));
        return;
      }
      applyEvent(ev);
    });
    esRef.current = es;
    return () => { es.close(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeKeys.join(','), win, side, showRadar, applyEvent]);

  const onColEnter = useCallback((key) => {
    pausedRef.current.add(key);
    setPausedKeys(prev => { const n = new Set(prev); n.add(key); return n; });
  }, []);
  const onColLeave = useCallback((key) => {
    pausedRef.current.delete(key);
    setPausedKeys(prev => { const n = new Set(prev); n.delete(key); return n; });
    const buffered = bufferRef.current[key] || [];
    bufferRef.current[key] = [];
    setBufCounts(prev => ({ ...prev, [key]: 0 }));
    // Вливаем накопленное (oldest→newest, чтобы порядок в колонке сохранился).
    buffered.forEach(applyEvent);
  }, [applyEvent]);

  const addColumn = useCallback((d) => {
    setActiveKeys(prev => prev.includes(d.key) ? prev : [...prev, d.key]);
  }, []);
  const removeColumn = useCallback((key) => {
    setActiveKeys(prev => prev.filter(k => k !== key));
  }, []);
  const resetToDefault = useCallback(() => {
    localStorage.removeItem(LS_KEY);
    intelApi.getLayout().then(l => setActiveKeys(l.direction_keys || [])).catch(() => {});
  }, []);

  return (
    <div className={styles.feed}>
      <div className={styles.feedTopbar}>
        <div className={styles.feedSeg}>
          {WINDOWS.map(([w, label]) =>
            <button key={w} data-active={win === w ? '1' : '0'} onClick={() => setWin(w)}>{label}</button>)}
        </div>
        <div className={styles.feedSeg}>
          {SIDES.map(([s, label]) =>
            <button key={label} data-active={String(side) === String(s) ? '1' : '0'} onClick={() => setSide(s)}>{label}</button>)}
        </div>
        <div className={styles.feedSeg}>
          <button data-active={showRadar ? '1' : '0'}
                  onClick={() => setShowRadar(v => !v)}
                  title="Показывать посты радар-источников в общей ленте">📡 Радар</button>
        </div>
        <div className={styles.feedSeg}>
          <button data-active={expandThreads ? '1' : '0'}
                  onClick={() => setExpandThreads(v => !v)}
                  title="Развернуть треды во всех колонках">🧵 Треды</button>
        </div>
        <div style={{ flex: 1 }} />
        <button className={styles.feedResetBtn} onClick={resetToDefault}>Сбросить к боевому</button>
      </div>

      <div className={styles.feedColumnBar}>
        {activeKeys.map(k => (
          <span key={k} className={styles.colChip}>
            ▶ {dirByName[k]?.name || k}
            <button onClick={() => removeColumn(k)}>✕</button>
          </span>
        ))}
        <ColumnPicker activeKeys={activeKeys} onAdd={addColumn} onRemove={removeColumn} />
      </div>

      <div className={styles.feedColumns}>
        {activeKeys.length === 0
          ? <div className={styles.feedEmpty}>Добавьте колонки через «+ колонки».</div>
          : activeKeys.map(k => (
              <FeedColumn key={k}
                          direction={dirByName[k] || { key: k, name: k }}
                          events={eventsByKey[k] || []}
                          paused={pausedKeys.has(k)}
                          newCount={bufCounts[k] || 0}
                          onEnter={() => onColEnter(k)}
                          onLeave={() => onColLeave(k)}
                          hiddenIds={hiddenIds}
                          onSpam={handleSpam}
                          expandThreads={expandThreads}
                          onRemove={() => removeColumn(k)} />
            ))}
      </div>
    </div>
  );
}
