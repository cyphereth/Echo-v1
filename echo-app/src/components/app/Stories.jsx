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

function StoryDetail({ id }) {
  const [data, setData] = useState(null);
  useEffect(() => { api.getStory(id).then(setData).catch(() => setData(null)); }, [id]);
  if (!data) return <div className={styles.empty}>Загрузка…</div>;
  const chart = data.points.map((p) => ({
    t: fmtHour(p.bucket_start),
    mentions: p.mention_count,
    sentiment: p.avg_sentiment,
  }));
  return (
    <div className={styles.detail}>
      <h2>{data.title}</h2>
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
            <div className={styles.sub}>{s.post_count} · {(s.avg_sentiment ?? 0).toFixed(2)}</div>
          </button>
        ))}
      </div>
      <div className={styles.pane}>
        {selected ? <StoryDetail id={selected} /> : <div className={styles.empty}>Выберите сюжет</div>}
      </div>
    </div>
  );
}
