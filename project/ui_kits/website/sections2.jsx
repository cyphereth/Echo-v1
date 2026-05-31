// ============================================================================
// Echo Radar — Website kit · sections (part 2: severity, platforms, trust, pricing, cta)
// ============================================================================

function WsRing({ value, color, bright, label, note }) {
  const size = 96, stroke = 9, r = (size - stroke) / 2, c = 2 * Math.PI * r;
  return (
    <div className="ws-sev-card">
      <span style={{ position: 'relative', display: 'inline-grid', placeItems: 'center', width: size, height: size }}>
        <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
          <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="var(--surface-3)" strokeWidth={stroke} />
          <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={color} strokeWidth={stroke}
            strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - value/100)} />
        </svg>
        <span style={{ position: 'absolute', fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 30, color: bright, fontVariantNumeric: 'tabular-nums' }}>{value}</span>
      </span>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.14em', textTransform: 'uppercase', fontWeight: 600, color: bright, marginTop: 14 }}>{label}</div>
      <div style={{ fontSize: 13.5, color: 'var(--fg-2)', marginTop: 8, lineHeight: 1.5 }}>{note}</div>
    </div>
  );
}

function SeverityDemo() {
  return (
    <section className="ws-section">
      <Container>
        <SectionHead center eyebrow="Severity 0–100"
          title="Одно число решает, кто будит PR"
          sub="Спокойствие — фон, срочность — точка. Холодный циан держит эфир под контролем; тёплый цвет вспыхивает, только когда сигнал реально разгоняется." />
        <div className="ws-sev-grid">
          <WsRing value={87} color="#FF4D5E" bright="#FF7A87" label="Залетает" note="Высокая виральность на разгоне — мгновенный пуш в Telegram PR с черновиком." />
          <WsRing value={54} color="#FFB23E" bright="#FFC871" label="Растёт" note="Набирает ускорение. На hot-watch: учащённый перерасчёт, пока не определится фаза." />
          <WsRing value={21} color="#2BB3C7" bright="#57D2E2" label="Под контролем" note="Фоновый шум и нейтральное. Копится в веб-инбоксе SMM, без срочности." />
        </div>
      </Container>
    </section>
  );
}

const PLATFORMS = [
  { pf: 'instagram', name: 'Instagram', st: 'v1 · в эфире', live: true },
  { pf: 'tiktok', name: 'TikTok', st: 'v1 · в эфире', live: true },
  { pf: 'twitter', name: 'Twitter / X', st: 'скоро', live: false },
  { pf: 'telegram', name: 'Telegram', st: 'скоро', live: false },
];
function Platforms() {
  return (
    <section className="ws-section ws-section-alt">
      <Container style={{ display: 'flex', gap: 40, alignItems: 'center', flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 280px' }}>
          <SectionHead eyebrow="Площадки" title="Старт на IG и TikTok. Архитектура — шире."
            sub="Запуск строго на Instagram и TikTok. Коннекторы расширяемы — Twitter и Telegram на очереди." />
        </div>
        <div className="ws-pf-grid">
          {PLATFORMS.map(p => (
            <div key={p.name} className="ws-pf-card">
              <PlatformMark platform={p.pf} size={40} />
              <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--fg-1)', marginTop: 12 }}>{p.name}</div>
              <div className={'ws-pf-st ' + (p.live ? 'ws-live' : '')}>{p.st}</div>
            </div>
          ))}
        </div>
      </Container>
    </section>
  );
}

const TRUST = [
  { icon: 'shieldCheck', t: 'Решение за человеком', d: 'В v1 нет автопубликации. Продукт предлагает черновик — менеджер одобряет, правит или отклоняет.' },
  { icon: 'eye', t: 'Confidence-гейт', d: 'При низкой уверенности классификатора черновик не предлагается — упоминание помечается «решает человек».' },
  { icon: 'sparkles', t: 'Юмор — только вручную', d: 'Шуточные ответы никогда не уходят автоматически. Публикация — только по подтверждению SMM.' },
];
function HumanLoop() {
  return (
    <section className="ws-section">
      <Container>
        <SectionHead center eyebrow="Контроль" title="Радар советует — решаете вы" />
        <div className="ws-trust-grid">
          {TRUST.map(c => (
            <div key={c.t} className="ws-trust-card">
              <span className="ws-trust-ic"><Icon name={c.icon} size={20} color="var(--brand-bright)" /></span>
              <div className="ws-trust-t">{c.t}</div>
              <div className="ws-trust-d">{c.d}</div>
            </div>
          ))}
        </div>
      </Container>
    </section>
  );
}

const TIERS = [
  { name: 'Старт', price: '15 000 ₽', per: '/ мес', limit: '5 000 упоминаний', feats: ['Instagram + TikTok', 'Веб-инбокс PR/SMM', 'Черновики ответов', 'Telegram-пуш'], cta: 'Начать', hot: false },
  { name: 'Рост', price: '39 000 ₽', per: '/ мес', limit: '25 000 упоминаний', feats: ['Всё из «Старт»', 'Hot-watch виральности', 'AI-онбординг зондов', 'Tone-learning по правкам', 'Приоритетный пуш'], cta: 'Запросить демо', hot: true },
  { name: 'Бренд', price: 'По запросу', per: '', limit: 'от 100 000 упоминаний', feats: ['Всё из «Рост»', 'Загрузка эталонных ответов', 'Выделенный канал доставки', 'SLA и поддержка'], cta: 'Связаться', hot: false },
];
function Pricing() {
  return (
    <section className="ws-section ws-section-alt">
      <Container>
        <SectionHead center eyebrow="Тарифы" title="Платите за обработанные упоминания"
          sub="Лимит уникальных упоминаний в месяц — не флэт. Прогноз расхода предупредит до достижения лимита." />
        <div className="ws-price-grid">
          {TIERS.map(t => (
            <div key={t.name} className={'ws-price-card' + (t.hot ? ' ws-price-hot' : '')}>
              {t.hot && <span className="ws-price-badge">Популярный</span>}
              <div className="ws-price-name">{t.name}</div>
              <div className="ws-price-amount"><span>{t.price}</span><em>{t.per}</em></div>
              <div className="ws-price-limit"><Icon name="activity" size={14} color="var(--brand-bright)" />{t.limit} / мес</div>
              <div className="ws-price-feats">
                {t.feats.map(f => <div key={f} className="ws-price-feat"><Icon name="check" size={15} color="var(--sev-calm)" />{f}</div>)}
              </div>
              <a href="#" className={'ws-btn ' + (t.hot ? 'ws-btn-primary' : 'ws-btn-secondary')} style={{ width: '100%', justifyContent: 'center', marginTop: 'auto' }}>{t.cta}</a>
            </div>
          ))}
        </div>
      </Container>
    </section>
  );
}

function CTABand() {
  return (
    <section className="ws-cta">
      <Container style={{ textAlign: 'center' }}>
        <div className="ws-cta-scope"><span /><span /><span /></div>
        <h2 className="ws-h2" style={{ position: 'relative' }}>Поймайте следующий пожар на разгоне</h2>
        <p className="ws-lead" style={{ maxWidth: 520, margin: '16px auto 0', position: 'relative' }}>
          Подключим зонды к вашему бренду за день. Покажем первые сигналы на живых данных.
        </p>
        <div style={{ display: 'flex', gap: 12, justifyContent: 'center', marginTop: 28, position: 'relative' }}>
          <a href="#" className="ws-btn ws-btn-primary ws-btn-lg">Запросить демо</a>
          <a href="#" className="ws-btn ws-btn-ghost ws-btn-lg">Связаться с нами</a>
        </div>
      </Container>
    </section>
  );
}

function Footer() {
  return (
    <footer className="ws-footer">
      <Container style={{ display: 'flex', gap: 40, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <div style={{ flex: '1 1 240px' }}>
          <EchoWordmark size={20} />
          <p style={{ fontSize: 13, color: 'var(--fg-3)', lineHeight: 1.6, marginTop: 14, maxWidth: 280 }}>
            Репутационный радар для брендов в Instagram и TikTok. Ловит виральный негатив на разгоне.
          </p>
        </div>
        {[['Продукт', ['Как работает', 'Severity', 'Площадки', 'Цены']], ['Компания', ['О нас', 'Блог', 'Контакты']], ['Правовое', ['Конфиденциальность', 'Условия']]].map(([h, items]) => (
          <div key={h} style={{ flex: '0 0 auto' }}>
            <div className="ws-foot-h">{h}</div>
            {items.map(i => <a key={i} href="#" className="ws-foot-link">{i}</a>)}
          </div>
        ))}
      </Container>
      <Container style={{ marginTop: 36, paddingTop: 20, borderTop: '1px solid var(--line-1)', display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--fg-3)' }}>© 2026 Echo Radar</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--fg-3)' }}>Сделано для спокойных диспетчеров</span>
      </Container>
    </footer>
  );
}
