import { useState, useEffect } from 'react';
import { Icon } from '../../core/components/icons';
import { request } from '../../core/api/client';
import styles from './detail.module.css';

// Brand mention API calls used by this shared Detail panel
const api = {
  getComments:       (mentionId, refresh = false) =>
    request(`/mentions/${mentionId}/comments${refresh ? '?refresh=1' : ''}`),
  commentAction:     (commentId, action, draft = null) =>
    request(`/comments/${commentId}/action`, { method: 'POST', body: JSON.stringify({ action, draft }) }),
  regenerateComment: (commentId) =>
    request(`/comments/${commentId}/regenerate`, { method: 'POST' }),
};

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

function fmtNum(n) {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000)    return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

const THUMB_EMOJI = { neg: '😡', competitor: '⚔️', niche: '💬', neutral: '📢' };

function SentimentBadge({ sentiment }) {
  if (sentiment === 'negative') return <span className={styles.sentBadge} style={{ background: 'var(--neg-dim)', color: 'var(--neg)' }}>негатив</span>;
  if (sentiment === 'positive') return <span className={styles.sentBadge} style={{ background: 'var(--calm-dim)', color: 'var(--calm)' }}>позитив</span>;
  return <span className={styles.sentBadge} style={{ background: 'var(--surface-3)', color: 'var(--fg-3)' }}>нейтрал</span>;
}

function CommentCard({ c, onApprove, onSkip, onRegenerate }) {
  const [draft, setDraft]   = useState(c.suggestedReply || c.pendingReply || '');
  const [done, setDone]     = useState(c.status !== 'pending');
  const [editing, setEditing] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const hasSuggestion = !!(c.suggestedReply || c.pendingReply);

  function approve() {
    onApprove(c.id, draft);
    setDone(true);
  }
  function skip() {
    onSkip(c.id);
    setDone(true);
  }
  async function regenerate() {
    if (!onRegenerate) return;
    setRegenerating(true);
    const next = await onRegenerate(c.id);
    if (next) setDraft(next);
    setRegenerating(false);
  }

  return (
    <div className={styles.comment} data-done={done ? '1' : '0'}>
      <div className={styles.commentBody}>
        <div className={styles.commentMeta}>
          <div className={styles.commentAvatar}>
            {c.author[0].toUpperCase()}
          </div>
          <span className={styles.commentAuthor}>{c.author}</span>
          <span className={styles.commentFollowers}>{fmtNum(c.followers)} подп.</span>
          {c.is_opportunity && (
            <span className={styles.sentBadge}
              title={c.opportunity || 'Уместный повод ответить от бренда'}
              style={{ background: 'var(--brand-dim, rgba(99,102,241,0.15))', color: 'var(--brand-bright, #818cf8)', marginLeft: 4 }}>
              🎯
            </span>
          )}
          <SentimentBadge sentiment={c.sentiment} />
          {done && <span className={styles.sentBadge} style={{ background: 'var(--calm-dim)', color: 'var(--calm)', marginLeft: 4 }}>✓ отправлен</span>}
        </div>
        <p className={styles.commentText}>{c.text}</p>
      </div>

      {hasSuggestion && !done && (
        <div className={styles.replyArea}>
          <div className={styles.replyLabel}>
            <Icon name="sparkles" size={11} color="var(--brand-bright)" />
            AI-черновик
          </div>
          {editing ? (
            <textarea
              className={styles.replyText}
              value={draft}
              onChange={e => setDraft(e.target.value)}
              autoFocus
            />
          ) : (
            <p style={{ fontSize: 13, color: regenerating ? 'var(--fg-3)' : 'var(--fg-1)', lineHeight: 1.55, cursor: 'text', overflowWrap: 'anywhere', wordBreak: 'break-word' }}
              onClick={() => setEditing(true)}>
              {regenerating ? 'Генерирую черновик…' : draft}
            </p>
          )}
          <div className={styles.replyActions}>
            <button className={`${styles.btn} ${styles.btnDanger}`} onClick={skip}>
              <Icon name="x" size={13} /> Пропустить
            </button>
            {!editing && (
              <button className={`${styles.btn} ${styles.btnGhost}`} onClick={() => setEditing(true)}>
                <Icon name="edit" size={13} /> Изменить
              </button>
            )}
            {onRegenerate && (
              <button className={`${styles.btn} ${styles.btnGhost}`} onClick={regenerate} disabled={regenerating}>
                <Icon name="sparkles" size={13} /> {regenerating ? '…' : 'Заново'}
              </button>
            )}
            <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={approve}>
              <Icon name="send" size={13} /> Отправить
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export function DetailPanel({ item }) {
  const [filter, setFilter] = useState('all');
  const [comments, setComments] = useState(item.comments);
  const [loadingComments, setLoadingComments] = useState(false);
  const isReal = typeof item.id === 'number';
  const laneColor = getLaneColor(item.lane);
  const pendingCount = comments.filter(c => (c.suggestedReply || c.pendingReply) && c.status === 'pending').length;

  // Load real comments from the backend for real mentions (numeric id).
  useEffect(() => {
    setComments(item.comments);
    if (!isReal) return;
    let alive = true;
    setLoadingComments(true);
    api.getComments(item.id)
      .then(data => {
        if (!alive) return;
        if (Array.isArray(data) && data.length) setComments(data);
      })
      .catch(() => {})
      .finally(() => { if (alive) setLoadingComments(false); });
    return () => { alive = false; };
  }, [item.id]);

  function handleApprove(id, draft) {
    setComments(cs => cs.map(c => c.id === id ? { ...c, status: 'approved', draft, suggestedReply: draft } : c));
    if (isReal) api.commentAction(id, 'approve', draft).catch(() => {});
  }
  function handleSkip(id) {
    setComments(cs => cs.map(c => c.id === id ? { ...c, status: 'skipped' } : c));
    if (isReal) api.commentAction(id, 'skip').catch(() => {});
  }
  async function handleRegenerate(id) {
    if (!isReal) return null;
    try {
      const { draft } = await api.regenerateComment(id);
      setComments(cs => cs.map(c => c.id === id ? { ...c, suggestedReply: draft } : c));
      return draft;
    } catch { return null; }
  }

  const filtered = comments.filter(c => {
    if (filter === 'negative') return c.sentiment === 'negative';
    if (filter === 'pending')  return (c.suggestedReply || c.pendingReply) && c.status === 'pending';
    return true;
  });

  const thumbBg = item.lane === 'brand' && item.severity >= 70
    ? 'linear-gradient(135deg, #1a0f0f, #2d1515)'
    : item.lane === 'competitor'
    ? 'linear-gradient(135deg, #130f1a, #1e1430)'
    : 'linear-gradient(135deg, #0f131a, #141d2d)';

  return (
    <div className={styles.panel}>
      {/* Context */}
      <div className={styles.context}>
        <div className={styles.contextTop}>
          <div className={styles.thumbnail} style={{ background: thumbBg }}>
            {THUMB_EMOJI[item.thumbnail] ?? '📢'}
          </div>
          <div className={styles.contextMeta}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: laneColor,
                background: laneColor + '18', padding: '2px 8px', borderRadius: 'var(--r-sm)',
                fontFamily: 'var(--font-mono)', letterSpacing: '0.05em', textTransform: 'uppercase' }}>
                {getLaneLabel(item.lane)}{item.competitor ? ` · ${item.competitor}` : ''}
              </span>
              <Icon name={item.platform} size={16} />
              {item.lane === 'brand' && item.severity >= 50 && (
                <span style={{ fontSize: 11, fontWeight: 700, color: item.severity >= 80 ? 'var(--neg)' : 'var(--rising)',
                  background: item.severity >= 80 ? 'var(--neg-dim)' : 'var(--rising-dim)',
                  padding: '2px 8px', borderRadius: 'var(--r-sm)', fontFamily: 'var(--font-mono)' }}>
                  {item.severity >= 80 ? '🔥' : '⚡'} {item.severity}
                </span>
              )}
            </div>
            <div className={styles.contextTitle}>{item.title}</div>
            <div className={styles.contextAuthor}>
              @{item.author} · {fmtNum(item.authorFollowers)} подп.
            </div>
            <div className={styles.contextStats}>
              <span className={styles.contextStat}><Icon name="eye" size={12} color="var(--fg-4)" />{fmtNum(item.views)}</span>
              <span className={styles.contextStat}><Icon name="messageCircle" size={12} color="var(--fg-4)" />{fmtNum(item.commentsCount)}</span>
              {item.lane === 'brand' && <span className={styles.contextStat} style={{ color: 'var(--neg)' }}>
                <Icon name="activity" size={12} color="var(--neg)" />{item.negativeCommentPct}% негатив
              </span>}
              <span className={styles.contextStat}><Icon name="clock" size={12} color="var(--fg-4)" />{item.ago}</span>
            </div>
          </div>
        </div>

        <div className={styles.aiSummary}>
          <Icon name="sparkles" size={14} color="var(--brand-bright)" style={{ marginTop: 1, flexShrink: 0 }} />
          <p className={styles.aiSummaryText}>{item.summary}</p>
        </div>

        {item.opportunity && (
          <div className={styles.oppBox}>
            <Icon name="zap" size={14} color="var(--brand-bright)" style={{ marginTop: 1, flexShrink: 0 }} />
            <p>{item.opportunity}</p>
          </div>
        )}
      </div>

      {/* Comments header */}
      <div className={styles.commentsHeader}>
        <span className={styles.commentsTitle}>
          Комментарии
          <span style={{ marginLeft: 6, fontSize: 11, color: 'var(--fg-4)', fontFamily: 'var(--font-mono)' }}>
            {comments.length}
          </span>
        </span>
        <div className={styles.filterChips}>
          {['all', 'negative', 'pending'].map(f => (
            <button key={f} className={styles.chip} data-active={filter === f ? '1' : '0'}
              onClick={() => setFilter(f)}>
              {f === 'all' ? 'Все' : f === 'negative' ? 'Негатив' : `Ответить (${pendingCount})`}
            </button>
          ))}
        </div>
      </div>

      {/* Comments list */}
      {loadingComments && (
        <div style={{ padding: '12px 16px', fontSize: 12, color: 'var(--fg-4)' }}>
          Загружаю комментарии…
        </div>
      )}
      <div className={styles.commentsList}>
        {filtered.map(c => (
          <CommentCard key={c.id} c={c} onApprove={handleApprove} onSkip={handleSkip}
            onRegenerate={isReal ? handleRegenerate : undefined} />
        ))}
      </div>

      {/* Bulk bar */}
      {pendingCount > 0 && (
        <div className={styles.bulkBar}>
          <span className={styles.bulkText}>
            <strong style={{ color: 'var(--fg-1)' }}>{pendingCount}</strong> ответов ждут одобрения
          </span>
          <button className={`${styles.btn} ${styles.btnGhost}`}
            onClick={() => {
              if (isReal) comments.forEach(c => c.status === 'pending' && api.commentAction(c.id, 'skip').catch(() => {}));
              setComments(cs => cs.map(c => c.status === 'pending' ? { ...c, status: 'skipped' } : c));
            }}>
            Пропустить все
          </button>
          <button className={`${styles.btn} ${styles.btnSuccess}`}
            onClick={() => {
              const isPending = c => (c.suggestedReply || c.pendingReply) && c.status === 'pending';
              if (isReal) comments.forEach(c => isPending(c) && api.commentAction(c.id, 'approve', c.suggestedReply || c.pendingReply).catch(() => {}));
              setComments(cs => cs.map(c => isPending(c) ? { ...c, status: 'approved' } : c));
            }}>
            <Icon name="checkCircle" size={14} /> Одобрить все
          </button>
        </div>
      )}
    </div>
  );
}

export function EmptyDetail() {
  return (
    <div className={styles.panel}>
      <div className={styles.empty}>
        <div style={{ textAlign: 'center' }}>
          <Icon name="messageCircle" size={32} color="var(--fg-4)" style={{ marginBottom: 12 }} />
          <div style={{ fontSize: 14, color: 'var(--fg-3)' }}>Выберите контент из ленты</div>
        </div>
      </div>
    </div>
  );
}
