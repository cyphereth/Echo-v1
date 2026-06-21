// Domain-agnostic recharts wrapper: volume bars (left axis) + line (right axis).
// Used by Stories.jsx story-detail panel; reusable for any dual-axis timeline.
import {
  ResponsiveContainer, ComposedChart, Bar, Line, XAxis, YAxis, Tooltip, CartesianGrid,
} from 'recharts';

/**
 * @param {object[]} data  — array of { t, mentions, sources }
 * @param {number}   height
 */
export function TimelineChart({ data, height = 240 }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="t" />
        <YAxis yAxisId="l" allowDecimals={false} />
        <YAxis yAxisId="r" orientation="right" allowDecimals={false} />
        <Tooltip />
        <Bar yAxisId="l" dataKey="mentions" name="Сообщения/час" fill="#6366f1" />
        <Line yAxisId="r" dataKey="sources" name="Источников" stroke="#16a34a" dot={false} strokeWidth={2} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
