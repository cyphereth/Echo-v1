// Оперативная доска (Operational Board) — сетка направлений.
// Каждая карточка: имя, heat-bar активности, индикатор всплеска (+%),
// количество верифицированных событий, последний фрагмент события, достоверность (credibility).
import { useEffect, useMemo, useState } from 'react';
import { intelApi, CREDIBILITY, spikeLevel, activityLevel, agoStrShort } from '../api';
import styles from '../intel.module.css';

// На доске показываем только КЛЮЧЕВЫЕ направления по военным действиям.
// Приграничные области РФ остаются отдельными направлениями в БД, но группируются
// на доске под одним заголовком «Приграничье РФ». Прочие направления (dnipro, kyiv,
// chernihiv, unassigned) и 📍-only города на доску не выводятся.
const BORDER_RF = ['bryansk', 'belgorod', 'kursk', 'voronezh', 'oryol', 'rostov'];
// Порядок одиночных ключевых направлений после группы приграничья.
const KEY_SOLO = ['sumy', 'kharkiv', 'luhansk', 'donetsk', 'zaporizhzhia', 'kherson', 'crimea'];

export function IntelBoard({ timeRange, onOpenDir }) {
  const win = timeRange?.window || '24h';
  const [dirs, setDirs]     = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    intelApi.directions(win).then(d => { if (alive) setDirs(d); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [win]);

  // Доска: группа «Приграничье РФ» + одиночные ключевые направления в заданном порядке.
  const groups = useMemo(() => {
    const byKey = new Map(dirs.map(d => [d.key, d]));
    const border = BORDER_RF.map(k => byKey.get(k)).filter(Boolean);
    const out = [];
    if (border.length) out.push({ title: 'Приграничье РФ', items: border });
    const solo = KEY_SOLO.map(k => byKey.get(k)).filter(Boolean);
    if (solo.length) out.push({ title: null, items: solo });
    return out;
  }, [dirs]);

  if (loading) return <div className={styles.workspace}><div className={styles.empty}>Загрузка обстановки по направлениям…</div></div>;

  const renderCard = (d) => {
    const heat = activityLevel(d.activity_level);
    const sp = spikeLevel(d.spike_pct);
    const cr = CREDIBILITY[d.dominant_credibility] || CREDIBILITY.unrated;
    return (
      <div key={d.key} className={styles.dirCard} onClick={() => onOpenDir?.(d.key)}>
        <div className={styles.dirCardHead}>
          <span className={styles.dirName}>{d.name}</span>
          {d.spike_pct >= 100 && (
            <span className={styles.spikeTag} style={{ color: sp.color, background: sp.color + '22' }}>
              ↑ {d.spike_pct}%
            </span>
          )}
        </div>

        {/* heat bar */}
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: '#6A8499', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
              Активность
            </span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700, color: heat.color }}>
              {d.activity_level} · {heat.label}
            </span>
          </div>
          <div className={styles.heatBar}>
            <div className={styles.heatFill} style={{ width: `${d.activity_level}%`, background: heat.color }} />
          </div>
        </div>

        {/* stats */}
        <div className={styles.dirStats}>
          <span>событий: <span className={styles.dirStatVal}>{d.events_count}</span></span>
          <span style={{ color: cr.color }}>● {cr.label}</span>
        </div>

        {/* last event */}
        {d.last_event && (
          <div className={styles.dirLast}>
            <div style={{ marginBottom: 3 }}>{d.last_event.text}</div>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: '#5A7488' }}>
              {d.last_event.source} · {agoStrShort(d.last_event.at)}
            </span>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className={styles.workspace}>
      {groups.map((g, i) => (
        <div key={g.title || `solo-${i}`}>
          {g.title && (
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700, color: '#6A8499', letterSpacing: '0.08em', textTransform: 'uppercase', margin: '4px 2px 8px' }}>
              {g.title}
            </div>
          )}
          <div className={styles.dirGrid} style={{ marginBottom: 18 }}>
            {g.items.map(renderCard)}
          </div>
        </div>
      ))}
    </div>
  );
}
