// Situational Center (home) — «что горит сейчас».
// KPI strip + Now hot + Alerts + Top stories + Event stream.
import { useEffect, useRef, useState } from 'react';
import { Icon } from '../../../core/components/icons';
import { IntelSparkline } from './IntelSparkline';
import { intelApi, CREDIBILITY, DIRECTION_NAMES, spikeLevel, agoStrShort, SIDE } from '../api';
import styles from '../intel.module.css';

// How often the situational center re-polls the backend for new events. The realtime
// listener writes new mentions the instant a channel publishes; this surfaces them in
// the UI without a page refresh.
const LIVE_POLL_MS = 12000;

export function IntelHome({ window: win, onOpenStory }) {
  const [data, setData]         = useState(null);
  const [stream, setStream]     = useState([]);
  const [flashIds, setFlashIds] = useState(() => new Set());
  const seenRef                 = useRef(new Set());

  useEffect(() => {
    let alive = true;
    seenRef.current = new Set();

    const tick = (first) => {
      intelApi.overview(win).then(d => { if (alive) setData(d); }).catch(() => {});
      intelApi.stream({ window: win, limit: 18 }).then(events => {
        if (!alive) return;
        const arr = Array.isArray(events) ? events : [];
        if (first) {
          seenRef.current = new Set(arr.map(e => e.id));
          setStream(arr);
          return;
        }
        const fresh = arr.filter(e => !seenRef.current.has(e.id));
        setStream(arr);   // refresh either way so relative "ago" labels keep ticking
        if (fresh.length) {
          fresh.forEach(e => seenRef.current.add(e.id));
          setFlashIds(new Set(fresh.map(e => e.id)));
          setTimeout(() => { if (alive) setFlashIds(new Set()); }, LIVE_POLL_MS - 1000);
        }
      }).catch(() => {});
    };

    tick(true);
    const timer = setInterval(() => tick(false), LIVE_POLL_MS);
    return () => { alive = false; clearInterval(timer); };
  }, [win]);

  if (!data) return <div className={styles.workspace}><div className={styles.empty}>Загрузка обстановки…</div></div>;

  const { kpis, hot, alerts, top_stories } = data;

  return (
    <div className={styles.workspace}>
      {/* KPI strip */}
      <div className={styles.kpis}>
        <div className={styles.kpi}>
          <span className={styles.kpiLabel}>Событий / 24ч</span>
          <span className={styles.kpiValue}>{kpis.events}</span>
        </div>
        <div className={styles.kpi}>
          <span className={styles.kpiLabel}>Активных сюжетов</span>
          <span className={styles.kpiValue}>{kpis.active_stories}</span>
        </div>
        <div className={styles.kpi}>
          <span className={styles.kpiLabel}>Направлений в росте</span>
          <span className={styles.kpiValue} style={{ color: '#FFB23E' }}>{kpis.spiking_dirs}</span>
        </div>
      </div>

      {/* Now hot + Alerts */}
      <div className={styles.grid2}>
        <div className={styles.section}>
          <div className={styles.sectionHead}>
            <span className={styles.sectionTitle}>
              <Icon name="flame" size={13} color="#FF4D5E" />
              Горит сейчас
              <span className={styles.sectionCount}>{hot.length}</span>
            </span>
          </div>
          {hot.map(s => {
            const sp = spikeLevel(s.spike_pct);
            const cr = CREDIBILITY[s.credibility] || CREDIBILITY.unrated;
            return (
              <div key={s.id} className={styles.hotRow} onClick={onOpenStory}>
                <span className={styles.spikeTag} style={{ color: sp.color, background: sp.color + '22' }}>
                  +{s.spike_pct}%
                </span>
                <span className={styles.hotTitle}>{s.title}</span>
                <IntelSparkline data={s.sparkline} color={sp.color} w={56} h={18} />
                <span className={styles.hotDir}>{DIRECTION_NAMES[s.direction]?.split(' ')[0] || s.direction}</span>
                <span className={styles.hotMeta} style={{ color: cr.color }}>{s.source_count} ист.</span>
                <span className={styles.hotMeta}>{agoStrShort(s.last_seen_at)}</span>
              </div>
            );
          })}
        </div>

        <div className={styles.section}>
          <div className={styles.sectionHead}>
            <span className={styles.sectionTitle}>
              <Icon name="bell" size={13} color="#FFB23E" />
              Сигналы
              <span className={styles.sectionCount}>{alerts.length}</span>
            </span>
          </div>
          {alerts.map(a => {
            const isFake = a.kind === 'fake';
            const color = isFake ? '#FF4D5E' : '#FFB23E';
            return (
              <div key={a.id} className={styles.alertRow}>
                <span className={styles.alertIcon} style={{ background: color + '22' }}>
                  <Icon name={isFake ? 'warning' : 'activity'} size={14} color={color} />
                </span>
                <div className={styles.alertText}>
                  <div className={styles.alertMsg}>{a.message}</div>
                  <div className={styles.alertMeta}>
                    {DIRECTION_NAMES[a.direction]?.split(' ')[0] || a.direction} · +{a.magnitude}% · {agoStrShort(a.at)}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Top stories + Event stream */}
      <div className={styles.grid2}>
        <div className={styles.section}>
          <div className={styles.sectionHead}>
            <span className={styles.sectionTitle}>
              <Icon name="bar3" size={13} color="#57D2E2" />
              Крупнейшие сюжеты
              <span className={styles.sectionCount}>{top_stories.length}</span>
            </span>
          </div>
          {top_stories.map(s => {
            const cr = CREDIBILITY[s.credibility] || CREDIBILITY.unrated;
            return (
              <div key={s.id} className={styles.hotRow} onClick={onOpenStory}>
                <span className={styles.hotTitle}>{s.title}</span>
                <IntelSparkline data={s.sparkline} color="#57D2E2" w={56} h={18} />
                <span className={styles.hotMeta}>{s.post_count} упом.</span>
                <span className={styles.hotMeta} style={{ color: cr.color }}>{s.source_count} ист.</span>
              </div>
            );
          })}
        </div>

        <div className={styles.section}>
          <div className={styles.sectionHead}>
            <span className={styles.sectionTitle}>
              <Icon name="radio" size={13} color="#57D2E2" />
              Лента событий
              <span className={styles.sectionCount}>{stream.length}</span>
            </span>
            <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 10, color: '#34D8A0', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              {flashIds.size > 0 && (
                <span style={{ color: '#34D8A0', fontWeight: 700 }}>+{flashIds.size}</span>
              )}
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#34D8A0', animation: 'erpulse 2.4s var(--ease-in-out) infinite' }} />
              LIVE
            </span>
          </div>
          {stream.map(e => {
            const sd = SIDE[e.side] || SIDE.ru;
            const isNew = flashIds.has(e.id);
            return (
              <div key={e.id} className={isNew ? `${styles.eventRow} ${styles.eventRowNew}` : styles.eventRow}>
                <span className={styles.eventSide} style={{ color: sd.color, background: sd.color + '1A' }}>
                  {sd.label}
                </span>
                <div className={styles.eventBody}>
                  <div className={styles.eventText}>{e.text}</div>
                  <div className={styles.eventMeta}>
                    {e.author} · {DIRECTION_NAMES[e.direction]?.split(' ')[0] || e.direction}
                    {e.verified ? ' · ✓' : ''}
                  </div>
                </div>
                <span className={styles.eventTime}>{agoStrShort(e.created_at)}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
