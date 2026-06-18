import { useEffect, useState } from 'react';
import {
  ResponsiveContainer, ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, CartesianGrid,
} from 'recharts';
import * as api from '../../services/api';
import styles from './stories.module.css';

function fmtHour(iso) {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:00`;
}

const badge = (bg, color) => ({
  display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 8px',
  borderRadius: 999, fontSize: 11, fontWeight: 700, background: bg, color,
  fontFamily: 'var(--font-sans)', whiteSpace: 'nowrap',
});

function VerifiedBadge({ story, compact }) {
  const n = story.source_count ?? 0;
  if (story.verified) {
    return <span style={badge('rgba(34,197,94,0.15)', '#16a34a')} title="Подтверждено независимыми источниками">
      ✓ {n} {compact ? '' : 'источник(ов)'}</span>;
  }
  return <span style={badge('var(--surface-3)', 'var(--fg-3)')} title="Недостаточно независимых источников">
    ± {n}</span>;
}

function CredibilityBadge({ story }) {
  if (story.credibility === 'suspect') {
    return <span style={badge('rgba(239,68,68,0.15)', '#ef4444')} title={story.credibility_note || ''}>⚠ требует проверки</span>;
  }
  if (story.credibility === 'credible') {
    return <span style={badge('rgba(34,197,94,0.15)', '#16a34a')} title={story.credibility_note || ''}>✓ проверено</span>;
  }
  return null;
}

function StoryDetail({ id }) {
  const [data, setData] = useState(null);
  const [assessing, setAssessing] = useState(false);
  useEffect(() => { api.getStory(id).then(setData).catch(() => setData(null)); }, [id]);
  if (!data) return <div className={styles.empty}>Загрузка…</div>;
  const chart = data.points.map((p) => ({
    t: fmtHour(p.bucket_start),
    mentions: p.mention_count,
    sentiment: p.avg_sentiment,
  }));
  const assess = async () => {
    setAssessing(true);
    try {
      const upd = await api.assessStory(id);
      setData((d) => ({ ...d, credibility: upd.credibility, credibility_note: upd.credibility_note }));
    } catch { /* 503 when LLM off — leave as-is */ }
    finally { setAssessing(false); }
  };
  return (
    <div className={styles.detail}>
      <h2>{data.title}</h2>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '4px 0 10px' }}>
        <VerifiedBadge story={data} />
        <CredibilityBadge story={data} />
        <button
          onClick={assess}
          disabled={assessing}
          style={{ ...badge('var(--brand)', '#fff'), border: 'none', cursor: assessing ? 'default' : 'pointer' }}
        >
          {assessing ? 'Анализ…' : '🔎 Оценить достоверность'}
        </button>
      </div>
      {data.credibility_note && (
        <div style={{ fontSize: 12, color: 'var(--fg-2)', marginBottom: 10 }}>{data.credibility_note}</div>
      )}
      <div className={styles.meta}>
        {data.post_count} упоминаний · тональность {(data.avg_sentiment ?? 0).toFixed(2)}
        {data.is_anomaly && <span className={styles.anomaly}> ⚠ аномалия</span>}
      </div>
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={chart}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="t" />
          <YAxis yAxisId="l" />
          <YAxis yAxisId="r" orientation="right" domain={[-1, 1]} />
          <Tooltip />
          <Bar yAxisId="l" dataKey="mentions" name="Упоминания" fill="#6366f1" />
          <Line yAxisId="r" dataKey="sentiment" name="Тональность" stroke="#ef4444" dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
      <h3>Инциденты</h3>
      <ul className={styles.incidents}>
        {data.incidents.map((i) => (
          <li key={i.id}>{i.title} <span>· {i.post_count}</span></li>
        ))}
      </ul>
    </div>
  );
}

export function StoriesScreen({ scope }) {
  const [stories, setStories] = useState([]);
  const [selected, setSelected] = useState(null);
  useEffect(() => {
    if (!scope?.id) { setStories([]); setSelected(null); return; }
    api.getStoriesScoped(scope).then((rows) => {
      setStories(rows);
      setSelected(rows[0]?.id ?? null);
    }).catch(() => setStories([]));
  }, [scope?.kind, scope?.id]);

  return (
    <div className={styles.wrap}>
      <div className={styles.list}>
        {stories.length === 0 && <div className={styles.empty}>Пока нет сюжетов</div>}
        {stories.map((s) => (
          <button
            key={s.id}
            className={s.id === selected ? styles.activeItem : styles.item}
            onClick={() => setSelected(s.id)}
          >
            <div className={styles.title}>
              {s.is_anomaly && <span className={styles.warn} title="Аномалия">⚠ </span>}
              {s.title}
            </div>
            <div className={styles.sub} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span>{s.post_count} · {(s.avg_sentiment ?? 0).toFixed(2)}</span>
              <VerifiedBadge story={s} compact />
              {s.credibility === 'suspect' && <span title={s.credibility_note || ''}>⚠</span>}
            </div>
          </button>
        ))}
      </div>
      <div className={styles.pane}>
        {selected ? <StoryDetail id={selected} /> : <div className={styles.empty}>Выберите сюжет</div>}
      </div>
    </div>
  );
}
