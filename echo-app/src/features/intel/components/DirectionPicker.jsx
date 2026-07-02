// Пикер области — drawer с поиском по направлениям, как ColumnPicker в Ленте v2.
// Single-select: клик выбирает направление, повторный — сбрасывает ("Все").
import { useEffect, useMemo, useRef, useState } from 'react';
import { DIRECTION_NAMES } from '../api';
import styles from '../intel.module.css';

// Группировка направлений
const RF_BORDER = ['bryansk', 'belgorod', 'kursk', 'voronezh', 'oryel', 'rostov',
  'crimea', 'krasnodar', 'smolensk', 'pskov', 'moscow'];
const SEPARATIST = ['dnr', 'lnr'];
const UKRAINE = ['kyiv', 'kharkiv', 'kherson', 'zaporizhzhia', 'dnipropetrovsk',
  'odesa', 'mykolaiv', 'vinnytsia', 'zhytomyr', 'chernihiv', 'sumy',
  'poltava', 'cherkasy', 'kirovohrad', 'ternopil', 'khmelnytskyi',
  'ivano-frankivsk', 'lviv', 'rivne', 'volyn', 'zakarpattia', 'chernivtsi'];

const GROUPS = [
  { label: 'РФ приграничные', keys: RF_BORDER },
  { label: 'ДНР / ЛНР', keys: SEPARATIST },
  { label: 'Украина', keys: UKRAINE },
];

// Все остальные ключи (если появились новые, не вошедшие в группы)
const EXTRA = Object.keys(DIRECTION_NAMES).filter(
  k => k !== 'unassigned' && !RF_BORDER.includes(k) && !SEPARATIST.includes(k) && !UKRAINE.includes(k)
);
if (EXTRA.length) GROUPS.push({ label: 'Прочее', keys: EXTRA });

export function DirectionPicker({ value, onChange }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const searchRef = useRef(null);

  // Esc закрывает, фокус в поиск при открытии
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('keydown', onKey);
    const t = setTimeout(() => searchRef.current?.focus(), 50);
    return () => { document.removeEventListener('keydown', onKey); clearTimeout(t); };
  }, [open]);

  const ql = q.toLowerCase();

  const filtered = useMemo(() => {
    if (!ql) return GROUPS;
    // Фильтруем группы — оставляем только те ключи, что совпадают
    return GROUPS.map(g => ({
      ...g,
      keys: g.keys.filter(k =>
        k.toLowerCase().includes(ql) || (DIRECTION_NAMES[k] || '').toLowerCase().includes(ql)
      ),
    })).filter(g => g.keys.length > 0);
  }, [ql]);

  function pick(key) {
    if (value === key) {
      // Снимаем выделение → все области
      onChange('');
    } else {
      onChange(key);
    }
    setOpen(false);
  }

  const label = value ? (DIRECTION_NAMES[value] || value) : 'Все области';

  return (
    <>
      <button
        className={`${styles.dirPickerBtn} ${value ? styles.dirPickerBtnActive : ''}`}
        onClick={() => setOpen(true)}
      >
        📍 {label}
      </button>
      {open && (
        <div className={styles.colDrawerBackdrop} onClick={() => setOpen(false)}>
          <aside className={styles.colDrawer} onClick={e => e.stopPropagation()}>
            <div className={styles.colDrawerHead}>
              <span className={styles.colDrawerTitle}>ОБЛАСТИ</span>
              <button className={styles.colDrawerClose} onClick={() => setOpen(false)}>✕</button>
            </div>
            <input
              className={styles.colPickerSearch}
              ref={searchRef}
              value={q}
              onChange={e => setQ(e.target.value)}
              placeholder="поиск области…"
            />
            <div className={styles.colDrawerBody}>
              {/* "Все области" чип */}
              <div className={styles.colDrawerGroup}>
                <div className={styles.colDrawerChips}>
                  <button
                    className={`${styles.colDrawerChip} ${!value ? styles.colDrawerChipOn : ''}`}
                    onClick={() => pick('')}
                  >
                    {!value ? '✓ ' : '  '}Все области
                  </button>
                </div>
              </div>
              {filtered.map(g => (
                <div key={g.label} className={styles.colDrawerGroup}>
                  <div className={styles.colDrawerGroupName}>{g.label}</div>
                  <div className={styles.colDrawerChips}>
                    {g.keys.map(k => {
                      const on = value === k;
                      return (
                        <button
                          key={k}
                          className={`${styles.colDrawerChip} ${on ? styles.colDrawerChipOn : ''}`}
                          onClick={() => pick(k)}
                        >
                          {on ? '✓ ' : '  '}{DIRECTION_NAMES[k] || k}
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
