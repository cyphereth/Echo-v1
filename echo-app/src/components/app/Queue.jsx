import { useState } from 'react';
import { Icon } from '../shared/icons';
import { FEED_ITEMS, getLaneColor, getLaneLabel } from '../../data/mock';
import styles from './queue.module.css';

function fmtNum(n) {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

// Flatten all comments with pending replies into queue items
function buildQueue() {
  const items = [];
  for (const video of FEED_ITEMS) {
    const pending = video.comments.filter(c => c.suggestedReply || c.pendingReply);
    if (pending.length > 0) {
      items.push({ video, comments: pending });
    }
  }
  return items;
}

function ReplyCard({ c, onApprove, onSkip }) {
  const [draft, setDraft]   = useState(c.suggestedReply || c.pendingReply || '');
  const [editing, setEditing] = useState(false);
  const [done, setDone]     = useState(false);
  const [doneType, setDoneType] = useState(null);

  function approve() {
    onApprove(c.id, draft);
    setDone(true);
    setDoneType('sent');
  }
  function skip() {
    onSkip(c.id);
    setDone(true);
    setDoneType('skipped');
  }

  return (
    <div className={styles.card} data-done={done ? '1' : '0'}>
      <div className={styles.cardComment}>
        <div className={styles.commentMeta}>
          <div className={styles.avatar}>{c.author[0].toUpperCase()}</div>
          <span className={styles.author}>{c.author}</span>
          <span className={styles.followers}>{fmtNum(c.followers)} подп.</span>
          {c.sentiment === 'negative' && (
            <span className={styles.sentBadge} style={{ background: 'var(--neg-dim)', color: 'var(--neg)' }}>
              негатив
            </span>
          )}
          {done && (
            <span className={styles.sentBadge} style={{
              background: doneType === 'sent' ? 'var(--calm-dim)' : 'var(--surface-3)',
              color: doneType === 'sent' ? 'var(--calm)' : 'var(--fg-3)',
              marginLeft: 4,
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
            <Icon name="sparkles" size={11} />
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
            <p style={{ fontSize: 13, color: 'var(--fg-1)', lineHeight: 1.55, cursor: 'text', padding: '8px 0' }}
              onClick={() => setEditing(true)}>
              {draft}
            </p>
          )}
          <div className={styles.actions}>
            <button className={`${styles.btn} ${styles.btnDanger}`} onClick={skip}>
              <Icon name="x" size={13} />Пропустить
            </button>
            {!editing && (
              <button className={`${styles.btn} ${styles.btnGhost}`} onClick={() => setEditing(true)}>
                <Icon name="edit" size={13} />Изменить
              </button>
            )}
            <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={approve}>
              <Icon name="send" size={13} />Отправить
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

const LANE_FILTERS = ['all', 'brand', 'competitor', 'niche'];

export function QueueScreen() {
  const [laneFilter, setLaneFilter] = useState('all');
  const [states, setStates] = useState({});

  const raw = buildQueue();
  const groups = raw.filter(g =>
    laneFilter === 'all' || g.video.lane === laneFilter
  );

  const totalPending = raw.reduce((sum, g) => sum + g.comments.length, 0);
  const approved     = Object.values(states).filter(s => s === 'approved').length;
  const skipped      = Object.values(states).filter(s => s === 'skipped').length;

  function onApprove(id) { setStates(s => ({ ...s, [id]: 'approved' })); }
  function onSkip(id)    { setStates(s => ({ ...s, [id]: 'skipped' })); }

  function approveAll() {
    const ids = {};
    for (const g of groups) for (const c of g.comments) ids[c.id] = 'approved';
    setStates(s => ({ ...s, ...ids }));
  }

  const pendingLeft = totalPending - approved - skipped;

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
          отправлено сегодня
        </span>
        <div className={styles.sep} />
        <span className={styles.barStat}>
          <span className={styles.barVal}>{skipped}</span>
          пропущено
        </span>

        <div className={styles.filters}>
          {LANE_FILTERS.map(f => (
            <button key={f} className={styles.chip} data-active={laneFilter === f ? '1' : '0'}
              onClick={() => setLaneFilter(f)}>
              {f === 'all' ? 'Все' : getLaneLabel(f)}
            </button>
          ))}
        </div>
      </div>

      {pendingLeft === 0 && approved === 0 ? (
        <div className={styles.empty}>
          <div style={{ textAlign: 'center' }}>
            <Icon name="checkCircle" size={36} color="var(--calm)" style={{ marginBottom: 12 }} />
            <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--fg-2)', marginBottom: 6 }}>Всё обработано</div>
            <div style={{ fontSize: 13, color: 'var(--fg-4)' }}>Новые ответы появятся когда Echo найдёт упоминания</div>
          </div>
        </div>
      ) : (
        <>
          <div className={styles.list}>
            {groups.map(({ video, comments }) => {
              const laneColor = getLaneColor(video.lane);
              const liveComments = comments.filter(c => !states[c.id]);
              if (liveComments.length === 0 && groups.length > 1) return null;
              return (
                <div key={video.id} className={styles.group}>
                  <div className={styles.groupHeader}>
                    <Icon name={video.platform} size={15} />
                    <span style={{ width: 8, height: 8, borderRadius: '50%', background: laneColor, flexShrink: 0 }} />
                    <span className={styles.groupTitle}>{video.title}</span>
                    <span className={styles.groupCount}>{liveComments.length} ответов</span>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {comments.map(c => (
                      <ReplyCard key={c.id} c={{ ...c, status: states[c.id] ? 'done' : 'pending' }}
                        onApprove={onApprove} onSkip={onSkip} />
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
              <button className={`${styles.btn} ${styles.btnGhost}`} onClick={() => {
                const ids = {};
                for (const g of groups) for (const c of g.comments) ids[c.id] = 'skipped';
                setStates(s => ({ ...s, ...ids }));
              }}>
                Пропустить все
              </button>
              <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={approveAll}>
                <Icon name="checkCircle" size={14} />
                Одобрить все ({pendingLeft})
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
