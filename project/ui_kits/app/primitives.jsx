// ============================================================================
// Echo Radar — App UI kit · primitives
// ============================================================================

function Button({ children, variant = 'secondary', icon, size = 'md', onClick, style }) {
  const pad = size === 'sm' ? '7px 12px' : size === 'lg' ? '12px 20px' : '10px 16px';
  const fs = size === 'sm' ? 13 : 14;
  const variants = {
    primary:   { background: 'var(--brand)', color: 'var(--fg-on-brand)', border: '1px solid transparent', boxShadow: 'var(--glow-brand)' },
    secondary: { background: 'var(--surface-2)', color: 'var(--fg-1)', border: '1px solid var(--line-strong)' },
    ghost:     { background: 'transparent', color: 'var(--fg-2)', border: '1px solid var(--line-2)' },
    danger:    { background: 'var(--sev-critical-ghost)', color: 'var(--sev-critical-bright)', border: '1px solid var(--sev-critical-line)' },
  };
  return (
    <button onClick={onClick} className="er-btn" style={{
      display: 'inline-flex', alignItems: 'center', gap: 8, justifyContent: 'center',
      fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: fs, padding: pad,
      borderRadius: 'var(--r-md)', cursor: 'pointer', whiteSpace: 'nowrap', ...variants[variant], ...style,
    }}>
      {icon && <Icon name={icon} size={fs + 2} />}{children}
    </button>
  );
}

const PF = {
  instagram: { glyph: 'instagram', color: '#E1306C', bg: 'rgba(225,48,108,.14)', label: 'Instagram' },
  tiktok:    { glyph: 'tiktok',    color: '#EAF1F8', bg: '#0A1420',              label: 'TikTok' },
  twitter:   { glyph: 'twitter',   color: '#EAF1F8', bg: '#0A1420',              label: 'Twitter' },
  telegram:  { glyph: 'telegram',  color: '#29A9EB', bg: 'rgba(41,169,235,.14)', label: 'Telegram' },
};
function PlatformMark({ platform, size = 28 }) {
  const p = PF[platform] || PF.instagram;
  return (
    <span style={{ width: size, height: size, borderRadius: 7, background: p.bg, display: 'grid', placeItems: 'center', flex: 'none', border: '1px solid var(--line-2)' }}>
      <Icon name={p.glyph} size={size * 0.6} color={p.color} />
    </span>
  );
}

function Avatar({ name, size = 36 }) {
  const initial = (name || '?')[0].toUpperCase();
  return (
    <span style={{ width: size, height: size, borderRadius: '50%', flex: 'none',
      background: 'linear-gradient(135deg,#2a4258,#162536)', border: '1px solid var(--line-2)',
      display: 'grid', placeItems: 'center', color: 'var(--fg-2)', fontFamily: 'var(--font-mono)',
      fontWeight: 600, fontSize: size * 0.4 }}>{initial}</span>
  );
}

// Ring gauge — full track + colored progress arc (unmistakably a meter)
function SeverityRing({ value, size = 76, stroke = 8, tone }) {
  const t = tone || sevTone(value);
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const off = c * (1 - value / 100);
  return (
    <span style={{ position: 'relative', width: size, height: size, flex: 'none', display: 'inline-grid', placeItems: 'center' }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="var(--surface-3)" strokeWidth={stroke} />
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={t.color} strokeWidth={stroke}
          strokeLinecap="round" strokeDasharray={c} strokeDashoffset={off}
          style={{ transition: 'stroke-dashoffset .6s var(--ease-out)' }} />
      </svg>
      <span style={{ position: 'absolute', fontFamily: 'var(--font-mono)', fontWeight: 700,
        fontSize: size * 0.32, color: t.bright, fontVariantNumeric: 'tabular-nums' }}>{value}</span>
    </span>
  );
}

// Sparkline of the snapshot series, tinted by phase
function Sparkline({ data, color = '#FFB23E', w = 96, h = 30 }) {
  const max = Math.max(...data), min = Math.min(...data);
  const span = max - min || 1;
  const pts = data.map((v, i) => [ (i / (data.length - 1)) * w, h - 3 - ((v - min) / span) * (h - 6) ]);
  const line = pts.map(p => p.join(',')).join(' ');
  const area = `0,${h} ${line} ${w},${h}`;
  const gid = 'spk' + Math.round(color.charCodeAt(1) * 99 + w);
  return (
    <svg width={w} height={h} style={{ display: 'block' }}>
      <defs><linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor={color} stopOpacity="0.28" /><stop offset="1" stopColor={color} stopOpacity="0" />
      </linearGradient></defs>
      <polygon points={area} fill={`url(#${gid})`} />
      <polyline points={line} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={pts[pts.length-1][0]} cy={pts[pts.length-1][1]} r="2.6" fill={color} />
    </svg>
  );
}

function Eyebrow({ children, color = 'var(--fg-3)', style }) {
  return <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.16em',
    textTransform: 'uppercase', fontWeight: 600, color, ...style }}>{children}</span>;
}

function SeverityBadge({ value }) {
  const t = sevTone(value);
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontFamily: 'var(--font-mono)',
      fontSize: 11, letterSpacing: '0.12em', textTransform: 'uppercase', fontWeight: 600, color: t.bright,
      background: t.ghost, border: `1px solid ${t.line}`, padding: '4px 9px', borderRadius: 999 }}>
      <span style={{ width: 6, height: 6, borderRadius: 999, background: t.color }} />{t.label}
    </span>
  );
}

function LaneTag({ lane }) {
  if (lane === 'PR') return <span className="er-lane" style={{ color: '#FF7A87', background: 'var(--sev-critical-ghost)', borderColor: 'var(--sev-critical-line)' }}>PR · срочно</span>;
  if (lane === 'SMM') return <span className="er-lane" style={{ color: 'var(--brand-bright)', background: 'var(--brand-ghost)', borderColor: 'var(--brand-line)' }}>SMM</span>;
  return <span className="er-lane" style={{ color: 'var(--fg-3)', background: 'var(--surface-2)', borderColor: 'var(--line-2)' }}>Решает человек</span>;
}
