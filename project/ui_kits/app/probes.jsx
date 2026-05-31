// ============================================================================
// Echo Radar — App UI kit · probes screen (AI onboarding + active probes)
// ============================================================================

const ACTIVE_PROBES = [
  { kind: 'keyword', q: 'испорченный заказ', pf: ['instagram','tiktok'], interval: '4 мин', trend: 'up',   last: '12 сек', hot: true,  mentions: 23 },
  { kind: 'hashtag', q: '#папапицца',        pf: ['instagram','tiktok'], interval: '8 мин', trend: 'flat', last: '1 мин',  hot: false, mentions: 64 },
  { kind: 'mention', q: '@papapizza',        pf: ['instagram','tiktok'], interval: '6 мин', trend: 'flat', last: '40 сек', hot: false, mentions: 41 },
  { kind: 'keyword', q: 'холодная пицца',    pf: ['instagram','tiktok'], interval: '12 мин',trend: 'down', last: '3 мин',  hot: false, mentions: 9 },
];
const AI_SUGGEST = ['вернули деньги', '#отзывброкен', 'курьер опоздал', 'заказ не привезли', 'долгая доставка'];
const KIND = { keyword: 'Ключевое слово', hashtag: 'Хэштег', mention: 'Упоминание' };

function ProbesScreen() {
  const [chips, setChips] = React.useState(AI_SUGGEST.map(q => ({ q, added: false })));
  const add = (i) => setChips(cs => cs.map((c, j) => j === i ? { ...c, added: true } : c));

  return (
    <div className="er-probes">
      {/* what is a probe — plain language */}
      <div className="er-probes-intro">
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 800, letterSpacing: '-0.02em', color: 'var(--fg-1)' }}>Зонды</h2>
        <p style={{ margin: '8px 0 0', fontSize: 14, lineHeight: 1.6, color: 'var(--fg-2)', maxWidth: 640 }}>
          Зонд — это поисковый запрос по ключевому слову или хэштегу, которым Echo Radar
          непрерывно ищет упоминания <b style={{ color: 'var(--fg-1)' }}>{BRAND.name}</b> в Instagram и TikTok.
          Чем точнее зонды — тем меньше шума и точнее severity.
        </p>
      </div>

      {/* AI onboarding */}
      <div className="er-onb">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
          <span className="er-onb-ic"><Icon name="sparkles" size={16} color="var(--brand-bright)" /></span>
          <div>
            <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--fg-1)' }}>AI-настройка зондов</div>
            <div style={{ fontSize: 12.5, color: 'var(--fg-3)' }}>Дайте ссылку на бренд — предложим ключевые слова и хэштеги</div>
          </div>
        </div>
        <div className="er-onb-input">
          <Icon name="link" size={15} color="var(--fg-3)" />
          <span style={{ flex: 1, color: 'var(--fg-1)', fontSize: 13.5 }}>papapizza.ru</span>
          <Button variant="primary" size="sm" icon="sparkles">Разобрать</Button>
        </div>
        <Eyebrow style={{ display: 'block', margin: '16px 0 10px' }}>Предложено AI — подтвердите нужные</Eyebrow>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {chips.map((c, i) => (
            <button key={i} className="er-chip-ai" data-added={c.added ? '1' : '0'} onClick={() => add(i)}>
              <Icon name={c.added ? 'check' : 'plus'} size={13} />{c.q}
            </button>
          ))}
        </div>
      </div>

      {/* active probes */}
      <div className="er-probe-list">
        <div className="er-probe-listhead">
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 9 }}>
            <Icon name="radio" size={16} color="var(--brand-bright)" />
            <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--fg-1)' }}>Активные зонды</span>
            <span className="er-count" style={{ color: 'var(--brand-bright)' }}>{ACTIVE_PROBES.length}</span>
          </span>
          <Button variant="ghost" size="sm" icon="plus">Зонд вручную</Button>
        </div>
        {ACTIVE_PROBES.map((p, i) => (
          <div key={i} className="er-probe-row">
            <span className="er-probe-kind">{KIND[p.kind]}</span>
            <span style={{ flex: 1, minWidth: 0 }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13.5, color: 'var(--fg-1)', fontWeight: 500 }}>{p.q}</span>
            </span>
            <span style={{ display: 'flex', gap: 5 }}>
              {p.pf.map(pf => <Icon key={pf} name={pf} size={15} color={pf === 'instagram' ? '#E1306C' : 'var(--fg-2)'} />)}
            </span>
            <span className="er-probe-int">
              <Icon name={p.trend === 'up' ? 'trendingUp' : p.trend === 'down' ? 'trendingDown' : 'activity'} size={13}
                color={p.trend === 'up' ? 'var(--sev-rising)' : 'var(--fg-3)'} />
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--fg-2)' }}>{p.interval}</span>
            </span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5, color: 'var(--fg-3)', width: 88, textAlign: 'right' }}>{p.mentions} упом.</span>
            <span className="er-probe-last">
              <span className="er-dot-live" style={{ background: p.hot ? 'var(--sev-rising)' : 'var(--sev-calm)' }} />
              {p.last}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
