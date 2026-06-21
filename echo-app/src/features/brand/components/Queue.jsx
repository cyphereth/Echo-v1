import { useState, useEffect } from 'react';
import { Icon } from '../../../core/components/icons';
import * as api from '../api';
import styles from '../../../components/app/queue.module.css';

// Lane display helpers (inlined — removes dependency on data/mock)
function getLaneColor(lane) {
  if (lane === 'competitor') return 'var(--warn)';
  if (lane === 'niche')      return 'var(--info, #6c8ebf)';
  return 'var(--brand)';
}
function getLaneLabel(lane, competitor) {
  if (lane === 'competitor') return competitor ? `vs ${competitor}` : 'Конкурент';
  if (lane === 'niche')      return 'Ниша';
  return 'Мой бренд';
}

function buildOppGroups(opps) {
  const byMention = {};
  for (const o of opps) {
    const key = o.mention_id;
    if (!byMention[key]) {
      byMention[key] = {
        video: { id: `m${key}`, title: o.post_title, platform: o.platform,
                 lane: o.source || 'competitor', url: o.post_url },
        comments: [],
      };
    }
    byMention[key].comments.push(o);
  }
  return Object.values(byMention);
}

function fmtNum(n) {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function fmtAgo(mins) {
  if (mins < 60)  return `${mins} мин`;
  if (mins < 1440) return `${Math.floor(mins / 60)} ч`;
  return `${Math.floor(mins / 1440)} д`;
}

function buildQueue(source) {
  const items = [];
  for (const video of source) {
    const pending = video.comments.filter(c => c.suggestedReply || c.pendingReply);
    if (pending.length > 0) items.push({ video, comments: pending });
  }
  return items;
}

// ── Reply card ──────────────────────────────────────────────────────────────

function ReplyCard({ c, postUrl, onApprove, onSkip, onPosted }) {
  const [draft, setDraft]     = useState(c.suggestedReply || c.pendingReply || '');
  const [editing, setEditing] = useState(false);
  const [done, setDone]       = useState(false);
  const [doneType, setDoneType] = useState(null);

  const sentColor = {
    negative: { bg: 'var(--neg-dim)',     fg: 'var(--neg)' },
    positive: { bg: 'var(--calm-dim)',    fg: 'var(--calm)' },
    neutral:  { bg: 'var(--surface-3)',   fg: 'var(--fg-3)' },
  }[c.sentiment] ?? { bg: 'var(--surface-3)', fg: 'var(--fg-3)' };

  const sentLabel = { negative: 'негатив', positive: 'позитив', neutral: 'нейтрал' }[c.sentiment];

  return (
    <div className={styles.card} data-done={done ? '1' : '0'}>
      <div className={styles.cardComment}>
        <div className={styles.commentMeta}>
          <div className={styles.avatar}>{c.author[0].toUpperCase()}</div>
          <span className={styles.author}>{c.author}</span>
          <span className={styles.followers}>{fmtNum(c.followers)} подп.</span>
          {c.is_opportunity && (
            <span className={styles.sentBadge}
              title={c.opportunity || 'Уместный повод ответить от бренда'}
              style={{ background: 'var(--brand-dim, rgba(99,102,241,0.15))', color: 'var(--brand-bright, #818cf8)' }}>
              🎯 Возможность
            </span>
          )}
          <span className={styles.sentBadge} style={{ background: sentColor.bg, color: sentColor.fg }}>
            {sentLabel}
          </span>
          {c.likes > 0 && (
            <span className={styles.followers} style={{ marginLeft: 4, display: 'inline-flex', alignItems: 'center', gap: 3 }}>
              <Icon name="zap" size={10} color="var(--fg-4)" />{fmtNum(c.likes)}
            </span>
          )}
          <span className={styles.followers} style={{ marginLeft: 2, display: 'inline-flex', alignItems: 'center', gap: 3 }}>
            <Icon name="clock" size={10} color="var(--fg-4)" />{fmtAgo(c.minsAgo)}
          </span>
          {postUrl && (
            <a href={postUrl} target="_blank" rel="noopener noreferrer"
              title="Открыть пост в соцсети"
              style={{ marginLeft: 4, color: 'var(--fg-4)', display: 'inline-flex', alignItems: 'center' }}>
              <Icon name="externalLink" size={10} color="var(--fg-4)" />
            </a>
          )}
          {done && (
            <span className={styles.sentBadge} style={{
              background: doneType === 'sent' ? 'var(--calm-dim)' : 'var(--surface-3)',
              color: doneType === 'sent' ? 'var(--calm)' : 'var(--fg-3)',
              marginLeft: 'auto',
            }}>
              {doneType === 'sent' ? '✓ отправлен' : 'пропущен'}
            </span>
          )}
        </div>
        <p className={styles.commentText}>{c.text}</p>
      </div>

      {!done && (
        <div className={styles.cardReply}>
          <div className={styles.replyLabel}>
            <Icon name="sparkles" size={11} />AI-черновик
          </div>
          {editing ? (
            <textarea className={styles.replyText} value={draft}
              onChange={e => setDraft(e.target.value)} autoFocus />
          ) : (
            <p style={{ fontSize: 13, color: 'var(--fg-1)', lineHeight: 1.55, cursor: 'text', padding: '8px 0' }}
              onClick={() => setEditing(true)}>{draft}</p>
          )}
          <div className={styles.actions}>
            <button className={`${styles.btn} ${styles.btnDanger}`} onClick={() => { onSkip(c.id); setDone(true); setDoneType('skipped'); }}>
              <Icon name="x" size={13} />Пропустить
            </button>
            {!editing && (
              <button className={`${styles.btn} ${styles.btnGhost}`} onClick={() => setEditing(true)}>
                <Icon name="edit" size={13} />Изменить
              </button>
            )}
            <button className={`${styles.btn} ${styles.btnGhost}`} onClick={() => { onApprove(c.id, draft); setDone(true); setDoneType('sent'); }}>
              <Icon name="check" size={13} />Одобрить
            </button>
            <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={() => { onPosted(c.id, draft); setDone(true); setDoneType('sent'); }}>
              <Icon name="send" size={13} />Опубликовано
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Screen ──────────────────────────────────────────────────────────────────

const LANE_FILTERS      = ['all', 'brand', 'competitor', 'niche'];
const SENTIMENT_FILTERS = ['all', 'negative', 'positive', 'neutral'];
const SENTIMENT_LABELS  = { all: 'Все', negative: 'Негатив', positive: 'Позитив', neutral: 'Нейтрал' };
const SORT_OPTIONS      = [
  { key: 'date',  label: 'По дате',   icon: 'clock' },
  { key: 'likes', label: 'По лайкам', icon: 'zap' },
];

export function QueueScreen({ items, brandId }) {
  const [laneFilter, setLaneFilter]         = useState('all');
  const [sentFilter, setSentFilter]         = useState('all');
  const [sortBy, setSortBy]                 = useState('date');
  const [onlyOpps, setOnlyOpps]             = useState(false);
  const [states, setStates]                 = useState({});
  const [opps, setOpps]                     = useState([]);

  useEffect(() => {
    if (typeof brandId !== 'number') return;
    let alive = true;
    api.getOpportunities(brandId)
      .then(d => { if (alive && Array.isArray(d)) setOpps(d); })
      .catch(() => {});
    return () => { alive = false; };
  }, [brandId]);

  const oppGroups = buildOppGroups(opps);
  const raw = [...oppGroups, ...buildQueue(items ?? [])];

  const oppIds = new Set(opps.map(o => o.id));
  const onApprove = (id, draft) => {
    setStates(s => ({ ...s, [id]: 'approved' }));
    if (oppIds.has(id)) api.commentAction(id, 'approve', draft).catch(() => {});
  };
  const onSkip = (id) => {
    setStates(s => ({ ...s, [id]: 'skipped' }));
    if (oppIds.has(id)) api.commentAction(id, 'skip').catch(() => {});
  };
  const onPosted = (id, draft) => {
    setStates(s => ({ ...s, [id]: 'approved' }));
    if (oppIds.has(id)) api.commentAction(id, 'posted', draft).catch(() => {});
  };

  const totalPending = raw.reduce((sum, g) => sum + g.comments.length, 0);
  const approved     = Object.values(states).filter(s => s === 'approved').length;
  const skipped      = Object.values(states).filter(s => s === 'skipped').length;
  const pendingLeft  = totalPending - approved - skipped;

  const groups = raw
    .filter(g => laneFilter === 'all' || g.video.lane === laneFilter)
    .map(g => ({
      ...g,
      comments: g.comments
        .filter(c => sentFilter === 'all' || c.sentiment === sentFilter)
        .filter(c => !onlyOpps || c.is_opportunity)
        .sort((a, b) => sortBy === 'likes' ? b.likes - a.likes : a.minsAgo - b.minsAgo),
    }))
    .filter(g => g.comments.length > 0);

  function approveAll() {
    const ids = {};
    for (const g of groups) for (const c of g.comments) if (!states[c.id]) ids[c.id] = 'approved';
    setStates(s => ({ ...s, ...ids }));
  }
  function skipAll() {
    const ids = {};
    for (const g of groups) for (const c of g.comments) if (!states[c.id]) ids[c.id] = 'skipped';
    setStates(s => ({ ...s, ...ids }));
  }

  return (
    <div className={styles.page}>

      {/* Stats bar */}
      <div className={styles.bar}>
        <span className={styles.barStat}>
          <span className={styles.barVal} style={{ color: 'var(--brand-bright)' }}>{pendingLeft}</span>
          ожидают
        </span>
        <div className={styles.sep} />
        <span className={styles.barStat}>
          <span className={styles.barVal} style={{ color: 'var(--calm)' }}>{approved}</span>
          отправлено
        </span>
        <div className={styles.sep} />
        <span className={styles.barStat}>
          <span className={styles.barVal}>{skipped}</span>
          пропущено
        </span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
          <div style={{ display: 'flex', background: 'var(--surface-2)', border: '1px solid var(--line-2)', borderRadius: 'var(--r-md)', padding: 3, gap: 2 }}>
            {SORT_OPTIONS.map(o => (
              <button key={o.key}
                onClick={() => setSortBy(o.key)}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 5,
                  padding: '4px 10px', borderRadius: 'var(--r-sm)', fontSize: 12,
                  fontWeight: 600, border: 'none', cursor: 'pointer', fontFamily: 'var(--font-sans)',
                  background: sortBy === o.key ? 'var(--surface-3)' : 'none',
                  color: sortBy === o.key ? 'var(--fg-1)' : 'var(--fg-4)',
                  transition: 'all 0.12s',
                }}>
                <Icon name={o.icon} size={12} color={sortBy === o.key ? 'var(--brand-bright)' : 'var(--fg-4)'} />
                {o.label}
              </button>
            ))}
          </div>
          <div className={styles.sep} />
          <div className={styles.filters}>
            {LANE_FILTERS.map(f => (
              <button key={f} className={styles.chip} data-active={laneFilter === f ? '1' : '0'}
                onClick={() => setLaneFilter(f)}>
                {f === 'all' ? 'Все' : getLaneLabel(f)}
              </button>
            ))}
            <button className={styles.chip} data-active={onlyOpps ? '1' : '0'}
              onClick={() => setOnlyOpps(v => !v)}
              title="Только поводы ответить от бренда">
              🎯 Только возможности
            </button>
          </div>
        </div>
      </div>

      {/* Sentiment tabs */}
      <div style={{ display: 'flex', gap: 0, padding: '0 16px', borderBottom: '1px solid var(--line)', flexShrink: 0 }}>
        {SENTIMENT_FILTERS.map(f => {
          const count = raw.reduce((s, g) =>
            s + g.comments.filter(c => f === 'all' || c.sentiment === f).length, 0);
          const colors = {
            all:      { active: 'var(--brand)',   dim: 'var(--brand-dim)' },
            negative: { active: 'var(--neg)',      dim: 'var(--neg-dim)' },
            positive: { active: 'var(--calm)',     dim: 'var(--calm-dim)' },
            neutral:  { active: 'var(--fg-3)',     dim: 'var(--surface-2)' },
          };
          const c = colors[f];
          const isActive = sentFilter === f;
          return (
            <button key={f}
              onClick={() => setSentFilter(f)}
              style={{
                padding: '10px 16px 9px', fontSize: 13, fontWeight: 600,
                color: isActive ? 'var(--fg-1)' : 'var(--fg-3)',
                border: 'none', background: 'none', cursor: 'pointer',
                borderBottom: `2px solid ${isActive ? c.active : 'transparent'}`,
                marginBottom: -1, transition: 'all 0.12s',
                display: 'flex', alignItems: 'center', gap: 6,
              }}>
              {SENTIMENT_LABELS[f]}
              <span style={{
                fontSize: 10, fontWeight: 700, padding: '1px 5px', borderRadius: 99,
                fontFamily: 'var(--font-mono)',
                background: isActive ? c.dim : 'var(--surface-2)',
                color: isActive ? c.active : 'var(--fg-4)',
              }}>{count}</span>
            </button>
          );
        })}
      </div>

      {/* Content */}
      {pendingLeft === 0 && approved === 0 ? (
        <div className={styles.empty}>
          <div style={{ textAlign: 'center' }}>
            <Icon name="checkCircle" size={36} color="var(--calm)" style={{ marginBottom: 12 }} />
            <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--fg-2)', marginBottom: 6 }}>Всё обработано</div>
            <div style={{ fontSize: 13, color: 'var(--fg-4)' }}>Новые ответы появятся когда Echo найдёт упоминания</div>
          </div>
        </div>
      ) : groups.length === 0 ? (
        <div className={styles.empty}>
          <div style={{ textAlign: 'center', color: 'var(--fg-4)', fontSize: 13 }}>
            Нет комментариев по выбранным фильтрам
          </div>
        </div>
      ) : (
        <>
          <div className={styles.list}>
            {groups.map(({ video, comments }) => {
              const laneColor  = getLaneColor(video.lane);
              const liveCount  = comments.filter(c => !states[c.id]).length;
              return (
                <div key={video.id} className={styles.group}>
                  <div className={styles.groupHeader}>
                    <Icon name={video.platform} size={15} />
                    <span style={{ width: 8, height: 8, borderRadius: '50%', background: laneColor, flexShrink: 0 }} />
                    <span className={styles.groupTitle}>{video.title}</span>
                    <span className={styles.groupCount}>{liveCount} ожидают</span>
                    {video.url && (
                      <a href={video.url} target="_blank" rel="noopener noreferrer"
                        title="Открыть пост"
                        style={{ marginLeft: 'auto', color: 'var(--fg-4)', display: 'flex', alignItems: 'center', flexShrink: 0 }}>
                        <Icon name="externalLink" size={13} color="var(--fg-4)" />
                      </a>
                    )}
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {comments.map(c => (
                      <ReplyCard key={c.id} c={c} postUrl={video.url} onApprove={onApprove} onSkip={onSkip} onPosted={onPosted} />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>

          {pendingLeft > 0 && (
            <div className={styles.footer}>
              <span className={styles.footerText}>
                <strong style={{ color: 'var(--fg-1)' }}>{pendingLeft}</strong> ответов ждут одобрения
              </span>
              <button className={`${styles.btn} ${styles.btnGhost}`} onClick={skipAll}>Пропустить все</button>
              <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={approveAll}>
                <Icon name="checkCircle" size={14} />Одобрить все ({pendingLeft})
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
