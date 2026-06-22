// Activity sparkline — тоньше витринного, без градиента-заливки (только линия).
// Цвет = уровень spike. Канон: project Sparkline, но stripped-down для доски.
export function IntelSparkline({ data, color = '#FFB23E', w = 64, h = 20 }) {
  if (!data || data.length < 2) return null;
  const max = Math.max(...data), min = Math.min(...data);
  const span = max - min || 1;
  const pts = data.map((v, i) => [
    (i / (data.length - 1)) * w,
    h - 2 - ((v - min) / span) * (h - 4),
  ]);
  const line = pts.map(p => p.join(',')).join(' ');
  return (
    <svg width={w} height={h} className="sparkWrap">
      <polyline points={line} fill="none" stroke={color} strokeWidth="1.5"
        strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r="2" fill={color} />
    </svg>
  );
}
