// News-specialized Stories screen — uses features/news/api.js (no scope, explicit topicId).
// getNewsStories → GET /news/stories?topic_id=
// getStory       → GET /news/stories/{id}
// assessStory    → POST /news/stories/{id}/assess
// summarizeStory → POST /news/stories/{id}/summarize
import { useEffect, useState } from 'react';
import * as api from '../api';
import styles from '../../../components/app/stories.module.css';
import { badgeStyle, VerifiedBadge, CredibilityBadge } from '../../../core/components/Badge';
import { TimelineChart } from '../../../core/components/TimelineChart';

function fmtHour(iso) {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:00`;
}

function fmtTime(iso) {
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function StoryDetail({ id }) {
  const [data, setData] = useState(null);
  const [assessing, setAssessing] = useState(false);
  const [summarizing, setSummarizing] = useState(false);
  useEffect(() => { api.getStory(id).then(setData).catch(() => setData(null)); }, [id]);
  if (!data) return <div className={styles.empty}>Загрузка…</div>;
  // News view: volume bars (spike) + source-count growth (corroboration). No sentiment.
  const chart = data.points.map((p) => ({
    t: fmtHour(p.bucket_start),
    mentions: p.mention_count,
    sources: p.source_count,
  }));
  const sources = data.sources || [];
  const assess = async () => {
    setAssessing(true);
    try {
      const upd = await api.assessStory(id);
      setData((d) => ({ ...d, credibility: upd.credibility, credibility_note: upd.credibility_note }));
    } catch { /* 503 when LLM off — leave as-is */ }
    finally { setAssessing(false); }
  };
  const summarize = async () => {
    setSummarizing(true);
    try {
      const upd = await api.summarizeStory(id);
      setData((d) => ({ ...d, summary: upd.summary }));
    } catch { /* 503 when LLM off */ }
    finally { setSummarizing(false); }
  };
  return (
    <div className={styles.detail}>
      <h2>{data.title}</h2>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', margin: '4px 0 10px' }}>
        <VerifiedBadge story={data} />
        <CredibilityBadge story={data} />
        {data.is_anomaly && <span style={badgeStyle('rgba(245,158,11,0.15)', '#f59e0b')}>⚡ всплеск</span>}
        <button onClick={summarize} disabled={summarizing}
          style={{ ...badgeStyle('var(--surface-3)', 'var(--fg-2)'), border: 'none', cursor: summarizing ? 'default' : 'pointer' }}>
          {summarizing ? '…' : '📝 Что произошло'}
        </button>
        <button onClick={assess} disabled={assessing}
          style={{ ...badgeStyle('var(--brand)', '#fff'), border: 'none', cursor: assessing ? 'default' : 'pointer' }}>
          {assessing ? 'Анализ…' : '🔎 Оценить достоверность'}
        </button>
      </div>

      {data.summary && (
        <div style={{ fontSize: 14, color: 'var(--fg-1)', background: 'var(--surface-2)',
                      padding: '10px 12px', borderRadius: 'var(--r-md)', marginBottom: 10 }}>
          {data.summary}
        </div>
      )}
      {data.credibility_note && (
        <div style={{ fontSize: 12, color: 'var(--fg-2)', marginBottom: 10 }}>⚠ {data.credibility_note}</div>
      )}

      <div className={styles.meta}>{data.post_count} сообщений · {data.source_count} источников</div>

      <TimelineChart data={chart} />

      <h3>Источники ({sources.length})</h3>
      <ul className={styles.incidents}>
        {sources.length === 0 && <li style={{ color: 'var(--fg-3)' }}>—</li>}
        {sources.map((src, i) => (
          <li key={src.author}>
            {i === 0 && <span title="Сообщил первым" style={{ color: '#16a34a', fontWeight: 700 }}>⚑ </span>}
            <span style={{ fontFamily: 'var(--font-mono)' }}>{src.author}</span>
            <span> · {fmtTime(src.first_seen)} · {src.count}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// Accepts topicId directly — no scope object.
export function NewsStoriesScreen({ topicId }) {
  const [stories, setStories] = useState([]);
  const [selected, setSelected] = useState(null);
  useEffect(() => {
    if (!topicId) { setStories([]); setSelected(null); return; }
    api.getNewsStories(topicId).then((rows) => {
      setStories(rows);
      setSelected(rows[0]?.id ?? null);
    }).catch(() => setStories([]));
  }, [topicId]);

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
              <span>{s.post_count} сообщений</span>
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
