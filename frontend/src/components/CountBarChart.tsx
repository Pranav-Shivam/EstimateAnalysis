import { Card, Empty } from 'antd'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

interface Props {
  title: string
  counts: Record<string, number>
  emptyText: string
  color?: string
}

const MIN_CHART_HEIGHT = 280
// Enough room per bar that every category name is drawn; the axis otherwise skips labels it cannot fit.
const ROW_HEIGHT = 30

export function CountBarChart({ title, counts, emptyText, color = '#4f46e5' }: Props) {
  const data = Object.entries(counts)
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count)
  const hasData = data.some((row) => row.count > 0)
  return (
    <Card title={title}>
      {hasData ? (
        <ResponsiveContainer width="100%" height={Math.max(MIN_CHART_HEIGHT, data.length * ROW_HEIGHT + 40)}>
          <BarChart data={data} layout="vertical" margin={{ left: 40 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
            <XAxis type="number" allowDecimals={false} />
            <YAxis type="category" dataKey="name" width={130} interval={0} tick={{ fontSize: 11 }} />
            <Tooltip cursor={{ fill: '#f1f5f9' }} />
            <Bar dataKey="count" fill={color} radius={[0, 4, 4, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      ) : (
        <Empty description={emptyText} />
      )}
    </Card>
  )
}
