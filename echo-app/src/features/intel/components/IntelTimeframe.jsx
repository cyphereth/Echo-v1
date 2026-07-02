// Таймфрейм — статичный архив за выбранный период.
// Колонки по направлению (сортировка по числу постов), внутри колонки посты
// сгруппированы по источнику-чату. Группировку делает backend (/intel/timeframe),
// клиент только рисует. Никакого SSE — это снимок, не live.
//
// Производительность:
//  • backend отдаёт до limit_per_source постов на источник (+has_more), не всё разом;
//  • источники в колонке рендерятся порциями («показать ещё N источников»), чтобы не
//    вешать в DOM тысячи узлов на первом кадре;
//  • «развернуть все треды» тянет контекст ОДНИМ батч-запросом (/intel/mentions/context)
//    вместо запроса на каждый пост, и раздаёт готовые данные в ThreadContext.
import { useEffect, useMemo, useState } from 'react';
import { intelApi } from '../api';
import { PostCard } from './PostCard';
import { ColumnPicker } from './ColumnPicker';
import styles from '../intel.module.css';

const SIDES = [[null, '🇷🇺+🇺🇦'], ['ru', '🇷🇺'], ['ua', '🇺🇦']];
const SOURCES_PAGE = 12;   // сколько источников в колонке показываем за раз

// timeRange → query-параметры для /intel/timeframe.
function rangeParams(timeRange) {
  if (timeRange?.from_dt || timeRange?.to_dt) {
    return { from_dt: timeRange.from_dt || undefined, to_dt: timeRange.to_dt || undefined };
  }
  return { window: timeRange?.window || '24h' };
}

function fmtRange(from_dt, to_dt) {
  const f = v => v ? new Date(v).toLocaleString('ru-RU', { day: '2-digit', month: '2-digit',
    year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '…';
  return `${f(from_dt)} → ${f(to_dt)}`;
}

function SourceGroup({ source, expandThreads, threadCtx }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6, padding: '4px 2px',
        fontFamily: 'var(--font-mono)', fontSize: 11, color: '#57D2E2',
        borderBottom: '1px solid rgba(43,179,199,.15)', marginBottom: 4,
        position: 'sticky', top: 0, background: '#0B121C', zIndex: 1,
      }}>
        <span style={{ fontWeight: 700 }}>{source.handle}</span>
        <span style={{ color: '#6A8499' }}>· {source.count}{source.has_more ? '+' : ''}</span>
      </div>
      {source.posts.map(e => (
        <PostCard key={e.id} event={e} expandThreads={expandThreads}
                  threadData={threadCtx ? threadCtx[e.id] || null : null} />
      ))}
      {source.has_more && (
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: '#6A8499', padding: '2px' }}>
          …ещё {source.count - source.posts.length} (сузь период)
        </div>
      )}
    </div>
  );
}

function Column({ col, expandThreads, threadCtx }) {
  const [visible, setVisible] = useState(SOURCES_PAGE);
  const shown = col.sources.slice(0, visible);
  const rest = col.sources.length - shown.length;
  return (
    <div className={styles.feedColumn}>
      <div className={styles.feedColumnHead}>
        <span className={styles.feedColumnName}>{col.direction.name}</span>
        <span className={styles.feedColumnCount}>{col.count}</span>
      </div>
      <div className={styles.feedColumnBody}>
        {shown.map(src => (
          <SourceGroup key={src.handle} source={src}
                       expandThreads={expandThreads} threadCtx={threadCtx} />
        ))}
        {rest > 0 && (
          <button className={styles.feedResetBtn} style={{ width: '100%', marginTop: 6 }}
                  onClick={() => setVisible(v => v + SOURCES_PAGE)}>
            показать ещё {Math.min(rest, SOURCES_PAGE)} источн. ({rest})
          </button>
        )}
      </div>
    </div>
  );
}

export function IntelTimeframe({ timeRange }) {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(false);
  const [side, setSide]       = useState(null);
  const [radar, setRadar]     = useState(false);
  const [expandThreads, setExpandThreads] = useState(false);
  const [threadCtx, setThreadCtx] = useState(null);   // {mentionId: {reply_chain, siblings}}
  const [allDirs, setAllDirs]     = useState([]);     // каталог направлений для фильтра
  const [pickDirs, setPickDirs]   = useState([]);     // выбранные ключи; пусто = все

  useEffect(() => { intelApi.directions().then(setAllDirs).catch(() => {}); }, []);

  const dirByKey = useMemo(() => Object.fromEntries(allDirs.map(d => [d.key, d])), [allDirs]);
  const dirCsv = pickDirs.join(',');
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setThreadCtx(null);   // новый срез — старые треды не валидны
    intelApi.timeframe({ ...rangeParams(timeRange),
                         side: side || undefined,
                         include_radar: radar || undefined,
                         directions: dirCsv || undefined })
      .then(d => { if (alive) setData(d); })
      .catch(() => { if (alive) setData({ columns: [], total: 0 }); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [timeRange, side, radar, dirCsv]);

  // Все id постов-ответов в срезе — кандидаты на треды.
  const replyIds = useMemo(() => {
    if (!data) return [];
    const ids = [];
    for (const c of data.columns) for (const s of c.sources) for (const p of s.posts) {
      if (p.is_reply) ids.push(p.id);
    }
    return ids;
  }, [data]);

  // Тумблер «треды»: один батч-запрос на весь срез (чанки по 500), готовые данные
  // раздаём постам через threadData → ThreadContext не ходит в сеть на каждый пост.
  useEffect(() => {
    if (!expandThreads || threadCtx || replyIds.length === 0) return;
    let alive = true;
    const chunks = [];
    for (let i = 0; i < replyIds.length; i += 500) chunks.push(replyIds.slice(i, i + 500));
    Promise.all(chunks.map(c => intelApi.mentionsContext(c).catch(() => ({}))))
      .then(parts => {
        if (!alive) return;
        setThreadCtx(Object.assign({}, ...parts));
      });
    return () => { alive = false; };
  }, [expandThreads, replyIds, threadCtx]);

  const columns = data?.columns || [];

  return (
    <div className={styles.feed}>
      <div className={styles.feedTopbar}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: '#97A9BE' }}>
          {data ? fmtRange(data.from_dt, data.to_dt) : '…'}
          <span style={{ color: '#57D2E2', marginLeft: 8 }}>{data?.total || 0} сообщ.</span>
        </div>
        <div style={{ flex: 1 }} />
        <div className={styles.feedSeg}>
          {SIDES.map(([s, label]) =>
            <button key={label} data-active={String(side) === String(s) ? '1' : '0'}
                    onClick={() => setSide(s)}>{label}</button>)}
        </div>
        <div className={styles.feedSeg}>
          <button data-active={radar ? '1' : '0'} onClick={() => setRadar(v => !v)}
                  title="Показывать посты радар-источников">📡 Радар</button>
        </div>
        <div className={styles.feedSeg}>
          <button data-active={expandThreads ? '1' : '0'}
                  onClick={() => setExpandThreads(v => !v)}
                  title="Развернуть все треды">🧵 Треды</button>
        </div>
      </div>

      {/* Фильтр областей — тот же drawer-пикер, что в Ленте v2. Пусто = все области;
          выбранные показываем чипами с ✕, «Все области» сбрасывает. */}
      <div className={styles.feedColumnBar}>
        {pickDirs.length === 0
          ? <span className={styles.colChip} style={{ opacity: 0.7 }}>Все области</span>
          : (
            <>
              {pickDirs.map(k => (
                <span key={k} className={styles.colChip}>
                  ▶ {dirByKey[k]?.name || k}
                  <button onClick={() => setPickDirs(prev => prev.filter(x => x !== k))}>✕</button>
                </span>
              ))}
              <button className={styles.feedResetBtn} onClick={() => setPickDirs([])}>Все области</button>
            </>
          )}
        <ColumnPicker
          activeKeys={pickDirs}
          onAdd={(d) => setPickDirs(prev => prev.includes(d.key) ? prev : [...prev, d.key])}
          onRemove={(key) => setPickDirs(prev => prev.filter(k => k !== key))} />
      </div>

      <div className={styles.feedColumns}>
        {loading && !data
          ? <div className={styles.feedEmpty}>Загрузка…</div>
          : columns.length === 0
            ? <div className={styles.feedEmpty}>Нет сообщений за выбранный период.</div>
            : columns.map(col => (
                <Column key={col.direction.key} col={col}
                        expandThreads={expandThreads} threadCtx={threadCtx} />
              ))}
      </div>
    </div>
  );
}
