// ============================================================================
// Echo Radar — Website kit · sections (part 1: header, hero, stakes, pipeline)
// ============================================================================

function Container({ children, style }) {
  return <div style={{ width: '100%', maxWidth: 1120, margin: '0 auto', padding: '0 28px', ...style }}>{children}</div>;
}
function Eyebrow({ children, color = 'var(--brand-bright)' }) {
  return <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontFamily: 'var(--font-mono)',
    fontSize: 12, letterSpacing: '0.18em', textTransform: 'uppercase', fontWeight: 600, color }}>{children}</span>;
}
function SectionHead({ eyebrow, title, sub, center }) {
  return (
    <div style={{ maxWidth: 680, margin: center ? '0 auto' : 0, textAlign: center ? 'center' : 'left', marginBottom: 44 }}>
      <Eyebrow>{eyebrow}</Eyebrow>
      <h2 className="ws-h2" style={{ margin: '14px 0 0' }}>{title}</h2>
      {sub && <p className="ws-lead" style={{ margin: '14px 0 0' }}>{sub}</p>}
    </div>
  );
}

function Header() {
  const links = ['Как работает', 'Severity', 'Площадки', 'Цены'];
  return (
    <header className="ws-header">
      <Container style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
        <EchoWordmark size={22} />
        <nav className="ws-nav">{links.map(l => <a key={l} href="#" className="ws-navlink">{l}</a>)}</nav>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 12 }}>
          <a href="#" className="ws-navlink">Войти</a>
          <a href="#" className="ws-btn ws-btn-primary">Запросить демо</a>
        </div>
      </Container>
    </header>
  );
}

// floating caught-mention card used in the hero scope
function MiniMention() {
  return (
    <div className="ws-mini">
      <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
        <span className="ws-mini-pf"><Icon name="tiktok" size={15} color="#EAF1F8" /></span>
        <div style={{ flex: 1, lineHeight: 1.2 }}>
          <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--fg-1)' }}>@user123</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--fg-3)' }}>TikTok · 14 мин</div>
        </div>
        <span className="ws-mini-sev">87</span>
      </div>
      <div style={{ fontSize: 12, color: 'var(--fg-2)', lineHeight: 1.45, marginTop: 9 }}>«…привезли через 2 часа и всё холодное. Снимаю на видео 👇»</div>
      <div className="ws-mini-tag"><span className="ws-blip" />Залетает · в PR за минуты</div>
    </div>
  );
}

function HeroScope() {
  return (
    <div className="ws-scope">
      <div className="ws-scope-rings"><span /><span /><span /><span /></div>
      <div className="ws-scope-sweep" />
      <span className="ws-scope-blip" style={{ left: '64%', top: '32%' }} />
      <span className="ws-scope-blip ws-amber" style={{ left: '32%', top: '58%' }} />
      <span className="ws-scope-blip ws-cyan" style={{ left: '50%', top: '72%' }} />
      <MiniMention />
    </div>
  );
}

function Hero() {
  return (
    <section className="ws-hero">
      <Container style={{ display: 'grid', gridTemplateColumns: '1.05fr 0.95fr', gap: 48, alignItems: 'center' }}>
        <div>
          <Eyebrow><span className="ws-livedot" />Репутационный радар · Instagram и TikTok</Eyebrow>
          <h1 className="ws-h1" style={{ margin: '20px 0 0' }}>
            Ловите негатив, пока у ролика тысяча просмотров, а&nbsp;не&nbsp;<span className="ws-accent">миллион</span>
          </h1>
          <p className="ws-lead" style={{ margin: '22px 0 0', maxWidth: 520 }}>
            Echo Radar предсказывает виральность на разгоне и отдаёт готовый черновик
            ответа на одобрение. Вы тушите пожар, пока он управляемый, — а не оплачиваете последствия.
          </p>
          <div style={{ display: 'flex', gap: 12, marginTop: 30 }}>
            <a href="#" className="ws-btn ws-btn-primary ws-btn-lg">Запросить демо</a>
            <a href="#" className="ws-btn ws-btn-ghost ws-btn-lg">Как это работает</a>
          </div>
          <div className="ws-trust">
            <span><Icon name="shieldCheck" size={15} color="var(--sev-calm)" />Решение всегда за человеком</span>
            <span><Icon name="zap" size={15} color="var(--brand-bright)" />Пуш в PR за минуты</span>
          </div>
        </div>
        <HeroScope />
      </Container>
    </section>
  );
}

function Stakes() {
  return (
    <section className="ws-section">
      <Container>
        <SectionHead
          eyebrow="Почему разгон, а не пик"
          title="Между «тысяча просмотров» и «миллион» — несколько часов"
          sub="Обычный мониторинг покажет негатив, когда он уже везде. Радар ловит ускорение раньше пика — пока ответ ещё что-то меняет." />
        <div className="ws-curve">
          <svg viewBox="0 0 720 220" className="ws-curve-svg" preserveAspectRatio="none">
            <defs>
              <linearGradient id="ws-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="#FF4D5E" stopOpacity="0.22" /><stop offset="1" stopColor="#FF4D5E" stopOpacity="0" />
              </linearGradient>
            </defs>
            <path d="M0 205 C 220 200 300 195 380 150 C 440 116 470 40 560 22 C 620 12 680 12 720 12 L720 220 L0 220 Z" fill="url(#ws-fill)" />
            <path d="M0 205 C 220 200 300 195 380 150 C 440 116 470 40 560 22 C 620 12 680 12 720 12" fill="none" stroke="#FF6473" strokeWidth="2.5" />
          </svg>
          <div className="ws-mark ws-mark-early" style={{ left: '40%', top: '54%' }}>
            <span className="ws-mark-dot ws-cyan" />
            <div className="ws-mark-card">
              <Eyebrow color="var(--brand-bright)">Echo ловит здесь</Eyebrow>
              <div className="ws-mark-t">Ускорение растёт · 1.2k → 4.8k</div>
              <div className="ws-mark-s">Управляемо · черновик готов</div>
            </div>
          </div>
          <div className="ws-mark ws-mark-late" style={{ right: '3%', top: '7%' }}>
            <span className="ws-mark-dot ws-crimson" />
            <div className="ws-mark-card ws-mark-card-late">
              <Eyebrow color="#FF7A87">Замечают обычно здесь</Eyebrow>
              <div className="ws-mark-t">1 200 000 просмотров</div>
              <div className="ws-mark-s">Кризис · поздно отвечать</div>
            </div>
          </div>
        </div>
      </Container>
    </section>
  );
}

const PIPELINE = [
  { icon: 'radio', t: 'Сбор', d: 'Зонды по ключам и хэштегам опрашивают IG и TikTok с адаптивным интервалом' },
  { icon: 'filter', t: 'Классификация', d: 'Каскад LLM размечает тон и категорию, отсеивает шум и омонимы' },
  { icon: 'activity', t: 'Скоринг', d: 'Severity по скорости и ускорению — ловит до пика, не после' },
  { icon: 'sparkles', t: 'Черновик', d: 'Готовый ответ с конкретным следующим шагом, а не «нам жаль»' },
  { icon: 'send', t: 'Доставка', d: 'Срочное — пушем в Telegram PR, остальное — в веб-инбокс' },
];
function Pipeline() {
  return (
    <section className="ws-section ws-section-alt">
      <Container>
        <SectionHead center eyebrow="Конвейер" title="От сигнала до ответа — за минуты"
          sub="Один поток: поймали, поняли, оценили, ответили. Hot-watch возвращает растущие посты на учащённый перерасчёт." />
        <div className="ws-pipe">
          {PIPELINE.map((s, i) => (
            <React.Fragment key={s.t}>
              <div className="ws-pipe-step">
                <span className="ws-pipe-ic"><Icon name={s.icon} size={20} color="var(--brand-bright)" /></span>
                <div className="ws-pipe-t">{s.t}</div>
                <div className="ws-pipe-d">{s.d}</div>
              </div>
              {i < PIPELINE.length - 1 && <span className="ws-pipe-arrow"><Icon name="chevronRight" size={18} color="var(--line-strong)" /></span>}
            </React.Fragment>
          ))}
        </div>
      </Container>
    </section>
  );
}
