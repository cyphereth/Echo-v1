import { EchoWordmark } from '../components/shared/EchoWordmark';
import { Icon } from '../components/shared/icons';
import { PlatformMark } from '../components/shared/primitives';
import styles from '../styles/website.module.css';

function Container({ children, style }) {
  return <div style={{ width: '100%', maxWidth: 1120, margin: '0 auto', padding: '0 28px', ...style }}>{children}</div>;
}

function Eyebrow({ children, color = 'var(--brand-bright)' }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontFamily: 'var(--font-mono)',
      fontSize: 12, letterSpacing: '0.18em', textTransform: 'uppercase', fontWeight: 600, color }}>{children}</span>
  );
}

function SectionHead({ eyebrow, title, sub, center }) {
  return (
    <div style={{ maxWidth: 680, margin: center ? '0 auto' : 0, textAlign: center ? 'center' : 'left', marginBottom: 44 }}>
      <Eyebrow>{eyebrow}</Eyebrow>
      <h2 style={{ fontWeight: 800, fontSize: 34, lineHeight: 1.12, letterSpacing: '-0.02em', color: 'var(--fg-1)', margin: '14px 0 0' }}>{title}</h2>
      {sub && <p style={{ fontSize: 17, lineHeight: 1.6, color: 'var(--fg-2)', fontWeight: 500, margin: '14px 0 0' }}>{sub}</p>}
    </div>
  );
}

function Header() {
  const links = ['Как работает', 'Severity', 'Площадки', 'Цены'];
  return (
    <header className={styles.header}>
      <Container style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
        <EchoWordmark size={22} />
        <nav className={styles.nav}>{links.map(l => <a key={l} href="#" className={styles.navLink}>{l}</a>)}</nav>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 12 }}>
          <a href="#" className={styles.navLink}>Войти</a>
          <a href="#" className={`${styles.btn} ${styles.btnPrimary}`}>Запросить демо</a>
        </div>
      </Container>
    </header>
  );
}

function MiniMention() {
  return (
    <div className={styles.miniCard}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
        <span className={styles.miniPf}><Icon name="tiktok" size={15} color="#EAF1F8" /></span>
        <div style={{ flex: 1, lineHeight: 1.2 }}>
          <div style={{ fontSize: 12.5, fontWeight: 700, color: 'var(--fg-1)' }}>@user123</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: 'var(--fg-3)' }}>TikTok · 14 мин</div>
        </div>
        <span className={styles.miniSev}>87</span>
      </div>
      <div style={{ fontSize: 12, color: 'var(--fg-2)', lineHeight: 1.45, marginTop: 9 }}>
        «…привезли через 2 часа и всё холодное. Снимаю на видео 👇»
      </div>
      <div className={styles.miniTag}><span className={styles.blip} />Залетает · в PR за минуты</div>
    </div>
  );
}

function HeroScope() {
  return (
    <div className={styles.scope}>
      <div className={styles.scopeRings}><span /><span /><span /><span /></div>
      <div className={styles.scopeSweep} />
      <span className={styles.scopeBlip} style={{ left: '64%', top: '32%' }} />
      <span className={`${styles.scopeBlip} ${styles.amber}`} style={{ left: '32%', top: '58%' }} />
      <span className={`${styles.scopeBlip} ${styles.cyan}`} style={{ left: '50%', top: '72%' }} />
      <MiniMention />
    </div>
  );
}

function Hero() {
  return (
    <section className={styles.hero}>
      <Container>
        <div className={styles.heroGrid} style={{ display: 'grid', gridTemplateColumns: '1.05fr 0.95fr', gap: 48, alignItems: 'center' }}>
          <div>
            <Eyebrow><span className={styles.liveDot} />Репутационный радар · Instagram и TikTok</Eyebrow>
            <h1 style={{ fontWeight: 800, fontSize: 52, lineHeight: 1.06, letterSpacing: '-0.025em', color: 'var(--fg-1)', margin: '20px 0 0' }}>
              Ловите негатив, пока у ролика тысяча просмотров, а&nbsp;не&nbsp;<span style={{ color: 'var(--brand-bright)' }}>миллион</span>
            </h1>
            <p style={{ fontSize: 17, lineHeight: 1.6, color: 'var(--fg-2)', fontWeight: 500, margin: '22px 0 0', maxWidth: 520 }}>
              Echo Radar предсказывает виральность на разгоне и отдаёт готовый черновик
              ответа на одобрение. Вы тушите пожар, пока он управляемый, — а не оплачиваете последствия.
            </p>
            <div style={{ display: 'flex', gap: 12, marginTop: 30 }}>
              <a href="#" className={`${styles.btn} ${styles.btnPrimary} ${styles.btnLg}`}>Запросить демо</a>
              <a href="#" className={`${styles.btn} ${styles.btnGhost} ${styles.btnLg}`}>Как это работает</a>
            </div>
            <div style={{ display: 'flex', gap: 22, marginTop: 26, flexWrap: 'wrap' }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 13, fontWeight: 600, color: 'var(--fg-2)' }}>
                <Icon name="shieldCheck" size={15} color="var(--sev-calm)" />Решение всегда за человеком
              </span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: 13, fontWeight: 600, color: 'var(--fg-2)' }}>
                <Icon name="zap" size={15} color="var(--brand-bright)" />Пуш в PR за минуты
              </span>
            </div>
          </div>
          <HeroScope />
        </div>
      </Container>
    </section>
  );
}

function Stakes() {
  return (
    <section className={styles.section}>
      <Container>
        <SectionHead
          eyebrow="Почему разгон, а не пик"
          title="Между «тысяча просмотров» и «миллион» — несколько часов"
          sub="Обычный мониторинг покажет негатив, когда он уже везде. Радар ловит ускорение раньше пика — пока ответ ещё что-то меняет." />
        <div className={styles.curve}>
          <svg viewBox="0 0 720 220" className={styles.curveSvg} preserveAspectRatio="none">
            <defs>
              <linearGradient id="ws-fill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="#FF4D5E" stopOpacity="0.22" /><stop offset="1" stopColor="#FF4D5E" stopOpacity="0" />
              </linearGradient>
            </defs>
            <path d="M0 205 C 220 200 300 195 380 150 C 440 116 470 40 560 22 C 620 12 680 12 720 12 L720 220 L0 220 Z" fill="url(#ws-fill)" />
            <path d="M0 205 C 220 200 300 195 380 150 C 440 116 470 40 560 22 C 620 12 680 12 720 12" fill="none" stroke="#FF6473" strokeWidth="2.5" />
          </svg>
          <div className={styles.mark} style={{ left: '40%', top: '54%' }}>
            <span className={`${styles.markDot} ${styles.cyan}`} />
            <div className={styles.markCard}>
              <Eyebrow color="var(--brand-bright)">Echo ловит здесь</Eyebrow>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--fg-1)', fontWeight: 600, marginTop: 5 }}>Ускорение растёт · 1.2k → 4.8k</div>
              <div style={{ fontSize: 12, color: 'var(--fg-3)', marginTop: 3 }}>Управляемо · черновик готов</div>
            </div>
          </div>
          <div className={`${styles.mark} ${styles.markLate}`} style={{ right: '3%', top: '7%' }}>
            <span className={`${styles.markDot} ${styles.crimson}`} />
            <div className={`${styles.markCard} ${styles.markCardLate}`}>
              <Eyebrow color="#FF7A87">Замечают обычно здесь</Eyebrow>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--fg-1)', fontWeight: 600, marginTop: 5 }}>1 200 000 просмотров</div>
              <div style={{ fontSize: 12, color: 'var(--fg-3)', marginTop: 3 }}>Кризис · поздно отвечать</div>
            </div>
          </div>
        </div>
      </Container>
    </section>
  );
}

const PIPELINE = [
  { icon: 'radio',     t: 'Сбор',          d: 'Зонды по ключам и хэштегам опрашивают IG и TikTok с адаптивным интервалом' },
  { icon: 'filter',    t: 'Классификация',  d: 'Каскад LLM размечает тон и категорию, отсеивает шум и омонимы' },
  { icon: 'activity',  t: 'Скоринг',        d: 'Severity по скорости и ускорению — ловит до пика, не после' },
  { icon: 'sparkles',  t: 'Черновик',       d: 'Готовый ответ с конкретным следующим шагом, а не «нам жаль»' },
  { icon: 'send',      t: 'Доставка',       d: 'Срочное — пушем в Telegram PR, остальное — в веб-инбокс' },
];

function Pipeline() {
  return (
    <section className={`${styles.section} ${styles.sectionAlt}`}>
      <Container>
        <SectionHead center eyebrow="Конвейер" title="От сигнала до ответа — за минуты"
          sub="Один поток: поймали, поняли, оценили, ответили. Hot-watch возвращает растущие посты на учащённый перерасчёт." />
        <div className={styles.pipe}>
          {PIPELINE.map((s, i) => (
            <>
              <div key={s.t} className={styles.pipeStep}>
                <span className={styles.pipeIc}><Icon name={s.icon} size={20} color="var(--brand-bright)" /></span>
                <div className={styles.pipeTitle}>{s.t}</div>
                <div className={styles.pipeDesc}>{s.d}</div>
              </div>
              {i < PIPELINE.length - 1 && (
                <span key={`arr-${i}`} style={{ display: 'grid', placeItems: 'center', flexShrink: 0 }}>
                  <Icon name="chevronRight" size={18} color="var(--line-strong)" />
                </span>
              )}
            </>
          ))}
        </div>
      </Container>
    </section>
  );
}

function WsRing({ value, color, bright, label, note }) {
  const size = 96, stroke = 9, r = (size - stroke) / 2, c = 2 * Math.PI * r;
  return (
    <div className={styles.sevCard}>
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
    <section className={styles.section}>
      <Container>
        <SectionHead center eyebrow="Severity 0–100" title="Одно число решает, кто будит PR"
          sub="Спокойствие — фон, срочность — точка. Холодный циан держит эфир под контролем; тёплый цвет вспыхивает, только когда сигнал реально разгоняется." />
        <div className={styles.sevGrid}>
          <WsRing value={87} color="#FF4D5E" bright="#FF7A87" label="Залетает" note="Высокая виральность на разгоне — мгновенный пуш в Telegram PR с черновиком." />
          <WsRing value={54} color="#FFB23E" bright="#FFC871" label="Растёт"   note="Набирает ускорение. На hot-watch: учащённый перерасчёт, пока не определится фаза." />
          <WsRing value={21} color="#2BB3C7" bright="#57D2E2" label="Под контролем" note="Фоновый шум и нейтральное. Копится в веб-инбоксе SMM, без срочности." />
        </div>
      </Container>
    </section>
  );
}

const PLATFORMS = [
  { pf: 'instagram', name: 'Instagram',   st: 'v1 · в эфире', live: true },
  { pf: 'tiktok',    name: 'TikTok',      st: 'v1 · в эфире', live: true },
  { pf: 'twitter',   name: 'Twitter / X', st: 'скоро',         live: false },
  { pf: 'telegram',  name: 'Telegram',    st: 'скоро',         live: false },
];

function Platforms() {
  return (
    <section className={`${styles.section} ${styles.sectionAlt}`}>
      <Container style={{ display: 'flex', gap: 40, alignItems: 'center', flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 280px' }}>
          <SectionHead eyebrow="Площадки" title="Старт на IG и TikTok. Архитектура — шире."
            sub="Запуск строго на Instagram и TikTok. Коннекторы расширяемы — Twitter и Telegram на очереди." />
        </div>
        <div className={styles.pfGrid}>
          {PLATFORMS.map(p => (
            <div key={p.name} className={styles.pfCard}>
              <PlatformMark platform={p.pf} size={40} radius={9} />
              <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--fg-1)', marginTop: 12 }}>{p.name}</div>
              <div className={`${styles.pfStatus} ${p.live ? styles.live : ''}`}>{p.st}</div>
            </div>
          ))}
        </div>
      </Container>
    </section>
  );
}

const TRUST = [
  { icon: 'shieldCheck', t: 'Решение за человеком', d: 'В v1 нет автопубликации. Продукт предлагает черновик — менеджер одобряет, правит или отклоняет.' },
  { icon: 'eye',         t: 'Confidence-гейт',      d: 'При низкой уверенности классификатора черновик не предлагается — упоминание помечается «решает человек».' },
  { icon: 'sparkles',    t: 'Юмор — только вручную', d: 'Шуточные ответы никогда не уходят автоматически. Публикация — только по подтверждению SMM.' },
];

function HumanLoop() {
  return (
    <section className={styles.section}>
      <Container>
        <SectionHead center eyebrow="Контроль" title="Радар советует — решаете вы" />
        <div className={styles.trustGrid}>
          {TRUST.map(c => (
            <div key={c.t} className={styles.trustCard}>
              <span className={styles.trustIc}><Icon name={c.icon} size={20} color="var(--brand-bright)" /></span>
              <div style={{ fontSize: 17, fontWeight: 700, color: 'var(--fg-1)', marginBottom: 9 }}>{c.t}</div>
              <div style={{ fontSize: 14, lineHeight: 1.6, color: 'var(--fg-3)' }}>{c.d}</div>
            </div>
          ))}
        </div>
      </Container>
    </section>
  );
}

const TIERS = [
  { name: 'Старт', price: '15 000 ₽', per: '/ мес', limit: '5 000 упоминаний',    feats: ['Instagram + TikTok', 'Веб-инбокс PR/SMM', 'Черновики ответов', 'Telegram-пуш'], cta: 'Начать', hot: false },
  { name: 'Рост',  price: '39 000 ₽', per: '/ мес', limit: '25 000 упоминаний',   feats: ['Всё из «Старт»', 'Hot-watch виральности', 'AI-онбординг зондов', 'Tone-learning по правкам', 'Приоритетный пуш'], cta: 'Запросить демо', hot: true },
  { name: 'Бренд', price: 'По запросу',per: '',      limit: 'от 100 000 упоминаний',feats: ['Всё из «Рост»', 'Загрузка эталонных ответов', 'Выделенный канал доставки', 'SLA и поддержка'], cta: 'Связаться', hot: false },
];

function Pricing() {
  return (
    <section className={`${styles.section} ${styles.sectionAlt}`}>
      <Container>
        <SectionHead center eyebrow="Тарифы" title="Платите за обработанные упоминания"
          sub="Лимит уникальных упоминаний в месяц — не флэт. Прогноз расхода предупредит до достижения лимита." />
        <div className={styles.priceGrid}>
          {TIERS.map(t => (
            <div key={t.name} className={`${styles.priceCard} ${t.hot ? styles.priceHot : ''}`}>
              {t.hot && <span className={styles.priceBadge}>Популярный</span>}
              <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--brand-bright)' }}>{t.name}</div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, margin: '12px 0 4px' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 30, fontWeight: 700, color: 'var(--fg-1)', whiteSpace: 'nowrap' }}>{t.price}</span>
                <em style={{ fontStyle: 'normal', fontSize: 14, color: 'var(--fg-3)' }}>{t.per}</em>
              </div>
              <div style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 13, color: 'var(--fg-2)', paddingBottom: 18, borderBottom: '1px solid var(--line-1)', marginBottom: 18 }}>
                <Icon name="activity" size={14} color="var(--brand-bright)" />{t.limit} / мес
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 11, marginBottom: 24 }}>
                {t.feats.map(f => (
                  <div key={f} style={{ display: 'flex', alignItems: 'flex-start', gap: 9, fontSize: 13.5, color: 'var(--fg-2)', lineHeight: 1.4 }}>
                    <Icon name="check" size={15} color="var(--sev-calm)" />{f}
                  </div>
                ))}
              </div>
              <a href="#" className={`${styles.btn} ${t.hot ? styles.btnPrimary : styles.btnSecondary}`}
                style={{ width: '100%', justifyContent: 'center', marginTop: 'auto' }}>{t.cta}</a>
            </div>
          ))}
        </div>
      </Container>
    </section>
  );
}

function CTABand() {
  return (
    <section className={styles.cta}>
      <Container style={{ textAlign: 'center' }}>
        <div className={styles.ctaScope}><span /><span /><span /></div>
        <h2 style={{ fontWeight: 800, fontSize: 34, lineHeight: 1.12, letterSpacing: '-0.02em', color: 'var(--fg-1)', position: 'relative' }}>
          Поймайте следующий пожар на разгоне
        </h2>
        <p style={{ fontSize: 17, lineHeight: 1.6, color: 'var(--fg-2)', fontWeight: 500, maxWidth: 520, margin: '16px auto 0', position: 'relative' }}>
          Подключим зонды к вашему бренду за день. Покажем первые сигналы на живых данных.
        </p>
        <div style={{ display: 'flex', gap: 12, justifyContent: 'center', marginTop: 28, position: 'relative' }}>
          <a href="#" className={`${styles.btn} ${styles.btnPrimary} ${styles.btnLg}`}>Запросить демо</a>
          <a href="#" className={`${styles.btn} ${styles.btnGhost} ${styles.btnLg}`}>Связаться с нами</a>
        </div>
      </Container>
    </section>
  );
}

function Footer() {
  const cols = [
    ['Продукт', ['Как работает', 'Severity', 'Площадки', 'Цены']],
    ['Компания', ['О нас', 'Блог', 'Контакты']],
    ['Правовое', ['Конфиденциальность', 'Условия']],
  ];
  return (
    <footer className={styles.footer}>
      <Container style={{ display: 'flex', gap: 40, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <div style={{ flex: '1 1 240px' }}>
          <EchoWordmark size={20} />
          <p style={{ fontSize: 13, color: 'var(--fg-3)', lineHeight: 1.6, marginTop: 14, maxWidth: 280 }}>
            Репутационный радар для брендов в Instagram и TikTok. Ловит виральный негатив на разгоне.
          </p>
        </div>
        {cols.map(([h, items]) => (
          <div key={h} style={{ flexShrink: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg-1)', marginBottom: 14 }}>{h}</div>
            {items.map(i => <a key={i} href="#" className={styles.footLink}>{i}</a>)}
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

export default function WebsitePage() {
  return (
    <div className={styles.site}>
      <Header />
      <main style={{ paddingTop: 64 }}>
        <Hero />
        <Stakes />
        <Pipeline />
        <SeverityDemo />
        <Platforms />
        <HumanLoop />
        <Pricing />
        <CTABand />
      </main>
      <Footer />
    </div>
  );
}
