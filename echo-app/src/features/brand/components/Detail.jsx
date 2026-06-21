// Detail panel — канон: project/ui_kits/app/detail.jsx.
// 446px правая панель: SeverityRing 64 + badges + blockquote поста + meta-чипы
// + snapshot графика + draft editor (textarea + brand-glow) + Telegram-превью +
// действия в футере (Одобрить/Править/Отклонить). Confidence-гейт → человек.
// Comments — нижняя вторичная секция (оставлена: workflow одобрения ответов).
import { useState, useEffect } from 'react';
import { Icon } from '../../../core/components/icons';
import { Button, Eyebrow, SeverityBadge, LaneTag, PlatformMark, ScoreChip } from '../../../core/components/ui';
import { SeverityRing } from '../../../core/components/SeverityRing';
import { Sparkline } from '../../../core/components/Sparkline';
import { sevTone, fmtNum, PHASE, TONE } from '../../../core/utils/format';
import * as api from '../api';
import styles from '../../../components/app/detail.module.css';

// ── Lane mapping для бренд-режима ───────────────────────────────────────────
function laneTagOf(item) {
  if (item.status === 'human') return 'none';
  const s = item.severity || 0;
  if (s >= 75 || (item.lane === 'brand' && item.tone === 'negative' && s >= 45)) return 'PR';
  return 'SMM';
}

function StatusFlag({ status }) {
  if (status === 'sent' || status === 'approved')
    return <span className={styles.flag} style={{ color: 'var(--sev-calm)' }}><Icon name="check" size={12} color="var(--sev-calm)" />Отправлено</span>;
  if (status === 'human' || status === 'none')
    return <span className={styles.flag} style={{ color: 'var(--fg-3)' }}><Icon name="eye" size={12} color="var(--fg-3)" />Решает человек</span>;
  return <span className={styles.flag} style={{ color: 'var(--brand-bright)' }}>Новое</span>;
}

function TelegramPreview({ item, draft, sevLabel }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={styles.tg}>
      <button className={styles.tgToggle} data-open={open ? '1' : '0'} onClick={() => setOpen(o => !o)}>
        <Icon name="telegram" size={15} color="#29A9EB" />
        Как уйдёт в Telegram PR
        <Icon name="chevronDown" size={13} color="var(--fg-3)" className="tgToggleChev" style={{ marginLeft: 'auto' }} />
      </button>
      {open && (
        <div className={styles.tgCard}>
          <div className={styles.tgHead}>
            <span style={{ width: 22, height: 22, borderRadius: '50%', background: '#29A9EB', display: 'grid', placeItems: 'center', flex: 'none' }}>
              <Icon name="radio" size={12} color="#fff" />
            </span>
            Echo Radar bot
          </div>
          <div className={styles.tgBody}>
            <strong>🔴 {sevLabel} · Severity {item.severity}</strong><br />
            {TONE[item.tone]?.label || '—'} · @{item.author} · {item.platform}
          </div>
          <div className={styles.tgQuote}>{item.title}</div>
          <div className={styles.tgCta}>Черновик ответа готов → открыть в Echo</div>
          {draft && <div className={styles.tgBody} style={{ color: 'var(--fg-1)' }}>{draft}</div>}
        </div>
      )}
    </div>
  );
}

// ── Comment card (secondary) ────────────────────────────────────────────────
function CommentCard({ c, onApprove, onSkip, onRegenerate }) {
  const [draft, setDraft]       = useState(c.suggestedReply || c.pendingReply || '');
  const [done, setDone]         = useState(c.status !== 'pending');
  const [editing, setEditing]   = useState(false);
  const [regenerating, setReg]  = useState(false);
  const hasSuggestion = !!(c.suggestedReply || c.pendingReply);

  function approve() { onApprove(c.id, draft); setDone(true); }
  function skip()    { onSkip(c.id); setDone(true); }
  async function regenerate() {
    if (!onRegenerate) return;
    setReg(true);
    const next = await onRegenerate(c.id);
    if (next) setDraft(next);
    setReg(false);
  }

  return (
    <div className={styles.comment} data-done={done ? '1' : '0'}>
      <div className={styles.commentBody}>
        <div className={styles.commentMeta}>
          <div className={styles.commentAvatar}>{(c.author || '?')[0].toUpperCase()}</div>
          <span className={styles.commentAuthor}>{c.author}</span>
          <span className={styles.commentFollowers}>{fmtNum(c.followers)} подп.</span>
          <SentMini sentiment={c.sentiment} />
          {done && <span className={styles.sentBadge} style={{ background: 'var(--sev-calm-ghost)', color: 'var(--sev-calm)' }}>✓ отправлен</span>}
        </div>
        <p className={styles.commentText}>{c.text}</p>
      </div>
      {hasSuggestion && !done && (
        <div className={styles.replyArea}>
          <div className={styles.replyLabel}><Icon name="sparkles" size={11} color="var(--brand-bright)" />AI-черновик</div>
          {editing ? (
            <textarea className={styles.replyText} value={draft} onChange={e => setDraft(e.target.value)} autoFocus />
          ) : (
            <p className={styles.commentText} style={{ cursor: 'text' }} onClick={() => setEditing(true)}>
              {regenerating ? 'Генерирую черновик…' : draft}
            </p>
          )}
          <div className={styles.replyActions}>
            <Button variant="danger" size="sm" icon="x" onClick={skip}>Пропустить</Button>
            {!editing && <Button variant="ghost" size="sm" icon="edit" onClick={() => setEditing(true)}>Изменить</Button>}
            {onRegenerate && <Button variant="ghost" size="sm" icon="refresh" onClick={regenerate} disabled={regenerating}>{regenerating ? '…' : 'Заново'}</Button>}
            <Button variant="primary" size="sm" icon="send" onClick={approve}>Отправить</Button>
          </div>
        </div>
      )}
    </div>
  );
}

function SentMini({ sentiment }) {
  if (sentiment === 'negative') return <span className={styles.sentBadge} style={{ background: 'var(--sev-critical-ghost)', color: 'var(--sev-critical-bright)' }}>негатив</span>;
  if (sentiment === 'positive') return <span className={styles.sentBadge} style={{ background: 'var(--sev-calm-ghost)', color: 'var(--sev-calm)' }}>позитив</span>;
  return <span className={styles.sentBadge} style={{ background: 'var(--surface-3)', color: 'var(--fg-3)' }}>нейтрал</span>;
}

// ── DetailPanel ─────────────────────────────────────────────────────────────
export function DetailPanel({ item }) {
  const [comments, setComments]       = useState(item.comments);
  const [loadingComments, setLoading] = useState(false);
  const isReal  = typeof item.id === 'number';
  const tone    = sevTone(item.severity);
  const phase   = PHASE[item.phase] || PHASE.unknown;
  const lane    = laneTagOf(item);
  const confLow = (item.confidence || 0) < 0.6;

  // draft editor state
  const [draft, setDraft]     = useState(item.draft || '');
  const [editing, setEditing] = useState(false);
  const [sent, setSent]       = useState(item.status === 'sent');
  const [showComments, setShowComments] = useState(false);

  useEffect(() => {
    setDraft(item.draft || '');
    setEditing(false);
    setSent(item.status === 'sent');
    setComments(item.comments);
    setShowComments(false);
    if (!isReal) return;
    let alive = true;
    setLoading(true);
    api.getComments(item.id)
      .then(data => { if (alive && Array.isArray(data) && data.length) setComments(data); })
      .catch(() => {})
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [item.id, item.draft, item.status, item.comments, isReal]);

  const pendingComments = comments.filter(c => (c.suggestedReply || c.pendingReply) && c.status === 'pending');

  // действия с mention-уровнем (PR lane): approve / regenerate
  async function approveMention() {
    if (isReal) {
      try { await api.postAction(item.id, 'approve', draft); }
      catch { /* правило «решает человек»: даже при 503 показываем отправку */ }
    }
    setSent(true); setEditing(false);
  }
  async function regenerateMention() {
    if (!isReal) return;
    try {
      const { draft: next } = await api.regenerateDraft(item.id);
      if (next) setDraft(next);
    } catch { /* 503 no LLM key — тихо */ }
  }

  function handleApproveComment(id, d) {
    setComments(cs => cs.map(c => c.id === id ? { ...c, status: 'approved', draft: d, suggestedReply: d } : c));
    if (isReal) api.commentAction(id, 'approve', d).catch(() => {});
  }
  function handleSkipComment(id) {
    setComments(cs => cs.map(c => c.id === id ? { ...c, status: 'skipped' } : c));
    if (isReal) api.commentAction(id, 'skip').catch(() => {});
  }
  async function handleRegenComment(id) {
    if (!isReal) return null;
    try {
      const { draft: next } = await api.regenerateComment(id);
      setComments(cs => cs.map(c => c.id === id ? { ...c, suggestedReply: next } : c));
      return next;
    } catch { return null; }
  }

  const sevLabel = tone.label;

  return (
    <div className={styles.panel}>
      <div className={styles.scroll}>
        {/* head: platform + author + meta + external link */}
        <div className={styles.head}>
          <PlatformMark platform={item.platform} size={34} />
          <div className={styles.headMeta}>
            <div className={styles.headAuthor}>@{item.author}</div>
            <div className={styles.headSub}>
              {item.platform} · {fmtNum(item.authorFollowers)} подписчиков · {item.ago}
            </div>
          </div>
          {item.url && (
            <a href={item.url} target="_blank" rel="noopener noreferrer"
              style={{ display: 'inline-flex', padding: 8, color: 'var(--fg-3)', borderRadius: 'var(--r-md)' }}>
              <Icon name="externalLink" size={15} />
            </a>
          )}
        </div>

        {/* severity row: ring + badges */}
        <div className={styles.sevRow}>
          {item.status === 'human'
            ? <span style={{ width: 56, height: 56, borderRadius: '50%', border: '1px dashed var(--line-strong)', display: 'grid', placeItems: 'center', flex: 'none' }}>
                <Icon name="eye" size={20} color="var(--fg-3)" />
              </span>
            : <SeverityRing value={item.severity} size={64} stroke={7} />}
          <div className={styles.sevBadges}>
            {item.severity > 0 && <SeverityBadge value={item.severity} />}
            <LaneTag lane={lane} />
            <StatusFlag status={item.status} />
          </div>
        </div>

        {/* post text */}
        <blockquote className={styles.quote}>{item.summary}</blockquote>

        {/* meta chips: тон / уверенность / категория */}
        <div className={styles.metaRow}>
          <ScoreChip label="Тон" valueColor={TONE[item.tone]?.color || 'var(--fg-1)'}>
            {TONE[item.tone]?.label || '—'}
          </ScoreChip>
          <ScoreChip label="Увер." valueColor={confLow ? 'var(--sev-rising-bright)' : 'var(--fg-1)'}>
            {Math.round((item.confidence || 0) * 100)}%
          </ScoreChip>
          <ScoreChip label="Категория">
            {item.category || '—'}
          </ScoreChip>
        </div>

        {/* snapshot / dynamics */}
        {item.viewsSeries && item.viewsSeries.length > 1 && (
          <div className={styles.snap}>
            <div className={styles.snapHead}>
              <Eyebrow>Динамика просмотров · hot-watch</Eyebrow>
              <span className={styles.replyLabel} style={{ color: phase.color }}>{phase.label}</span>
            </div>
            <Sparkline data={item.viewsSeries} color={phase.color} w={372} h={84} />
            <div className={styles.snapFoot}>
              <ScoreChip label="Пик">{fmtNum(Math.max(...item.viewsSeries))}</ScoreChip>
              <ScoreChip label="Severity" valueColor={tone.bright}>{Math.round(item.severity)}/100</ScoreChip>
            </div>
          </div>
        )}

        {/* draft / confidence gate */}
        {confLow && !sent ? (
          <div className={styles.gate}>
            <Icon name="eye" size={18} color="var(--sev-rising-bright)" style={{ marginTop: 1 }} />
            <div className={styles.gateText}>
              <strong>Confidence-гейт</strong> · решает человек. Классификатор не уверен
              ({Math.round((item.confidence || 0) * 100)}%), черновик не предлагается автоматически.
            </div>
          </div>
        ) : draft ? (
          <>
            <div className={styles.draft}>
              <div className={styles.draftHead}>
                <Icon name="sparkles" size={14} color="var(--brand-bright)" />
                <Eyebrow color="var(--brand-bright)">Черновик ответа</Eyebrow>
                {item.humor && <span className={styles.replyLabel} style={{ marginLeft: 'auto', color: 'var(--sev-rising)' }}>Юмор · вручную</span>}
              </div>
              <div className={styles.draftBody}>
                {editing ? (
                  <textarea className={styles.draftText} value={draft} onChange={e => setDraft(e.target.value)} autoFocus />
                ) : (
                  <span>{draft}</span>
                )}
              </div>
            </div>
            {!sent && <TelegramPreview item={item} draft={draft} sevLabel={sevLabel} />}
          </>
        ) : null}

        {/* comments (secondary) */}
        {(comments.length > 0 || loadingComments) && (
          <div className={styles.commentsHeader}>
            <span className={styles.commentsTitle}>Комментарии</span>
            <span className={styles.commentsCount}>{comments.length}</span>
            {pendingComments.length > 0 && (
              <span className={styles.commentsCount} style={{ color: 'var(--sev-critical-bright)' }}>
                · {pendingComments.length} ждут
              </span>
            )}
            <button className={styles.tgToggle} style={{ marginLeft: 'auto', padding: '4px 8px' }}
              data-open={showComments ? '1' : '0'} onClick={() => setShowComments(s => !s)}>
              {showComments ? 'Скрыть' : 'Показать'}
              <Icon name="chevronDown" size={12} color="var(--fg-3)" style={{ marginLeft: 'auto' }} />
            </button>
          </div>
        )}
        {showComments && (
          <div className={styles.commentsList}>
            {loadingComments && <div style={{ fontSize: 12, color: 'var(--fg-3)' }}>Загружаю комментарии…</div>}
            {comments.map(c => (
              <CommentCard key={c.id} c={c} onApprove={handleApproveComment} onSkip={handleSkipComment}
                onRegenerate={isReal ? handleRegenComment : undefined} />
            ))}
          </div>
        )}
      </div>

      {/* actions footer */}
      <div className={styles.actions}>
        {sent ? (
          <div className={styles.sentState}>
            <Icon name="check" size={15} color="var(--sev-calm)" />
            Ответ отправлен · правка залогирована
          </div>
        ) : confLow ? (
          <Button variant="danger" icon="flame" onClick={() => { setEditing(true); }} style={{ flex: 1 }}>В PR — срочно</Button>
        ) : editing ? (
          <>
            <Button variant="primary" icon="send" onClick={approveMention} style={{ flex: 1 }}>Сохранить и отправить</Button>
            <Button variant="ghost" icon="x" onClick={() => setEditing(false)}>Отмена</Button>
          </>
        ) : (
          <>
            <Button variant="primary" icon="send" onClick={approveMention} style={{ flex: 1 }}>Одобрить и отправить</Button>
            <Button variant="secondary" icon="pencil" onClick={() => setEditing(true)}>Править</Button>
            <Button variant="ghost" size="sm" icon="refresh" onClick={regenerateMention} title="Сгенерировать заново" />
          </>
        )}
      </div>
    </div>
  );
}

export function EmptyDetail() {
  return (
    <div className={styles.panel}>
      <div className={styles.empty}>
        <div>
          <Icon name="radio" size={34} color="var(--fg-4)" />
          <div className={styles.emptyTitle}>Выберите сигнал из ленты</div>
        </div>
      </div>
    </div>
  );
}
