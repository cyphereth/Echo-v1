import { useEffect, useState } from 'react';
import * as api from '../api';
import styles from '../../../components/app/digests.module.css';

export function BrandDigestsScreen({ brandId }) {
  const [items, setItems] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const load = () => {
    if (!brandId) { setItems([]); return; }
    api.getBrandDigests(brandId).then(setItems).catch(() => setItems([]));
  };
  useEffect(load, [brandId]);

  const generate = async () => {
    if (!brandId) return;
    setBusy(true); setError(null);
    try {
      await api.createBrandDigest(brandId);
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
