// «+ колонки» — выезжающая справа панель-drawer со списком всех направлений.
// Раньше был absolute-дропдаун внутри .feedColumnBar (overflow-x:auto его обрезал —
// список не было видно). Теперь это полноразмерный drawer с backdrop: больше места,
// поиск + чипы направлений (активные подсвечены ✓), группировка по типу.
import { useEffect, useMemo, useRef, useState } from 'react';
import { intelApi } from '../api';
import styles from '../intel.module.css';

const KIND_LABEL = { geo: 'География', source: 'Источники', topic: 'Темы', manual: 'Прочее' };

export function ColumnPicker({ activeKeys, onAdd, onRemove }) {
  const [open, setOpen] = useState(false);
  const [all, setAll]   = useState([]);
  const [q, setQ]       = useState('');
  const searchRef = useRef(null);

  useEffect(() => { intelApi.directions().then(setAll).catch(() => {}); }, []);

  // Esc закрывает, фокус в поиск при открытии.
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('keydown', onKey);
    const t = setTimeout(() => searchRef.current?.focus(), 50);
    return () => { document.removeEventListener('keydown', onKey); clearTimeout(t); };
  }, [open]);

  const filtered = useMemo(
    () => all.filter(d => (d.name || d.key).toLowerCase().includes(q.toLowerCase())),
    [all, q]);

  // Группируем по kind, чтобы было что выбирать — а не сплошной список.
  const groups = useMemo(() => {
    const m = new Map();
    for (const d of filtered) {
      const k = d.kind || 'manual';
      if (!m.has(k)) m.set(k, []);
      m.get(k).push(d);
    }
    return [...m.entries()];
  }, [filtered]);

  return (
    <>
      <button className={styles.colPickerBtn} onClick={() => setOpen(true)}>+ колонки</button>
      {open && (
        <div className={styles.colDrawerBackdrop} onClick={() => setOpen(false)}>
          <aside className={styles.colDrawer} onClick={e => e.stopPropagation()}>
            <div className={styles.colDrawerHead}>
              <span className={styles.colDrawerTitle}>КОЛОНКИ · {activeKeys.length}</span>
              <button className={styles.colDrawerClose} onClick={() => setOpen(false)}>✕</button>
            </div>
            <input className={styles.colPickerSearch} ref={searchRef} value={q}
                   onChange={e => setQ(e.target.value)} placeholder="поиск направления…" />
            <div className={styles.colDrawerBody}>
              {groups.length === 0 && <div className={styles.feedColumnEmpty}>ничего не найдено</div>}
              {groups.map(([kind, items]) => (
                <div key={kind} className={styles.colDrawerGroup}>
                  <div className={styles.colDrawerGroupName}>{KIND_LABEL[kind] || kind}</div>
                  <div className={styles.colDrawerChips}>
                    {items.map(d => {
                      const on = activeKeys.includes(d.key);
                      return (
                        <button key={d.key}
                                className={on ? `${styles.colDrawerChip} ${styles.colDrawerChipOn}` : styles.colDrawerChip}
                                onClick={() => on ? onRemove(d.key) : onAdd(d)}>
                          {on ? '✓ ' : '+ '}{d.name}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </aside>
        </div>
      )}
    </>
  );
}
