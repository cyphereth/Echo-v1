// Situational Center (home) — «что горит сейчас».
// KPI strip + Now hot + Alerts + Top stories + Event stream.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Icon } from '../../../core/components/icons';
import { IntelSparkline } from './IntelSparkline';
import { ThreadContext } from './ThreadContext';
import MediaPreview from './MediaPreview';
import { intelApi, CREDIBILITY, DIRECTION_NAMES, spikeLevel, agoStrShort, SIDE } from '../api';
import styles from '../intel.module.css';

// KPI / hot / alerts refresh — not latency-critical, so a slow poll is fine. The event
// FEED is fed by an SSE push stream (~1-2s latency), not this interval.
const KPI_POLL_MS = 15000;
const STREAM_MAX  = 40;   // cap the in-memory feed so it can't grow unbounded
const FLASH_MS    = 2600; // how long a freshly arrived row stays highlighted

export function IntelHome({ timeRange, liveEvents = [], onOpenStory }) {
  const [data, setData]         = useState(null);
  const [stream, setStream]     = useState([]);
  const [flashIds, setFlashIds] = useState(() => new Set());
  const [hiddenIds, setHiddenIds] = useState(() => new Set());
  const [paused, setPaused]     = useState(false);  // наведение курсора замораживает ленту
  const pausedRef               = useRef(false);     // чтобы merge-эффект читал актуальное значение
  const seenRef                 = useRef(new Set());

  // Throw a post into the spam filter (kind="example") and hide it from the feed.
  async function handleSpam(e, ev) {
    ev.stopPropagation();
    setHiddenIds(prev => { const n = new Set(prev); n.add(e.id); return n; });
    try {
      // Запоминаем как пример мусора И мягко скрываем упоминание — чтобы пост ушёл
      // не только из ленты, но и из сюжетов/агрегатов (soft-hide на бэке).
      await Promise.all([
        intelApi.addSpam({ kind: 'example', value: e.text || '', author: e.author || null, source_post_id: e.post_id || null }),
        intelApi.hideMention(e.id),
      ]);
    } catch { /* optimistic — keep it hidden anyway */ }
  }

  // Derive a simple window string for SSE feed cutoff filtering
  const win = timeRange?.window || '24h';
  const isCustom = !!(timeRange?.from_dt || timeRange?.to_dt);

  useEffect(() => {
    let alive = true;
    seenRef.current = new Set();

    setStream([]);
    setFlashIds(new Set());
    intelApi.overview(timeRange).then(d => { if (alive) setData(d); }).catch(() => {});

    const streamParams = isCustom
      ? { from_dt: timeRange.from_dt, to_dt: timeRange.to_dt, limit: 18 }
      : { window: win, limit: 18 };
    intelApi.stream(streamParams).then(events => {
      if (!alive) return;
      const arr = Array.isArray(events) ? events : [];
      seenRef.current = new Set(arr.map(e => e.id));
      setStream(arr);
    }).catch(() => {});

    // Only poll KPIs in live mode; custom range is static
    let kpiTimer;
    if (!isCustom) {
      kpiTimer = setInterval(() => {
        intelApi.overview(timeRange).then(d => { if (alive) setData(d); }).catch(() => {});
      }, KPI_POLL_MS);
    }

    return () => { alive = false; clearInterval(kpiTimer); };
  }, [timeRange]);

  // Merge live events arriving from IntelApp's unified stream into the feed.
  // Filter by window so switching to 1h doesn't show 2-day-old posts that
  // were just ingested by the collector. Dedupes against what's already in the
  // stream, so it's safe to call with the full (cumulative) liveEvents prop.
  const mergeLive = useCallback((events) => {
    if (!events.length || isCustom) return;
    const windowMs = win === '1h' ? 3600000 : win === '7d' ? 7 * 86400000 : win === '30d' ? 30 * 86400000 : 86400000;
    const cutoff = Date.now() - windowMs;
    setStream(prev => {
      const seen = new Set(prev.map(e => e.id));
      const add = events.filter(e =>
        e && e.id != null && !seen.has(e.id) &&
        (!e.created_at || Date.parse(e.created_at) >= cutoff)
      );
      if (!add.length) return prev;
      add.forEach(e => {
        setFlashIds(f => { const n = new Set(f); n.add(e.id); return n; });
        setTimeout(() => {
          setFlashIds(f => { const n = new Set(f); n.delete(e.id); return n; });
        }, FLASH_MS);
      });
      // Лента — newest-first. liveEvents приходят oldest→newest, поэтому разворачиваем
      // и кладём в НАЧАЛО; slice(0,200) обрезает старые снизу, а не новые сверху.
      return [...add.reverse(), ...prev].slice(0, 200);
    });
  }, [win, isCustom]);

  // While the cursor is over the feed (paused), don't fold new events in — they'd
  // shift rows under the user's pointer. liveEvents is cumulative, so on un-pause
  // we just re-merge the whole prop and dedup catches the backlog.
  useEffect(() => {
    if (pausedRef.current) return;
    mergeLive(liveEvents);
  }, [liveEvents, mergeLive]);

  const onFeedEnter = useCallback(() => { pausedRef.current = true; setPaused(true); }, []);
  const onFeedLeave = useCallback(() => {
    pausedRef.current = false;
    setPaused(false);
    mergeLive(liveEvents);  // flush whatever arrived while paused
  }, [liveEvents, mergeLive]);

  // Collapse verbatim cross-channel reposts: events sharing a content signature become
  // one row (the newest), with a count of how many channels carried it. Keeps the feed
  // readable instead of repeating the same post once per channel.
  const feed = useMemo(() => {
    const out = [];
    const bySig = new Map();
    for (const e of stream) {
      if (hiddenIds.has(e.id)) continue;
      const key = e.sig || `id:${e.id}`;
      if (bySig.has(key)) {
        const item = out[bySig.get(key)];
        item._dups += 1;
        if (e.author) item._srcs.add(e.author);
        continue;
      }
      bySig.set(key, out.length);
      out.push({ ...e, _dups: 1, _srcs: new Set(e.author ? [e.author] : []) });
    }
    return out;
  }, [stream, hiddenIds]);

  if (!data) return <div className={styles.workspace}><div className={styles.empty}>Загрузка обстановки…</div></div>;

  const { kpis, hot, alerts, top_stories } = data;
  const SNIPPET_MAX = 160;
  const snippet = (t) => {
    const s = (t || '').replace(/\s+/g, ' ').trim();
    return s.length > SNIPPET_MAX ? s.slice(0, SNIPPET_MAX) + '…' : s;
  };

  return (
    <div className={`${styles.workspace} ${styles.homeWorkspace}`}>
      {/* KPI strip */}
      <div className={styles.kpis}>
        <div className={styles.kpi}>
          <span className={styles.kpiLabel}>Событий / {isCustom ? 'период' : win}</span>
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
          <div className={styles.scrollBody}>
          {hot.map(s => {
            const sp = spikeLevel(s.spike_pct);
            const cr = CREDIBILITY[s.credibility] || CREDIBILITY.unrated;
            return (
              <div key={s.id} className={styles.hotRow} onClick={() => onOpenStory(s.id)}>
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
        </div>

        <div className={styles.section}>
          <div className={styles.sectionHead}>
            <span className={styles.sectionTitle}>
              <Icon name="bell" size={13} color="#FFB23E" />
              Сигналы
              <span className={styles.sectionCount}>{alerts.length}</span>
            </span>
          </div>
          <div className={styles.scrollBody}>
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
      </div>

      {/* Top stories + Event stream */}
      <div className={`${styles.grid2} ${styles.feedRow}`}>
        <div className={styles.section}>
          <div className={styles.sectionHead}>
            <span className={styles.sectionTitle}>
              <Icon name="bar3" size={13} color="#57D2E2" />
              Крупнейшие сюжеты
              <span className={styles.sectionCount}>{top_stories.length}</span>
            </span>
          </div>
          <div className={styles.scrollBody}>
          {top_stories.map(s => {
            const cr = CREDIBILITY[s.credibility] || CREDIBILITY.unrated;
            return (
              <div key={s.id} className={styles.hotRow} onClick={() => onOpenStory(s.id)}>
                <span className={styles.hotTitle}>{s.title}</span>
                <IntelSparkline data={s.sparkline} color="#57D2E2" w={56} h={18} />
                <span className={styles.hotMeta}>{s.post_count} упом.</span>
                <span className={styles.hotMeta} style={{ color: cr.color }}>{s.source_count} ист.</span>
              </div>
            );
          })}
          </div>
        </div>

        <div className={styles.section} onMouseEnter={onFeedEnter} onMouseLeave={onFeedLeave}>
          <div className={styles.sectionHead}>
            <span className={styles.sectionTitle}>
              <Icon name="radio" size={13} color="#57D2E2" />
              Лента событий
              <span className={styles.sectionCount}>{feed.length}</span>
            </span>
            {isCustom ? (
              <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 10, color: '#6A8499' }}>
                АРХИВ
              </span>
            ) : paused ? (
              <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 10, color: '#FFB23E', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                {liveEvents.length > 0 && (
                  <span style={{ color: '#FFB23E', fontWeight: 700 }}>❚❚</span>
                )}
                ПАУЗА
              </span>
            ) : (
              <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 10, color: '#34D8A0', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                {flashIds.size > 0 && (
                  <span style={{ color: '#34D8A0', fontWeight: 700 }}>+{flashIds.size}</span>
                )}
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#34D8A0', animation: 'erpulse 2.4s var(--ease-in-out) infinite' }} />
                LIVE
              </span>
            )}
          </div>
          <div className={styles.scrollBody}>
          {feed.map(e => {
            const sd = SIDE[e.side] || SIDE.ru;
            const isNew = flashIds.has(e.id);
            const dups = e._dups || 1;
            return (
              <div key={e.id} className={isNew ? `${styles.eventRow} ${styles.eventRowNew}` : styles.eventRow}
                   title={e.text}>
                <span className={styles.eventSide} style={{ color: sd.color, background: sd.color + '1A' }}>
                  {sd.label}
                </span>
                <div className={styles.eventBody}>
                  <div className={styles.eventText}>
                    {e.media && (
                      <MediaPreview kind={e.media} url={`/intel/mention/${e.id}/media`} label={e.text} />
                    )}
                    {snippet(e.text)}
                  </div>
                  <div className={styles.eventMeta}>
                    {e.subject && <span style={{ color: '#57D2E2' }}>📍 {e.subject} · </span>}
                    {e.author} · {DIRECTION_NAMES[e.direction]?.split(' ')[0] || e.direction}
                    {dups > 1 ? ` · ${dups} канал.` : ''}
                    {e.verified ? ' · ✓' : ''}
                    {e.url && (
                      <> · <a href={e.url} target="_blank" rel="noopener noreferrer"
                             onClick={ev => ev.stopPropagation()}
                             style={{ color: '#57D2E2', textDecoration: 'none' }}>↗ TG</a></>
                    )}
                  </div>
                  {e.is_reply && <ThreadContext mentionId={e.id} />}
                </div>
                <span className={styles.eventTime}>{agoStrShort(e.created_at)}</span>
                <button
                  className={styles.eventSpam}
                  onClick={(ev) => handleSpam(e, ev)}
                  title="В спам (скрыть и запомнить как мусор)"
                >✕</button>
              </div>
            );
          })}
          </div>
        </div>
      </div>
    </div>
  );
}
