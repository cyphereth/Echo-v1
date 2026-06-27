// Выбор временного диапазона — пресеты или произвольный from/to.
// Возвращает { window } или { from_dt, to_dt } в зависимости от режима.
import { useState, useRef, useEffect } from 'react';
import styles from '../intel.module.css';

const PRESETS = [
  { label: '1ч',  window: '1h' },
  { label: '24ч', window: '24h' },
  { label: '7д',  window: '7d' },
  { label: '30д', window: '30d' },
];

// ISO datetime string → local datetime-local input value
function toInputVal(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// datetime-local input value → ISO UTC string
function fromInputVal(val) {
  if (!val) return null;
  return new Date(val).toISOString();
}

export function DateRangePicker({ value, onChange }) {
  // value: { window: '24h' } or { from_dt: iso, to_dt: iso }
  const isCustom = !!(value && (value.from_dt || value.to_dt));
  const [open, setOpen] = useState(false);
  const [fromVal, setFromVal] = useState(() => toInputVal(value?.from_dt));
  const [toVal, setToVal]     = useState(() => toInputVal(value?.to_dt));
  const ref = useRef(null);

  // Sync input fields when value is reset externally
  useEffect(() => {
    setFromVal(toInputVal(value?.from_dt));
    setToVal(toInputVal(value?.to_dt));
  }, [value?.from_dt, value?.to_dt]);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = e => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  function applyCustom() {
    const from_dt = fromInputVal(fromVal);
    const to_dt   = fromInputVal(toVal);
    if (!from_dt && !to_dt) return;
    onChange({ from_dt, to_dt });
    setOpen(false);
  }

  const activeWindow = !isCustom ? (value?.window || '24h') : null;

  return (
    <div ref={ref} style={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 0 }}>
      {/* Preset buttons */}
      <div className={styles.windowSel}>
        {PRESETS.map(p => (
          <button
            key={p.window}
            className={styles.windowBtn}
            data-active={activeWindow === p.window ? '1' : '0'}
            onClick={() => { onChange({ window: p.window }); setOpen(false); }}
          >
            {p.label}
          </button>
        ))}
        {/* Custom range toggle */}
        <button
          className={styles.windowBtn}
          data-active={isCustom ? '1' : '0'}
          onClick={() => setOpen(o => !o)}
          title="Произвольный диапазон"
        >
          {isCustom
            ? [value.from_dt, value.to_dt]
                .map(dt => dt ? toInputVal(dt).slice(5, 16).replace('T', ' ') : '…')
                .join(' → ')
            : '⋯'}
        </button>
      </div>

      {/* Dropdown */}
      {open && (
        <div style={{
          position: 'absolute', top: 'calc(100% + 6px)', right: 0, zIndex: 200,
          background: '#0D1520', border: '1px solid rgba(43,179,199,.20)',
          borderRadius: 8, padding: '14px 16px', minWidth: 280,
          boxShadow: '0 8px 32px rgba(0,0,0,.5)',
          fontFamily: 'var(--font-mono)', fontSize: 11, color: '#97A9BE',
        }}>
          <div style={{ marginBottom: 10, color: '#57D2E2', fontWeight: 700, letterSpacing: '0.06em' }}>
            ПЕРИОД
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span>От</span>
              <input
                type="datetime-local"
                value={fromVal}
                onChange={e => setFromVal(e.target.value)}
                style={inputStyle}
              />
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span>До</span>
              <input
                type="datetime-local"
                value={toVal}
                onChange={e => setToVal(e.target.value)}
                style={inputStyle}
              />
            </label>
          </div>
          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            <button
              onClick={applyCustom}
              style={{ ...btnStyle, background: 'rgba(43,179,199,.15)', color: '#57D2E2', flex: 1 }}
            >
              Применить
            </button>
            <button
              onClick={() => { onChange({ window: '24h' }); setOpen(false); setFromVal(''); setToVal(''); }}
              style={{ ...btnStyle, color: '#6A8499' }}
            >
              Сброс
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

const inputStyle = {
  background: 'rgba(255,255,255,.04)',
  border: '1px solid rgba(255,255,255,.10)',
  borderRadius: 4,
  color: '#D8E4F0',
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  padding: '5px 8px',
  outline: 'none',
  colorScheme: 'dark',
};

const btnStyle = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  fontWeight: 600,
  padding: '6px 12px',
  background: 'rgba(255,255,255,.04)',
  border: '1px solid rgba(255,255,255,.08)',
  borderRadius: 5,
  cursor: 'pointer',
  color: '#97A9BE',
};
