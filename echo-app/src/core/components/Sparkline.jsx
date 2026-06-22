// ============================================================================
// Sparkline — мини-график ряда снимков (просмотры во времени), тонированный фазой.
// Площадь (gradient) + линия + концевая точка. Канон: primitives.jsx.
// ============================================================================
export function Sparkline({ data, color = '#FFB23E', w = 96, h = 30 }) {
  if (!data || data.length < 2) {
    return <svg width={w} height={h} style={{ display: 'block' }} />;
  }
  const max = Math.max(...data), min = Math.min(...data);
  const span = max - min || 1;
  const pts = data.map((v, i) => [
    (i / (data.length - 1)) * w,
    h - 3 - ((v - min) / span) * (h - 6),
  ]);
  const line = pts.map(p => p.join(',')).join(' ');
  const area = `0,${h} ${line} ${w},${h}`;
  // Стабильный id градиента (без random — иначе ре-ренер плодит <defs>).
  const gid = 'spk' + (color.replace(/[^a-z0-9]/gi, '').slice(0, 6) || 'dflt') + w;
  return (
    <svg width={w} height={h} style={{ display: 'block' }}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity="0.28" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={area} fill={`url(#${gid})`} />
      <polyline points={line} fill="none" stroke={color} strokeWidth="2"
        strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r="2.6" fill={color} />
    </svg>
  );
}
