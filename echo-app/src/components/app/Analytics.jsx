import { Icon } from '../shared/icons';
import { FEED_ITEMS } from '../../data/mock';
import styles from './analytics.module.css';

// ── Mock stats ────────────────────────────────────────────────────────────────

const STATS = [
  { label: 'Упоминаний за 7 дней', value: '284',  delta: '+38', up: true,  color: 'var(--fg-1)' },
  { label: 'Негативных',           value: '67',   delta: '+12', up: false, color: 'var(--neg)' },
  { label: 'Ответов отправлено',   value: '41',   delta: '+9',  up: true,  color: 'var(--calm)' },
  { label: 'Среднее время ответа', value: '18м',  delta: '-4м', up: true,  color: 'var(--brand-bright)' },
];

const DAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const NEG_SERIES  = [28, 35, 42, 31, 67, 54, 48];
const POS_SERIES  = [18, 22, 19, 25, 20, 28, 24];
const NEU_SERIES  = [44, 39, 51, 48, 57, 62, 44];

const PLATFORMS = [
  { name: 'TikTok',    icon: 'tiktok',    pct: 58, color: 'var(--tt)', bg: 'var(--surface-3)' },
  { name: 'Instagram', icon: 'instagram', pct: 31, color: 'var(--ig)', bg: '#e1306c22' },
  { name: 'Telegram',  icon: 'telegram',  pct: 11, color: 'var(--tg)', bg: '#29b6f622' },
];

const COMPETITORS = [
  { name: 'DoDo Pizza',  mentions: 142, neg: 61, trend: 'up'   },
  { name: 'Dominos',     mentions: 98,  neg: 55, trend: 'up'   },
  { name: 'Pizza Hut',   mentions: 67,  neg: 38, trend: 'down' },
];

// ── SVG Line Chart ─────────────────────────────────────────────────────────

function LineChart({ series, color, height = 120, width = 100 }) {
  const max   = Math.max(...series);
  const min   = Math.min(...series);
  const range = max - min || 1;
  const W     = 100;
  const H     = height;
  const pad   = 4;
  const step  = (W - pad * 2) / (series.length - 1);

  const pts = series.map((v, i) => {
    const x = pad + i * step;
    const y = H - pad - ((v - min) / range) * (H - pad * 2);
    return `${x},${y}`;
  });

  const area = `M${pts[0]} L${pts.join(' L')} L${pad + (series.length - 1) * step},${H} L${pad},${H} Z`;
  const line = `M${pts.join(' L')}`;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" width="100%" height={H}>
      <defs>
        <linearGradient id={`g${color.replace(/[^a-z]/gi, '')}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.25" />
          <stop offset="100%" stopColor={color} stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#g${color.replace(/[^a-z]/gi, '')})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      {series.map((v, i) => (
        <circle key={i} cx={pad + i * step} cy={H - pad - ((v - min) / range) * (H - pad * 2)}
          r="2.5" fill={color} />
      ))}
    </svg>
  );
}

function MultiLineChart({ height = 140 }) {
  const allVals = [...NEG_SERIES, ...POS_SERIES, ...NEU_SERIES];
  const max = Math.max(...allVals);
  const min = 0;
  const range = max - min || 1;
  const W = 100; const H = height; const pad = 4;
  const step = (W - pad * 2) / (DAYS.length - 1);

  function pts(series) {
    return series.map((v, i) => {
      const x = pad + i * step;
      const y = H - pad - ((v - min) / range) * (H - pad * 2);
      return `${x},${y}`;
    });
  }

  const series = [
    { data: NEG_SERIES, color: 'var(--neg)',   label: 'Негатив' },
    { data: POS_SERIES, color: 'var(--calm)',  label: 'Позитив' },
    { data: NEU_SERIES, color: 'var(--fg-4)',  label: 'Нейтрал' },
  ];

  return (
    <div>
      {/* Legend */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 12 }}>
        {series.map(s => (
          <span key={s.label} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}>
            <span style={{ width: 20, height: 2, background: s.color, borderRadius: 2, display: 'inline-block' }} />
            {s.label}
          </span>
        ))}
      </div>
      <div className={styles.chartWrap}>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" width="100%" height={H}>
          {/* Grid lines */}
          {[0.25, 0.5, 0.75, 1].map(t => (
            <line key={t} x1={pad} y1={pad + (1 - t) * (H - pad * 2)}
              x2={W - pad} y2={pad + (1 - t) * (H - pad * 2)}
              stroke="rgba(255,255,255,0.05)" strokeWidth="1" />
          ))}
          {series.map(s => {
            const p = pts(s.data);
            return (
              <g key={s.label}>
                <path d={`M${p.join(' L')}`} fill="none" stroke={s.color}
                  strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                {s.data.map((v, i) => (
                  <circle key={i} cx={pad + i * step}
                    cy={H - pad - ((v - min) / range) * (H - pad * 2)}
                    r="2" fill={s.color} />
                ))}
              </g>
            );
          })}
        </svg>
      </div>
      <div className={styles.chartLabels}>
        {DAYS.map(d => <span key={d} className={styles.chartLabel}>{d}</span>)}
      </div>
    </div>
  );
}

// ── Analytics page ─────────────────────────────────────────────────────────

export function AnalyticsScreen() {
  const topVideos = [...FEED_ITEMS]
    .filter(v => v.lane === 'brand')
    .sort((a, b) => b.severity - a.severity)
    .slice(0, 4);

  return (
    <div className={styles.page}>

      {/* Stat cards */}
      <div className={styles.statRow}>
        {STATS.map(s => (
          <div key={s.label} className={styles.statCard}>
            <div className={styles.statLabel}>{s.label}</div>
            <div className={styles.statValue} style={{ color: s.color }}>{s.value}</div>
            <span className={styles.statDelta} style={{ color: s.up ? 'var(--calm)' : 'var(--neg)' }}>
              <Icon name={s.up ? 'trendingUp' : 'activity'} size={12} />
              {s.delta} за 7 дней
            </span>
          </div>
        ))}
      </div>

      {/* Chart + Platforms */}
      <div className={styles.row2}>
        <div className={styles.card}>
          <div className={styles.cardTitle}>
            <Icon name="activity" size={15} color="var(--brand-bright)" />
            Динамика настроений
          </div>
          <MultiLineChart />
        </div>

        <div className={styles.card}>
          <div className={styles.cardTitle}>
            <Icon name="pieChart" size={15} color="var(--brand-bright)" />
            По платформам
          </div>
          <div className={styles.platformRows}>
            {PLATFORMS.map(p => (
              <div key={p.name} className={styles.platformRow}>
                <div className={styles.platformName}>
                  <Icon name={p.icon} size={16} />
                  {p.name}
                </div>
                <div className={styles.barTrack}>
                  <div className={styles.barFill} style={{ width: `${p.pct}%`, background: p.color }} />
                </div>
                <span className={styles.platformVal} style={{ color: 'var(--fg-2)' }}>{p.pct}%</span>
              </div>
            ))}
          </div>

          <div style={{ marginTop: 24 }}>
            <div className={styles.cardTitle} style={{ marginBottom: 12 }}>
              <Icon name="zap" size={15} color="var(--rising)" />
              Конкуренты
            </div>
            <div className={styles.compTable}>
              {COMPETITORS.map(c => (
                <div key={c.name} className={styles.compRow}>
                  <span className={styles.compName}>{c.name}</span>
                  <span className={styles.compStat}>
                    <Icon name="messageCircle" size={12} color="var(--fg-4)" />
                    {c.mentions}
                  </span>
                  <span className={styles.pill} style={{
                    background: c.neg > 55 ? 'var(--neg-dim)' : 'var(--rising-dim)',
                    color: c.neg > 55 ? 'var(--neg)' : 'var(--rising)',
                  }}>
                    {c.neg}% neg
                  </span>
                  <Icon name={c.trend === 'up' ? 'trendingUp' : 'activity'} size={13}
                    color={c.trend === 'up' ? 'var(--neg)' : 'var(--calm)'} />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Top negative videos */}
      <div className={styles.card}>
        <div className={styles.cardTitle}>
          <Icon name="flame" size={15} color="var(--neg)" />
          Топ негативных упоминаний
        </div>
        <div className={styles.videoList}>
          {topVideos.map((v, i) => (
            <div key={v.id} className={styles.videoRow}>
              <span className={styles.videoRank}>#{i + 1}</span>
              <div className={styles.videoInfo}>
                <div className={styles.videoTitle}>{v.title}</div>
                <div className={styles.videoMeta}>
                  <span className={styles.videoStat}>
                    <Icon name={v.platform} size={12} />
                    @{v.author}
                  </span>
                  <span className={styles.videoStat}>
                    <Icon name="eye" size={11} color="var(--fg-4)" />
                    {v.views >= 1000 ? `${(v.views/1000).toFixed(1)}k` : v.views}
                  </span>
                  <span className={styles.videoStat} style={{ color: 'var(--neg)' }}>
                    <Icon name="activity" size={11} color="var(--neg)" />
                    {v.negativeCommentPct}% негатив
                  </span>
                </div>
              </div>
              <span className={styles.pill} style={{
                background: v.severity >= 80 ? 'var(--neg-dim)' : 'var(--rising-dim)',
                color: v.severity >= 80 ? 'var(--neg)' : 'var(--rising)',
              }}>
                {v.severity >= 80 ? '🔥' : '⚡'} {v.severity}
              </span>
            </div>
          ))}
        </div>
      </div>

    </div>
  );
}
