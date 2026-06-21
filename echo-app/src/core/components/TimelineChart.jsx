// Domain-agnostic recharts wrapper: volume bars (left axis) + line (right axis).
// Used by Stories.jsx story-detail panel; reusable for any dual-axis timeline.
// Цвета — канон дизайн-системы (recharts рендерит в SVG-атрибуты, var() там не
// работает, поэтому прямые hex из токенов: brand #2BB3C7, calm #34D8A0).
import {
  ResponsiveContainer, ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, CartesianGrid,
} from 'recharts';

// HEX-константы из дизайн-системы (var() не работает в SVG-атрибутах recharts)
const BRAND  = '#2BB3C7';
const CALM   = '#34D8A0';
const GRID   = '#243A50';   // --line-1
const FG3    = '#5C6E83';   // --fg-3 (оси)
const FG1    = '#EAF1F8';   // --fg-1 (подписи)

const tooltipStyle = {
  background: '#1C3349',           // --surface-1
  border: '1px solid #314A64',     // --line-2
  borderRadius: '10px',
  color: FG1,
  fontSize: '12px',
};

/**
 * @param {object[]} data  — array of { t, mentions, sources }
 * @param {number}   height
 */
export function TimelineChart({ data, height = 240 }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
        <XAxis dataKey="t" stroke={FG3} tick={{ fontSize: 11, fontFamily: 'var(--font-mono)' }} tickLine={false} axisLine={{ stroke: GRID }} />
        <YAxis yAxisId="l" allowDecimals={false} stroke={FG3} tick={{ fontSize: 11, fontFamily: 'var(--font-mono)' }} tickLine={false} axisLine={{ stroke: GRID }} />
        <YAxis yAxisId="r" orientation="right" allowDecimals={false} stroke={FG3} tick={{ fontSize: 11, fontFamily: 'var(--font-mono)' }} tickLine={false} axisLine={{ stroke: GRID }} />
        <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: FG3 }} />
        <Bar yAxisId="l" dataKey="mentions" name="Сообщения/час" fill={BRAND} radius={[3, 3, 0, 0]} />
        <Line yAxisId="r" dataKey="sources" name="Источников" stroke={CALM} dot={false} strokeWidth={2} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
