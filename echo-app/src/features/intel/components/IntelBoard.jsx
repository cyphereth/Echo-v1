// Оперативная доска (Operational Board) — сетка направлений.
// Каждая карточка: имя, heat-bar активности, индикатор всплеска (+%),
// количество верифицированных событий, последний фрагмент события, достоверность (credibility).
import { useEffect, useState } from 'react';
import { intelApi, CREDIBILITY, spikeLevel, activityLevel, agoStrShort } from '../api';
import styles from '../intel.module.css';

export function IntelBoard({ window: win, onOpenDir }) {
  const [dirs, setDirs]     = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    intelApi.directions(win).then(d => { if (alive) setDirs(d); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [win]);

  if (loading) return <div className={styles.workspace}><div className={styles.empty}>Загрузка обстановки по направлениям…</div></div>;

  return (
    <div className={styles.workspace}>
      <div className={styles.dirGrid}>
        {dirs.map(d => {
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
        })}
      </div>
    </div>
  );
}
