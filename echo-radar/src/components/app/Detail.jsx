import { useState, useEffect } from 'react';
import { Icon } from '../shared/icons';
import { PlatformMark, SeverityRing, Sparkline, Eyebrow, SeverityBadge, LaneTag, Button } from '../shared/primitives';
import { PF } from '../shared/primitives';
import { sevTone, PHASE, TONE } from '../../data/mentions';
import styles from './app.module.css';

function ScoreChip({ label, value, color }) {
  return (
    <div className={styles.scoreChip}>
      <Eyebrow>{label}</Eyebrow>
      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 14, color: color || 'var(--fg-1)', fontVariantNumeric: 'tabular-nums' }}>{value}</span>
    </div>
  );
}

function SnapshotChart({ m }) {
  const phase = PHASE[m.phase];
  return (
    <div className={styles.snap}>
      <div className={styles.snapHead}>
        <Eyebrow>Динамика просмотров · hot-watch</Eyebrow>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: 'var(--font-mono)', fontSize: 12, color: phase.color, fontWeight: 600 }}>
          <Icon name={phase.icon} size={14} />{phase.label}
        </span>
      </div>
      <Sparkline data={m.views} color={phase.color} w={372} h={84} />
      <div className={styles.snapFoot}>
        <ScoreChip label="Пик" value={m.peakViews} />
        <ScoreChip label="Скорость" value={m.rate} color={phase.color} />
        <ScoreChip label="Severity" value={`${m.severity}/100`} color={sevTone(m.severity).bright} />
      </div>
    </div>
  );
}

function TelegramPreview({ m }) {
  const [open, setOpen] = useState(false);
  const t = sevTone(m.severity);
  return (
    <div className={styles.tgSection}>
      <button className={styles.tgToggle} onClick={() => setOpen(o => !o)}>
        <Icon name="telegram" size={15} color="#29A9EB" />
        <span style={{ flex: 1, textAlign: 'left' }}>Как уйдёт в Telegram PR</span>
        <Icon name="chevronDown" size={15} color="var(--fg-3)" style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .2s' }} />
      </button>
      {open && (
        <div className={styles.tgCard}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <span style={{ width: 22, height: 22, borderRadius: '50%', background: '#29A9EB', display: 'grid', placeItems: 'center' }}>
              <Icon name="radio" size={13} color="#fff" />
            </span>
            <span style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--fg-1)' }}>Echo Radar bot</span>
          </div>
          <div style={{ fontSize: 13, color: 'var(--fg-2)', lineHeight: 1.5 }}>
            <b style={{ color: t.bright }}>🔴 {t.label} · Severity {m.severity}</b><br />
            {TONE[m.tone].label} · @{m.author} ({PF[m.platform].label})<br />
            <span style={{ color: 'var(--fg-3)' }}>«{m.text.slice(0, 70)}…»</span><br />
            <span style={{ color: 'var(--brand-bright)' }}>Черновик ответа готов → открыть в Echo</span>
          </div>
        </div>
      )}
    </div>
  );
}

export function DetailPanel({ m, onAction }) {
  const [draft, setDraft] = useState(m.draft || '');
  const [editing, setEditing] = useState(false);
  useEffect(() => { setDraft(m.draft || ''); setEditing(false); }, [m.id]);

  const t = sevTone(m.severity);
  const sent = m.status === 'sent';
  const human = m.status === 'human';

  return (
    <aside className={styles.detail}>
      <div className={styles.detailScroll}>
        <div className={styles.detailHead}>
          <PlatformMark platform={m.platform} size={34} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--fg-1)' }}>@{m.author}</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--fg-3)' }}>
              {PF[m.platform].label} · {m.followers.toLocaleString('ru')} подписчиков · {m.ago}
            </div>
          </div>
          <button className={styles.icbtn} style={{ position: 'relative' }}>
            <Icon name="externalLink" size={16} color="var(--fg-2)" />
          </button>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '4px 0 16px' }}>
          {human
            ? <span style={{ width: 56, height: 56, borderRadius: '50%', border: '1px dashed var(--line-strong)', display: 'grid', placeItems: 'center' }}>
                <Icon name="eye" size={22} color="var(--fg-3)" />
              </span>
            : <SeverityRing value={m.severity} size={64} stroke={7} tone={t} />}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
            <SeverityBadge value={m.severity} />
            <LaneTag lane={m.lane} />
          </div>
        </div>

        <blockquote className={styles.quote}>{m.text}</blockquote>

        <div className={styles.metaRow}>
          <ScoreChip label="Тон" value={TONE[m.tone].label} color={TONE[m.tone].color} />
          <ScoreChip label="Увер." value={m.confidence.toFixed(2)} color={m.confidence < 0.6 ? 'var(--sev-rising)' : 'var(--fg-1)'} />
          <ScoreChip label="Категория" value={m.category} />
        </div>

        <SnapshotChart m={m} />

        {human ? (
          <div className={styles.gate}>
            <Icon name="eye" size={16} color="var(--sev-rising)" />
            <div>
              <div style={{ fontWeight: 700, color: 'var(--fg-1)', fontSize: 13.5, marginBottom: 3 }}>Confidence-гейт · решает человек</div>
              <div style={{ fontSize: 13, color: 'var(--fg-2)', lineHeight: 1.5 }}>
                Уверенность классификатора {m.confidence.toFixed(2)} ниже порога 0.60 — черновик не предлагается. Оцените тон вручную.
              </div>
            </div>
          </div>
        ) : (
          <div className={styles.draft}>
            <div className={styles.draftHead}>
              <Eyebrow color="var(--brand-bright)" style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
                <Icon name="sparkles" size={13} />Черновик ответа
              </Eyebrow>
              {m.humor && <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--sev-rising)', background: 'var(--sev-rising-ghost)', border: '1px solid var(--sev-rising-line)', padding: '3px 7px', borderRadius: 999 }}>
                <Icon name="sparkles" size={12} />Юмор · только вручную
              </span>}
            </div>
            {editing
              ? <textarea className={styles.textarea} value={draft} onChange={e => setDraft(e.target.value)} rows={4} autoFocus />
              : <p className={styles.draftBody}>{draft}</p>}
            <TelegramPreview m={m} />
          </div>
        )}
      </div>

      <div className={styles.actions}>
        {sent ? (
          <div className={styles.sent}><Icon name="check" size={16} color="var(--sev-calm)" />Ответ отправлен · правка залогирована</div>
        ) : human ? (
          <>
            <Button variant="danger" icon="flame" onClick={() => onAction(m.id, 'pr')} style={{ flex: 1 }}>В PR — срочно</Button>
            <Button variant="ghost" icon="x" onClick={() => onAction(m.id, 'reject')}>Шум</Button>
          </>
        ) : editing ? (
          <>
            <Button variant="primary" icon="check" onClick={() => { setEditing(false); onAction(m.id, 'approve'); }} style={{ flex: 1 }}>Сохранить и отправить</Button>
            <Button variant="ghost" onClick={() => setEditing(false)}>Отмена</Button>
          </>
        ) : (
          <>
            <Button variant="primary" icon="send" onClick={() => onAction(m.id, 'approve')} style={{ flex: 1 }}>Одобрить и отправить</Button>
            <Button variant="secondary" icon="pencil" onClick={() => setEditing(true)}>Править</Button>
            <Button variant="ghost" icon="x" onClick={() => onAction(m.id, 'reject')} />
          </>
        )}
      </div>
    </aside>
  );
}
