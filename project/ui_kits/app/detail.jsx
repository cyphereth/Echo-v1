// ============================================================================
// Echo Radar — App UI kit · detail panel (post, snapshot, draft, actions)
// ============================================================================

function ScoreChip({ label, value, color }) {
  return (
    <div className="er-score">
      <Eyebrow>{label}</Eyebrow>
      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 14, color: color || 'var(--fg-1)', fontVariantNumeric: 'tabular-nums' }}>{value}</span>
    </div>
  );
}

function SnapshotChart({ m }) {
  const phase = PHASE[m.phase];
  return (
    <div className="er-snap">
      <div className="er-snap-head">
        <Eyebrow>Динамика просмотров · hot-watch</Eyebrow>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: 'var(--font-mono)', fontSize: 12, color: phase.color, fontWeight: 600 }}>
          <Icon name={phase.icon} size={14} />{phase.label}
        </span>
      </div>
      <Sparkline data={m.views} color={phase.color} w={372} h={84} />
      <div className="er-snap-foot">
        <ScoreChip label="Пик" value={m.peakViews} />
        <ScoreChip label="Скорость" value={m.rate} color={phase.color} />
        <ScoreChip label="Severity" value={`${m.severity}/100`} color={sevTone(m.severity).bright} />
      </div>
    </div>
  );
}

function TelegramPreview({ m }) {
  const [open, setOpen] = React.useState(false);
  const t = sevTone(m.severity);
  return (
    <div className="er-tg">
      <button className="er-tg-toggle" onClick={() => setOpen(o => !o)}>
        <Icon name="telegram" size={15} color="#29A9EB" />
        <span style={{ flex: 1, textAlign: 'left' }}>Как уйдёт в Telegram PR</span>
        <Icon name="chevronDown" size={15} color="var(--fg-3)" style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .2s' }} />
      </button>
      {open && (
        <div className="er-tg-card">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <span style={{ width: 22, height: 22, borderRadius: '50%', background: '#29A9EB', display: 'grid', placeItems: 'center' }}><Icon name="radio" size={13} color="#fff" /></span>
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

function DetailPanel({ m, onAction }) {
  const [draft, setDraft] = React.useState(m.draft || '');
  const [editing, setEditing] = React.useState(false);
  React.useEffect(() => { setDraft(m.draft || ''); setEditing(false); }, [m.id]);

  const t = sevTone(m.severity);
  const sent = m.status === 'sent';
  const human = m.status === 'human';

  return (
    <aside className="er-detail">
      <div className="er-detail-scroll">
        {/* header */}
        <div className="er-detail-head">
          <PlatformMark platform={m.platform} size={34} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--fg-1)' }}>@{m.author}</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--fg-3)' }}>{PF[m.platform].label} · {m.followers.toLocaleString('ru')} подписчиков · {m.ago}</div>
          </div>
          <button className="er-icbtn"><Icon name="externalLink" size={16} color="var(--fg-2)" /></button>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '4px 0 16px' }}>
          {human ? <span className="er-human" style={{ width: 56, height: 56 }}><Icon name="eye" size={22} color="var(--fg-3)" /></span>
                 : <SeverityRing value={m.severity} size={64} stroke={7} tone={t} />}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
            {human ? <SeverityBadge value={m.severity} /> : <SeverityBadge value={m.severity} />}
            <LaneTag lane={m.lane} />
          </div>
        </div>

        {/* the post */}
        <blockquote className="er-quote">{m.text}</blockquote>

        <div className="er-meta-row">
          <ScoreChip label="Тон" value={TONE[m.tone].label} color={TONE[m.tone].color} />
          <ScoreChip label="Увер." value={m.confidence.toFixed(2)} color={m.confidence < 0.6 ? 'var(--sev-rising)' : 'var(--fg-1)'} />
          <ScoreChip label="Категория" value={m.category} />
        </div>

        <SnapshotChart m={m} />

        {/* draft */}
        {human ? (
          <div className="er-gate">
            <Icon name="eye" size={16} color="var(--sev-rising)" />
            <div>
              <div style={{ fontWeight: 700, color: 'var(--fg-1)', fontSize: 13.5, marginBottom: 3 }}>Confidence-гейт · решает человек</div>
              <div style={{ fontSize: 13, color: 'var(--fg-2)', lineHeight: 1.5 }}>Уверенность классификатора {m.confidence.toFixed(2)} ниже порога 0.60 — черновик не предлагается. Оцените тон вручную.</div>
            </div>
          </div>
        ) : (
          <div className="er-draft">
            <div className="er-draft-head">
              <Eyebrow color="var(--brand-bright)" style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
                <Icon name="sparkles" size={13} />Черновик ответа
              </Eyebrow>
              {m.humor && <span className="er-humor"><Icon name="sparkles" size={12} />Юмор · только вручную</span>}
            </div>
            {editing
              ? <textarea className="er-textarea" value={draft} onChange={e => setDraft(e.target.value)} rows={4} autoFocus />
              : <p className="er-draft-body">{draft}</p>}
            <TelegramPreview m={m} />
          </div>
        )}
      </div>

      {/* actions */}
      <div className="er-actions">
        {sent ? (
          <div className="er-sent"><Icon name="check" size={16} color="var(--sev-calm)" />Ответ отправлен · правка залогирована</div>
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
