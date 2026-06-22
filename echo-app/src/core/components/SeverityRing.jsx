// ============================================================================
// SeverityRing — кольцевой gauge виральности. Трек + цветная дуга прогресса.
// Безошибочно читается как прибор. Канон: project/ui_kits/app/primitives.jsx.
// ============================================================================
import { sevTone } from '../utils/format';

export function SeverityRing({ value, size = 76, stroke = 8, tone }) {
  const t = tone || sevTone(value);
  const v = Math.max(0, Math.min(100, Number(value) || 0));
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const off = c * (1 - v / 100);
  return (
    <span style={{
      position: 'relative', width: size, height: size, flex: 'none',
      display: 'inline-grid', placeItems: 'center',
    }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-3)" strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={t.color} strokeWidth={stroke}
          strokeLinecap="round" strokeDasharray={c} strokeDashoffset={off}
          style={{ transition: 'stroke-dashoffset .6s var(--ease-out)' }} />
      </svg>
      <span style={{
        position: 'absolute', fontFamily: 'var(--font-mono)', fontWeight: 700,
        fontSize: size * 0.32, color: t.bright, fontVariantNumeric: 'tabular-nums',
      }}>{Math.round(v)}</span>
    </span>
  );
}
