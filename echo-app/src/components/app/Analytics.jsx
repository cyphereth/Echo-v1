import { useState, useEffect } from 'react';
import { Icon } from '../shared/icons';
import * as api from '../../services/api';
import styles from './analytics.module.css';

// ── Fallback (demo) data — used when the backend has no real data yet ─────────

const STATS_MOCK = [
  { key: 'total', label: 'Упоминаний за 7 дней', value: '284',  delta: '+38', up: true  },
  { key: 'neg',   label: 'Негативных',           value: '67',   delta: '+12', up: false },
  { key: 'sent',  label: 'Ответов отправлено',   value: '41',   delta: '+9',  up: true  },
  { key: 'hot',   label: 'Горячих сейчас',       value: '3',    delta: '3',   up: false },
];
const STAT_COLOR = {
  total: 'var(--fg-1)', neg: 'var(--neg)', sent: 'var(--calm)', hot: 'var(--rising)',
};

const SERIES_MOCK = {
  days: ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'],
  neg:  [28, 35, 42, 31, 67, 54, 48],
  pos:  [18, 22, 19, 25, 20, 28, 24],
  neu:  [44, 39, 51, 48, 57, 62, 44],
};

const PLATFORM_ICON = { TikTok: 'tiktok', Instagram: 'instagram', Telegram: 'telegram' };
const PLATFORM_COLOR = { TikTok: 'var(--tt)', Instagram: 'var(--ig)', Telegram: 'var(--tg)' };
const PLATFORMS_MOCK = [
  { name: 'TikTok',    pct: 58 },
  { name: 'Instagram', pct: 31 },
  { name: 'Telegram',  pct: 11 },
];

const COMPETITORS_MOCK = [
  { name: 'DoDo Pizza',  mentions: 142, neg: 61, trend: 'up'   },
  { name: 'Dominos',     mentions: 98,  neg: 55, trend: 'up'   },
  { name: 'Pizza Hut',   mentions: 67,  neg: 38, trend: 'down' },
];

// ── SVG multi-line chart ─────────────────────────────────────────────────────

function MultiLineChart({ series, height = 140 }) {
  const { days, neg, pos, neu } = series;
  const allVals = [...neg, ...pos, ...neu];
  const max = Math.max(...allVals, 1);
  const min = 0;
  const range = max - min || 1;
  const W = 100; const H = height; const pad = 4;
  const step = (W - pad * 2) / Math.max(days.length - 1, 1);

  function pts(data) {
    return data.map((v, i) => {
      const x = pad + i * step;
      const y = H - pad - ((v - min) / range) * (H - pad * 2);
      return `${x},${y}`;
    });
  }

  const lines = [
    { data: neg, color: 'var(--neg)',  label: 'Негатив' },
    { data: pos, color: 'var(--calm)', label: 'Позитив' },
    { data: neu, color: 'var(--fg-4)', label: 'Нейтрал' },
  ];

  return (
    <div>
      <div style={{ display: 'flex', gap: 16, marginBottom: 12 }}>
        {lines.map(s => (
          <span key={s.label} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--fg-3)', fontFamily: 'var(--font-mono)' }}>
            <span style={{ width: 20, height: 2, background: s.color, borderRadius: 2, display: 'inline-block' }} />
            {s.label}
          </span>
        ))}
      </div>
      <div className={styles.chartWrap}>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" width="100%" height={H}>
          {[0.25, 0.5, 0.75, 1].map(t => (
            <line key={t} x1={pad} y1={pad + (1 - t) * (H - pad * 2)}
              x2={W - pad} y2={pad + (1 - t) * (H - pad * 2)}
              stroke="rgba(255,255,255,0.05)" strokeWidth="1" />
          ))}
          {lines.map(s => {
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
        {days.map((d, i) => <span key={i} className={styles.chartLabel}>{d}</span>)}
      </div>
    </div>
  );
}

// ── Analytics page ───────────────────────────────────────────────────────────

export function AnalyticsScreen({ brandId }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    if (typeof brandId !== 'number') return;
    let alive = true;
    api.getAnalytics(brandId)
      .then(d => { if (alive && d && d.has_data) setData(d); })
      .catch(() => { /* keep demo fallback */ });
    return () => { alive = false; };
  }, [brandId]);

  const stats     = data?.stats?.length        ? data.stats        : STATS_MOCK;
  const series    = data?.series?.days?.length  ? data.series       : SERIES_MOCK;
  const platforms = data?.platforms?.length     ? data.platforms    : PLATFORMS_MOCK;
  const competitors = data?.competitors?.length ? data.competitors  : COMPETITORS_MOCK;
  const topVideos = data?.top_negative?.length
    ? data.top_negative
    : [];

  return (
    <div className={styles.page}>

      {/* Stat cards */}
      <div className={styles.statRow}>
        {stats.map(s => (
          <div key={s.key ?? s.label} className={styles.statCard}>
            <div className={styles.statLabel}>{s.label}</div>
            <div className={styles.statValue} style={{ color: STAT_COLOR[s.key] ?? 'var(--fg-1)' }}>{s.value}</div>
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
          <MultiLineChart series={series} />
        </div>

        <div className={styles.card}>
          <div className={styles.cardTitle}>
            <Icon name="pieChart" size={15} color="var(--brand-bright)" />
            По платформам
          </div>
          <div className={styles.platformRows}>
            {platforms.map(p => (
              <div key={p.name} className={styles.platformRow}>
                <div className={styles.platformName}>
                  <Icon name={PLATFORM_ICON[p.name] ?? 'radio'} size={16} />
                  {p.name}
                </div>
                <div className={styles.barTrack}>
                  <div className={styles.barFill} style={{ width: `${p.pct}%`, background: PLATFORM_COLOR[p.name] ?? 'var(--brand)' }} />
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
            {competitors.length === 0 ? (
              <div style={{ fontSize: 12.5, color: 'var(--fg-4)' }}>Добавьте конкурентов в Настройках и соберите данные</div>
            ) : (
              <div className={styles.compTable}>
                {competitors.map(c => (
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
            )}
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
                    {v.views >= 1000 ? `${(v.views / 1000).toFixed(1)}k` : v.views}
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
