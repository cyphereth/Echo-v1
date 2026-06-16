import { useEffect, useState } from 'react';
import * as api from '../../services/api';
import styles from './digests.module.css';

export function DigestsScreen({ brand }) {
  const [items, setItems] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const load = () => {
    if (!brand?.id) return;
    api.getDigests(brand.id).then(setItems).catch(() => setItems([]));
  };
  useEffect(load, [brand?.id]);

  const generate = async () => {
    if (!brand?.id) return;
    setBusy(true); setError(null);
    try {
      await api.createDigest(brand.id);
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
