// News-specialized Digests screen — always topic-scoped.
// Wired to: GET /topics/{id}/digests, POST /topics/{id}/digest via features/news/api.js
import { useEffect, useState } from 'react';
import * as api from '../api';
import styles from '../../../components/app/digests.module.css';

// Accepts topicId directly — no scope object.
export function NewsDigestsScreen({ topicId }) {
  const [items, setItems] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const load = () => {
    if (!topicId) { setItems([]); return; }
    api.getTopicDigests(topicId).then(setItems).catch(() => setItems([]));
  };
  useEffect(load, [topicId]);

  const generate = async () => {
    if (!topicId) return;
    setBusy(true); setError(null);
    try {
      await api.generateTopicDigest(topicId);
      load();
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.wrap}>
      <div className={styles.bar}>
        <button className={styles.btn} onClick={generate} disabled={busy}>
          {busy ? 'Генерация…' : 'Сгенерировать дайджест'}
        </button>
        {error && <span className={styles.err}>{error}</span>}
      </div>
      {items.length === 0 && <div className={styles.empty}>Пока нет дайджестов</div>}
      <ul className={styles.list}>
        {items.map((r) => (
          <li key={r.id} className={styles.item}>
            <div className={styles.meta}>{new Date(r.created_at).toLocaleString()}</div>
            <div className={styles.body}>{r.body}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}
