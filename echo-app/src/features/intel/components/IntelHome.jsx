// Situational Center (home) — «что горит сейчас».
// KPI strip + Now hot + Alerts + Top stories + Event stream.
import { useEffect, useRef, useState } from 'react';
import { Icon } from '../../../core/components/icons';
import { IntelSparkline } from './IntelSparkline';
import { intelApi, streamLiveEvents, CREDIBILITY, DIRECTION_NAMES, spikeLevel, agoStrShort, SIDE } from '../api';
import styles from '../intel.module.css';

// KPI / hot / alerts refresh — not latency-critical, so a slow poll is fine. The event
// FEED is fed by an SSE push stream (~1-2s latency), not this interval.
const KPI_POLL_MS = 15000;
const STREAM_MAX  = 40;   // cap the in-memory feed so it can't grow unbounded
const FLASH_MS    = 2600; // how long a freshly arrived row stays highlighted

export function IntelHome({ window: win, onOpenStory }) {
  const [data, setData]         = useState(null);
  const [stream, setStream]     = useState([]);
  const [flashIds, setFlashIds] = useState(() => new Set());
  const seenRef                 = useRef(new Set());

  useEffect(() => {
    let alive = true;
    seenRef.current = new Set();
    let stopStream = () => {};

    intelApi.overview(win).then(d => { if (alive) setData(d); }).catch(() => {});

    // Initial snapshot, then resume the live push stream from the newest id we have.
    intelApi.stream({ window: win, limit: 18 }).then(events => {
      if (!alive) return;
      const arr = Array.isArray(events) ? events : [];
      seenRef.current = new Set(arr.map(e => e.id));
      setStream(arr);
      const maxId = arr.reduce((m, e) => Math.max(m, e.id || 0), 0);
      stopStream = streamLiveEvents({
        afterId: maxId,
        onEvent: (e) => {
          if (!alive || !e || e.id == null || seenRef.current.has(e.id)) return;
          seenRef.current.add(e.id);
          setStream(prev => [e, ...prev].slice(0, STREAM_MAX));
          setFlashIds(prev => { const n = new Set(prev); n.add(e.id); return n; });
          setTimeout(() => {
            if (!alive) return;
            setFlashIds(prev => { const n = new Set(prev); n.delete(e.id); return n; });
          }, FLASH_MS);
        },
      });
    }).catch(() => {});

    const kpiTimer = setInterval(() => {
      intelApi.overview(win).then(d => { if (alive) setData(d); }).catch(() => {});
    }, KPI_POLL_MS);

    return () => { alive = false; stopStream(); clearInterval(kpiTimer); };
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
