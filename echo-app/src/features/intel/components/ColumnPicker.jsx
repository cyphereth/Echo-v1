// "+ колонки ▾" dropdown: search + checkbox list of all directions.
import { useEffect, useRef, useState } from 'react';
import { intelApi } from '../api';
import styles from '../intel.module.css';

export function ColumnPicker({ activeKeys, onAdd, onRemove }) {
  const [open, setOpen]     = useState(false);
  const [all, setAll]       = useState([]);
  const [q, setQ]           = useState('');
  const ref = useRef(null);

  useEffect(() => { intelApi.directions().then(setAll).catch(() => {}); }, []);
  useEffect(() => {
    function onDoc(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false); }
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  const filtered = all.filter(d => (d.name || d.key).toLowerCase().includes(q.toLowerCase()));

  return (
    <div className={styles.colPickerWrap} ref={ref}>
      <button className={styles.colPickerBtn} onClick={() => setOpen(o => !o)}>+ колонки ▾</button>
      {open && (
        <div className={styles.colPicker}>
          <input className={styles.colPickerSearch} value={q}
                 onChange={e => setQ(e.target.value)} placeholder="поиск…" autoFocus />
          <div className={styles.colPickerList}>
            {filtered.map(d => {
              const on = activeKeys.includes(d.key);
              return (
                <label key={d.key} className={styles.colPickerItem}>
                  <input type="checkbox" checked={on}
                         onChange={() => on ? onRemove(d.key) : onAdd(d)} />
                  <span>{d.name} <span className={styles.colPickerKind}>{d.kind}</span></span>
                </label>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
