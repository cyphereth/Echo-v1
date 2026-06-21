// ============================================================================
// Echo Radar — UI primitives. Канон: project/ui_kits/app/primitives.jsx.
// Glow-кнопки, платформенные марки, аватары, eyebrows, badges, lane-теги.
// ============================================================================
import { Icon } from './icons';
import { sevTone } from '../utils/format';

// ── Button ──────────────────────────────────────────────────────────────────
// Варианты: primary (cyan + glow) / secondary / ghost / danger (warm ghost).
// Hover: brightness(1.08). Press: scale(0.98). Без bounce — диспетчерская не
// подпрыгивает.
export function Button({ children, variant = 'secondary', icon, size = 'md', onClick, style, ...rest }) {
  const pad = size === 'sm' ? '7px 12px' : size === 'lg' ? '12px 20px' : '10px 16px';
  const fs = size === 'sm' ? 13 : 14;
  const variants = {
    primary:   { background: 'var(--brand)', color: 'var(--fg-on-brand)', border: '1px solid transparent', boxShadow: 'var(--glow-brand)' },
    secondary: { background: 'var(--surface-2)', color: 'var(--fg-1)', border: '1px solid var(--line-strong)' },
    ghost:     { background: 'transparent', color: 'var(--fg-2)', border: '1px solid var(--line-2)' },
    danger:    { background: 'var(--sev-critical-ghost)', color: 'var(--sev-critical-bright)', border: '1px solid var(--sev-critical-line)' },
  };
  return (
    <button onClick={onClick} className="er-btn" {...rest} style={{
      display: 'inline-flex', alignItems: 'center', gap: 8, justifyContent: 'center',
      fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: fs, padding: pad,
      borderRadius: 'var(--r-md)', cursor: 'pointer', whiteSpace: 'nowrap',
      transition: 'filter var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-out)',
      ...variants[variant], ...style,
    }}>
      {icon && <Icon name={icon} size={fs + 2} />}{children}
    </button>
  );
}

// ── PlatformMark ────────────────────────────────────────────────────────────
// Квадратный тайл с фирменным глифом. Цвета — канон дизайн-кита.
const PF = {
  instagram: { glyph: 'instagram', color: '#E1306C', bg: 'rgba(225,48,108,.14)', label: 'Instagram' },
  tiktok:    { glyph: 'tiktok',    color: '#EAF1F8', bg: '#0A1420',              label: 'TikTok' },
  twitter:   { glyph: 'twitter',   color: '#EAF1F8', bg: '#0A1420',              label: 'Twitter' },
  telegram:  { glyph: 'telegram',  color: '#29A9EB', bg: 'rgba(41,169,235,.14)', label: 'Telegram' },
};
export function PlatformMark({ platform, size = 28 }) {
  const p = PF[platform] || PF.instagram;
  return (
    <span style={{
      width: size, height: size, borderRadius: 7, background: p.bg,
      display: 'grid', placeItems: 'center', flex: 'none', border: '1px solid var(--line-2)',
    }}>
      <Icon name={p.glyph} size={size * 0.6} color={p.color} />
    </span>
  );
}
export const PLATFORMS = PF;

// ── Avatar ──────────────────────────────────────────────────────────────────
export function Avatar({ name, size = 36 }) {
  const initial = (name || '?')[0].toUpperCase();
  return (
    <span style={{
      width: size, height: size, borderRadius: '50%', flex: 'none',
      background: 'linear-gradient(135deg,#2a4258,#162536)', border: '1px solid var(--line-2)',
      display: 'grid', placeItems: 'center', color: 'var(--fg-2)', fontFamily: 'var(--font-mono)',
      fontWeight: 600, fontSize: size * 0.4,
    }}>{initial}</span>
  );
}

// ── Eyebrow ─────────────────────────────────────────────────────────────────
// Приборная маркировка: mono, КАПС, разрядка. Инструментальный голос.
export function Eyebrow({ children, color = 'var(--fg-3)', style }) {
  return <span style={{
    fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.16em',
    textTransform: 'uppercase', fontWeight: 600, color, ...style,
  }}>{children}</span>;
}

// ── SeverityBadge ───────────────────────────────────────────────────────────
// Пилюля с точкой + лейблом (ЗАЛЕТАЕТ / РАСТЁТ / ПОД КОНТРОЛЕМ).
export function SeverityBadge({ value }) {
  const t = sevTone(value);
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: 'var(--font-mono)',
      fontSize: 11, letterSpacing: '0.12em', textTransform: 'uppercase', fontWeight: 600,
      color: t.bright, background: t.ghost, border: `1px solid ${t.line}`,
      padding: '4px 9px', borderRadius: 999,
    }}>
      <span style={{ width: 6, height: 6, borderRadius: 999, background: t.color }} />{t.label}
    </span>
  );
}

// ── LaneTag ─────────────────────────────────────────────────────────────────
// Маршрут карточки: PR (срочное, warm) / SMM (cyan) / «решает человек» (нейтрально).
export function LaneTag({ lane }) {
  if (lane === 'PR' || lane === 'pr')
    return <span style={laneSpan('#FF7A87', 'var(--sev-critical-ghost)', 'var(--sev-critical-line)')}>PR · срочно</span>;
  if (lane === 'SMM' || lane === 'smm')
    return <span style={laneSpan('var(--brand-bright)', 'var(--brand-ghost)', 'var(--brand-line)')}>SMM</span>;
  return <span style={laneSpan('var(--fg-3)', 'var(--surface-2)', 'var(--line-2)')}>Решает человек</span>;
}
function laneSpan(color, bg, border) {
  return {
    display: 'inline-flex', alignItems: 'center', fontFamily: 'var(--font-mono)',
    fontSize: 11, letterSpacing: '0.1em', textTransform: 'uppercase', fontWeight: 600,
    color, background: bg, border: `1px solid ${border}`, padding: '4px 9px', borderRadius: 999,
  };
}

// ── ScoreChip ───────────────────────────────────────────────────────────────
// Метрика в детальной карточке: лейбл (eyebrow) + моно-значение.
export function ScoreChip({ label, children, valueColor = 'var(--fg-1)' }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 5, padding: '9px 12px',
      background: 'var(--surface-1)', border: '1px solid var(--line-2)', borderRadius: 'var(--r-md)',
    }}>
      <Eyebrow>{label}</Eyebrow>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 14, fontWeight: 700, color: valueColor, fontVariantNumeric: 'tabular-nums' }}>
        {children}
      </span>
    </div>
  );
}
