// Таймфрейм — статичный архив за выбранный период.
// Колонки по направлению (сортировка по числу постов), внутри колонки посты
// сгруппированы по источнику-чату. Группировку делает backend (/intel/timeframe),
// клиент только рисует. Треды сворачиваемы; тумблер «развернуть все» поднимает их
// разом через forceOpen у ThreadContext. Никакого SSE — это снимок, не live.
import { useEffect, useState } from 'react';
import { intelApi } from '../api';
import { PostCard } from './PostCard';
import styles from '../intel.module.css';

const SIDES = [[null, '🇷🇺+🇺🇦'], ['ru', '🇷🇺'], ['ua', '🇺🇦']];

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

function SourceGroup({ source, expandThreads }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6, padding: '4px 2px',
        fontFamily: 'var(--font-mono)', fontSize: 11, color: '#57D2E2',
        borderBottom: '1px solid rgba(43,179,199,.15)', marginBottom: 4,
        position: 'sticky', top: 0, background: '#0B121C', zIndex: 1,
      }}>
        <span style={{ fontWeight: 700 }}>{source.handle}</span>
        <span style={{ color: '#6A8499' }}>· {source.count}</span>
      </div>
      {source.posts.map(e => (
        <PostCard key={e.id} event={e} expandThreads={expandThreads} />
      ))}
    </div>
  );
}

export function IntelTimeframe({ timeRange }) {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(false);
  const [side, setSide]       = useState(null);
  const [radar, setRadar]     = useState(false);
  const [expandThreads, setExpandThreads] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    intelApi.timeframe({ ...rangeParams(timeRange),
                         side: side || undefined,
                         include_radar: radar || undefined })
      .then(d => { if (alive) setData(d); })
      .catch(() => { if (alive) setData({ columns: [], total: 0 }); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [timeRange, side, radar]);

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

      <div className={styles.feedColumns}>
        {loading && !data
          ? <div className={styles.feedEmpty}>Загрузка…</div>
          : columns.length === 0
            ? <div className={styles.feedEmpty}>Нет сообщений за выбранный период.</div>
            : columns.map(col => (
                <div key={col.direction.key} className={styles.feedColumn}>
                  <div className={styles.feedColumnHead}>
                    <span className={styles.feedColumnName}>{col.direction.name}</span>
                    <span className={styles.feedColumnCount}>{col.count}</span>
                  </div>
                  <div className={styles.feedColumnBody}>
                    {col.sources.map(src => (
                      <SourceGroup key={src.handle} source={src} expandThreads={expandThreads} />
                    ))}
                  </div>
                </div>
              ))}
      </div>
    </div>
  );
}
