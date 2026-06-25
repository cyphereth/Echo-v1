// Stories — news intelligence on the conflict.
// Левая колонка: список + фильтры (direction / side / verified-only) + sort.
// Правая: деталь — заголовок, summary, credibility, activity-timeline,
// список источников по сторонам, составляющие события.
import { useEffect, useState } from 'react';
import {
  ResponsiveContainer, ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, CartesianGrid,
} from 'recharts';
import { Icon } from '../../../core/components/icons';
import { intelApi, CREDIBILITY, DIRECTION_NAMES, SIDE, spikeLevel, agoStrShort } from '../api';
import styles from '../intel.module.css';

const C = { bar: '#2BB3C7', line: '#34D8A0', grid: 'rgba(43,179,199,.10)', fg3: '#6A8499' };
const tooltipStyle = { background: '#0A0F16', border: '1px solid rgba(43,179,199,.20)', borderRadius: '6px', color: '#D8E4F0', fontSize: '11px' };
const DIRECTION_OPTS = Object.keys(DIRECTION_NAMES);

export function IntelStories({ timeRange, openStoryId, openDirection, navToken }) {
  const [list, setList]         = useState([]);
  const [selectedId, setSel]    = useState(null);
  const [detail, setDetail]     = useState(null);
  const [filters, setFilters]   = useState({ direction: openDirection || '', side: '', verified: false });
  const [sort, setSort]         = useState('activity');

  // When navigated here from home with a specific story, select it immediately.
  useEffect(() => {
    if (openStoryId != null) setSel(openStoryId);
  }, [openStoryId]);

  // When navigated here from board with a direction, apply it as a filter.
  // navToken changes on every navigation so this fires even if direction is the same.
  useEffect(() => {
    if (openDirection != null) setFilters(f => ({ ...f, direction: openDirection }));
    else if (openDirection === null) setFilters(f => ({ ...f, direction: '' }));
  }, [openDirection, navToken]);

  useEffect(() => {
    const rangeParams = timeRange?.from_dt || timeRange?.to_dt
      ? { from_dt: timeRange.from_dt, to_dt: timeRange.to_dt }
      : { window: timeRange?.window || '24h' };
    intelApi.stories({ ...filters, ...rangeParams, verified: filters.verified ? 'true' : '', sort, limit: 30 })
      .then(l => {
        setList(l);
        // If navigated here with a specific story, keep that selection; otherwise pick first.
        setSel(cur => {
          if (openStoryId != null) return openStoryId;
          if (cur != null && l.find(s => s.id === cur)) return cur;
          return l.length ? l[0].id : null;
        });
      })
      .catch(() => setList([]));
  }, [filters, sort, timeRange, openStoryId]);  // eslint-disable-line

  useEffect(() => {
    if (!selectedId) { setDetail(null); return; }
    intelApi.story(selectedId).then(setDetail).catch(() => setDetail(null));
  }, [selectedId]);

  return (
    <div className={styles.gridSplit} style={{ flex: 1 }}>
      {/* left: list + filters */}
      <div className={styles.storyList}>
        <div className={styles.storyListHead}>
          <div className={styles.storyListTitle}>Сюжеты · {list.length}</div>
          {/* direction filter */}
          <div className={styles.filters}>
            <div className={styles.filterRow}>
              <button className={styles.filterChip} data-active={!filters.direction ? '1' : '0'}
                onClick={() => setFilters(f => ({ ...f, direction: '' }))}>Все</button>
              {DIRECTION_OPTS.slice(0, 6).map(d => (
                <button key={d} className={styles.filterChip} data-active={filters.direction === d ? '1' : '0'}
                  onClick={() => setFilters(f => ({ ...f, direction: f.direction === d ? '' : d }))}>
                  {DIRECTION_NAMES[d].split(' ')[0]}
                </button>
              ))}
            </div>
            <div className={styles.filterRow}>
              {['ru', 'ua'].map(s => (
                <button key={s} className={styles.filterChip} data-active={filters.side === s ? '1' : '0'}
                  onClick={() => setFilters(f => ({ ...f, side: f.side === s ? '' : s }))}>
                  {SIDE[s].label}
                </button>
              ))}
              <button className={styles.filterChip} data-active={filters.verified ? '1' : '0'}
                onClick={() => setFilters(f => ({ ...f, verified: !f.verified }))}>
                ✓ вериф.
              </button>
            </div>
            <div className={styles.filterRow}>
              <button className={styles.filterChip} data-active={sort === 'activity' ? '1' : '0'}
                onClick={() => setSort('activity')}>по активности</button>
              <button className={styles.filterChip} data-active={sort === 'recency' ? '1' : '0'}
                onClick={() => setSort('recency')}>по свежести</button>
            </div>
          </div>
        </div>
        {list.map(s => {
          const sp = spikeLevel(s.spike_pct);
          const cr = CREDIBILITY[s.credibility] || CREDIBILITY.unrated;
          return (
            <div key={s.id} className={styles.storyCard} data-active={selectedId === s.id ? '1' : '0'}
              onClick={() => setSel(s.id)}>
              <div className={styles.storyCardTitle}>{s.title}</div>
              <div className={styles.storyCardMeta}>
                <span style={{ color: sp.color }}>+{s.spike_pct}%</span>
                <span style={{ color: cr.color }}>● {cr.label}</span>
                <span>{s.source_count} ист.</span>
                <span>{DIRECTION_NAMES[s.direction]?.split(' ')[0]}</span>
                <span style={{ marginLeft: 'auto' }}>{agoStrShort(s.last_seen_at)}</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* right: detail */}
      <div className={styles.storyDetail}>
        {!detail ? (
          <div className={styles.empty}>Выберите сюжет слева</div>
        ) : <StoryDetail detail={detail} />}
      </div>
    </div>
  );
}

function CollapsibleSection({ title, icon, count, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={styles.section}>
      <div
        className={styles.sectionHead}
        onClick={() => setOpen(o => !o)}
        style={{ cursor: 'pointer', userSelect: 'none' }}
      >
        <span className={styles.sectionTitle}>
          <Icon name={icon} size={12} color="#57D2E2" />
          {title}
          {count != null && <span className={styles.sectionCount}>{count}</span>}
        </span>
        <span style={{ marginLeft: 'auto', color: '#4A6378', fontSize: 11, fontFamily: 'var(--font-mono)', transition: 'transform .2s', display: 'inline-block', transform: open ? 'rotate(0deg)' : 'rotate(-90deg)' }}>▾</span>
      </div>
      {open && children}
    </div>
  );
}

function ThreadContext({ mentionId }) {
  const [open, setOpen] = useState(false);
  const [ctx, setCtx] = useState(null);
  const [loading, setLoading] = useState(false);

  function toggle() {
    if (open) { setOpen(false); return; }
    if (ctx) { setOpen(true); return; }
    setLoading(true);
    intelApi.mentionContext(mentionId)
      .then(data => { setCtx(data); setOpen(true); })
      .catch(() => setCtx({ reply_chain: [], siblings: [] }))
      .finally(() => setLoading(false));
  }

  const borderStyle = { borderLeft: '2px solid #2BB3C7', paddingLeft: 8, margin: '4px 0' };

  return (
    <div style={{ marginBottom: 4 }}>
      <button
        onClick={toggle}
        style={{ background: 'none', border: 'none', color: '#4A6378', fontSize: 10,
                 fontFamily: 'var(--font-mono)', cursor: 'pointer', padding: '0 0 2px' }}>
        {loading ? '…' : open ? '↓ свернуть тред' : '↑ контекст'}
      </button>
      {open && ctx && (
        <div style={borderStyle}>
          {[...ctx.reply_chain].reverse().map((p, i) => (
            <div key={p.tg_msg_id} style={{ color: '#4A6378', fontSize: 11, marginBottom: 2,
                                            paddingLeft: i * 8 }}>
              <span style={{ color: '#3A5368', marginRight: 4 }}>{p.author}</span>
              {p.text}
            </div>
          ))}
          {ctx.siblings.map(s => (
            <div key={s.tg_msg_id} style={{ color: '#4A6378', fontSize: 11, marginBottom: 2,
                                            paddingLeft: (ctx.reply_chain.length) * 8 }}>
              <span style={{ color: '#3A5368', marginRight: 4 }}>{s.author}</span>
              {s.text}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StoryDetail({ detail }) {
  const cr = CREDIBILITY[detail.credibility] || CREDIBILITY.unrated;
  const sp = spikeLevel(detail.spike_pct);
  const chartData = (detail.points || []).map(p => ({
    t: agoStrShort(p.bucket_start),
    mentions: p.mention_count,
    sources: p.source_count,
  }));

  return (
    <>
      <div className={styles.detailTitle}>{detail.title}</div>
      <div className={styles.detailBadges}>
        <span className={styles.badge} style={{ color: sp.color, background: sp.color + '22' }}>
          +{detail.spike_pct}% · {sp.label}
        </span>
        <span className={styles.badge} style={{ color: cr.color, background: cr.bg, border: `1px solid ${cr.border}` }}>
          {cr.label}
        </span>
        {detail.sides?.map(s => (
          <span key={s} className={styles.badge} style={{ color: SIDE[s].color, background: SIDE[s].color + '1A' }}>
            {SIDE[s].label}
          </span>
        ))}
        <span className={styles.badge} style={{ color: '#6A8499', background: 'rgba(255,255,255,.03)' }}>
          {DIRECTION_NAMES[detail.direction]}
        </span>
      </div>

      {detail.credibility_note && (
        <div className={styles.detailSummary} style={{ borderLeftColor: cr.border }}>
          <strong style={{ color: cr.color }}>{cr.label}.</strong> {detail.credibility_note}
        </div>
      )}
      {detail.summary_text && (
        <div className={styles.detailSummary}>{detail.summary_text}</div>
      )}

      {/* activity timeline */}
      {chartData.length > 0 && (
        <div className={styles.section}>
          <div className={styles.sectionHead}>
            <span className={styles.sectionTitle}>
              <Icon name="activity" size={12} color="#57D2E2" />
              Активность по времени
            </span>
          </div>
          <div style={{ padding: 12 }}>
            <ResponsiveContainer width="100%" height={200}>
              <ComposedChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={C.grid} vertical={false} />
                <XAxis dataKey="t" stroke={C.fg3} tick={{ fontSize: 10, fontFamily: 'var(--font-mono)' }} tickLine={false} axisLine={{ stroke: C.grid }} />
                <YAxis stroke={C.fg3} tick={{ fontSize: 10, fontFamily: 'var(--font-mono)' }} tickLine={false} axisLine={{ stroke: C.grid }} allowDecimals={false} />
                <Tooltip contentStyle={tooltipStyle} />
                <Bar dataKey="mentions" name="Упоминания" fill={C.bar} radius={[2, 2, 0, 0]} />
                <Line dataKey="sources" name="Источников" stroke={C.line} dot={false} strokeWidth={2} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* sources by side */}
      <CollapsibleSection icon="radio" title="Источники" count={detail.sources?.length || 0}>
        <div style={{ padding: '4px 16px 8px' }}>
          {(detail.sources || []).map((src, i) => {
            const sd = SIDE[src.side] || SIDE.ru;
            return (
              <div key={i} className={styles.sourceRow}>
                <span className={styles.eventSide} style={{ color: sd.color, background: sd.color + '1A', minWidth: 36 }}>
                  {sd.label}
                </span>
                <span className={styles.sourceName}>{src.name}</span>
                <span className={styles.sourceCount}>{src.count} упом.</span>
                <span className={styles.sourceCount}>{agoStrShort(src.last_at)}</span>
              </div>
            );
          })}
        </div>
      </CollapsibleSection>

      {/* constituent events */}
      {detail.events?.length > 0 && (
        <CollapsibleSection icon="bar3" title="События" count={detail.events.length} defaultOpen={false}>
          {detail.events.map(e => {
            const sd = SIDE[e.side] || SIDE.ru;
            return (
              <div key={e.id} className={styles.eventRow}>
                <span className={styles.eventSide} style={{ color: sd.color, background: sd.color + '1A' }}>{sd.label}</span>
                <div className={styles.eventBody}>
                  <div className={styles.eventText}>{e.text}</div>
                  <div className={styles.eventMeta}>{e.author}{e.verified ? ' · ✓' : ''}</div>
                  {e.is_reply && <ThreadContext mentionId={e.id} />}
                </div>
                <span className={styles.eventTime}>{agoStrShort(e.created_at)}</span>
              </div>
            );
          })}
        </CollapsibleSection>
      )}
    </>
  );
}
