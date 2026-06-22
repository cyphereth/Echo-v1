// Executive overview «Арена-style» — сводный дашборд для руководителя.
// Hero-метрики (severity/негатив/ответы/аномалии) + таймлайн динамики +
// разбивка по платформам + аномальные сюжеты + топ-негатив. Один экран — вся картина.
// API: GET /analytics?brand_id= (stats/series/platforms/top_negative) + GET /stories?brand_id= (anomalies).
import { useEffect, useState } from 'react';
import {
  ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid,
} from 'recharts';
import { Icon } from '../../../core/components/icons';
import { Eyebrow } from '../../../core/components/ui';
import { sevTone } from '../../../core/utils/format';
import * as api from '../api';
import styles from '../../../components/app/overview.module.css';

// HEX-константы для recharts (SVG, var() не работает)
const C = {
  neg: '#FF4D5E', pos: '#34D8A0', neu: '#7E91A6',
  brand: '#2BB3C7', grid: '#243A50', fg3: '#5C6E83',
};
const tooltipStyle = {
  background: '#1C3349', border: '1px solid #314A64', borderRadius: '10px',
  color: '#EAF1F8', fontSize: '12px',
};

const METRIC_ICON = {
  total:  { icon: 'radio',      bg: 'var(--brand-ghost)',    color: 'var(--brand-bright)' },
  neg:    { icon: 'flame',      bg: 'var(--sev-critical-ghost)', color: 'var(--sev-critical-bright)' },
  sent:   { icon: 'check',      bg: 'var(--sev-calm-ghost)',  color: 'var(--sev-calm)' },
  hot:    { icon: 'activity',   bg: 'var(--sev-rising-ghost)', color: 'var(--sev-rising-bright)' },
};

const PLATFORM_COLOR = { instagram: '#E1306C', tiktok: '#EAF1F8', telegram: '#29A9EB', web: '#2BB3C7' };

function MetricCard({ stat }) {
  const cfg = METRIC_ICON[stat.key] || METRIC_ICON.total;
  const deltaColor = stat.up ? 'var(--sev-calm)' : 'var(--sev-critical-bright)';
  const deltaBg = stat.up ? 'var(--sev-calm-ghost)' : 'var(--sev-critical-ghost)';
  return (
    <div className={styles.metric}>
      <div className={styles.metricHead}>
        <Eyebrow>{stat.label}</Eyebrow>
        <span className={styles.metricIc} style={{ background: cfg.bg }}>
          <Icon name={cfg.icon} size={16} color={cfg.color} />
        </span>
      </div>
      <div className={styles.metricValue}>{stat.value}</div>
      {stat.delta && (
        <span className={styles.metricDelta} style={{ color: deltaColor, background: deltaBg }}>
          <Icon name={stat.up ? 'trendingUp' : 'trendingDown'} size={11} color={deltaColor} />
          {stat.delta}
        </span>
      )}
    </div>
  );
}

export function OverviewScreen({ brand, onOpenStory }) {
  const [data, setData]           = useState(null);
  const [stories, setStories]     = useState([]);
  const [loading, setLoading]     = useState(true);

  useEffect(() => {
    if (!brand?.id) return;
    let alive = true;
    setLoading(true);
    Promise.all([
      api.getAnalytics(brand.id).catch(() => null),
      api.getBrandStories(brand.id).catch(() => []),
    ]).then(([a, s]) => {
      if (!alive) return;
      setData(a);
      setStories(Array.isArray(s) ? s : []);
    }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [brand?.id]);

  if (loading) {
    return <div className={styles.wrap}><div className={styles.inner}><div className={styles.empty}>Загружаю обзор…</div></div></div>;
  }
  if (!data || !data.has_data) {
    return (
      <div className={styles.wrap}><div className={styles.inner}>
        <div className={styles.card}><div className={styles.empty}>
          Данных пока нет. Нажмите «Собрать данные» — радар начнёт ловить упоминания.
        </div></div>
      </div></div>
    );
  }

  const chartData = data.series.days.map((d, i) => ({
    t: d,
    neg: data.series.neg[i],
    pos: data.series.pos[i],
    neu: data.series.neu[i],
  }));
  const anomalies = stories.filter(s => s.is_anomaly).slice(0, 5);

  return (
    <div className={styles.wrap}>
      <div className={styles.inner}>
        {/* header */}
        <div className={styles.head}>
          <div>
            <h1 className={styles.headTitle}>{brand?.name || 'Обзор'}</h1>
            <div className={styles.headSub}>Сводная картина за последние 7 дней</div>
          </div>
          <span className={styles.liveBadge}>
            <span className={styles.liveDot} />В эфире
          </span>
        </div>

        {/* hero metrics */}
        <div className={styles.metrics}>
          {data.stats.map(s => <MetricCard key={s.key} stat={s} />)}
        </div>

        {/* timeline + platform rail */}
        <div className={styles.grid}>
          <div className={styles.card}>
            <div className={styles.cardHead}>
              <span className={styles.cardTitle}>
                <Icon name="activity" size={16} color="var(--brand-bright)" />
                Динамика упоминаний
              </span>
            </div>
            <div className={styles.cardBody}>
              <ResponsiveContainer width="100%" height={240}>
                <AreaChart data={chartData} margin={{ top: 6, right: 8, left: -18, bottom: 0 }}>
                  <defs>
                    <linearGradient id="g-neg" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={C.neg} stopOpacity={0.4} />
                      <stop offset="100%" stopColor={C.neg} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke={C.grid} vertical={false} />
                  <XAxis dataKey="t" stroke={C.fg3} tick={{ fontSize: 11, fontFamily: 'var(--font-mono)' }} tickLine={false} axisLine={{ stroke: C.grid }} />
                  <YAxis stroke={C.fg3} tick={{ fontSize: 11, fontFamily: 'var(--font-mono)' }} tickLine={false} axisLine={{ stroke: C.grid }} allowDecimals={false} />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Area type="monotone" dataKey="neg" name="Негатив" stroke={C.neg} strokeWidth={2} fill="url(#g-neg)" />
                  <Area type="monotone" dataKey="neu" name="Нейтрально" stroke={C.neu} strokeWidth={1.5} fillOpacity={0} />
                  <Area type="monotone" dataKey="pos" name="Позитив" stroke={C.pos} strokeWidth={1.5} fillOpacity={0} />
                </AreaChart>
              </ResponsiveContainer>
              <div className={styles.legend}>
                <span className={styles.legendItem}><span className={styles.legendDot} style={{ background: C.neg }} />Негатив</span>
                <span className={styles.legendItem}><span className={styles.legendDot} style={{ background: C.neu }} />Нейтрально</span>
                <span className={styles.legendItem}><span className={styles.legendDot} style={{ background: C.pos }} />Позитив</span>
              </div>
            </div>
          </div>

          <div className={styles.card}>
            <div className={styles.cardHead}>
              <span className={styles.cardTitle}>
                <Icon name="pieChart" size={16} color="var(--brand-bright)" />
                Источники
              </span>
            </div>
            <div className={styles.cardBody}>
              {data.platforms.length === 0 ? (
                <div style={{ fontSize: 13, color: 'var(--fg-3)' }}>Нет данных по платформам.</div>
              ) : data.platforms.map(p => (
                <div key={p.key} className={styles.barRow}>
                  <span className={styles.barLabel}>
                    <Icon name={p.key} size={13} color={PLATFORM_COLOR[p.key] || 'var(--fg-3)'} />
                    {p.name}
                  </span>
                  <span className={styles.barTrack}>
                    <span className={styles.barFill} style={{ width: `${p.pct}%`, background: PLATFORM_COLOR[p.key] || C.brand }} />
                  </span>
                  <span className={styles.barPct}>{p.pct}%</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* anomalies + top negative */}
        <div className={styles.grid}>
          <div className={styles.card}>
            <div className={styles.cardHead}>
              <span className={styles.cardTitle}>
                <Icon name="flame" size={16} color="var(--sev-critical-bright)" />
                Аномальные сюжеты
                {anomalies.length > 0 && (
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 700, color: 'var(--sev-critical-bright)', background: 'var(--sev-critical-ghost)', padding: '2px 8px', borderRadius: 'var(--r-pill)' }}>
                    {anomalies.length}
                  </span>
                )}
              </span>
            </div>
            {anomalies.length === 0 ? (
              <div className={styles.empty}>Аномалий нет. Спокойно.</div>
            ) : anomalies.map(s => (
              <div key={s.id} className={styles.storyItem} onClick={() => onOpenStory?.(s.id)}>
                <span className={styles.storyWarn} />
                <span className={styles.storyText}>{s.title}</span>
                <span className={styles.storyMeta}>{s.post_count} упом.</span>
              </div>
            ))}
          </div>

          <div className={styles.card}>
            <div className={styles.cardHead}>
              <span className={styles.cardTitle}>
                <Icon name="trendingDown" size={16} color="var(--sev-critical-bright)" />
                Топ-негатив
              </span>
            </div>
            {(!data.top_negative || data.top_negative.length === 0) ? (
              <div className={styles.empty}>Негативных упоминаний нет.</div>
            ) : data.top_negative.map(m => {
              const tone = sevTone(m.severity);
              return (
                <div key={m.id} className={styles.negItem}>
                  <span className={styles.negSev} style={{ color: tone.bright }}>{m.severity}</span>
                  <span className={styles.negText}>{m.title}</span>
                  <Icon name={m.platform} size={14} color={PLATFORM_COLOR[m.platform] || 'var(--fg-3)'} />
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
