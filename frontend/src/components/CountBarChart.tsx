import { Card, Empty } from 'antd'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

interface Props {
  title: string
  counts: Record<string, number>
  emptyText: string
  color?: string
}

const CHART_HEIGHT = 280

export function CountBarChart({ title, counts, emptyText, color = '#1677ff' }: Props) {
  const data = Object.entries(counts)
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count)
  const hasData = data.some((row) => row.count > 0)
  return (
    <Card title={title}>
      {hasData ? (
        <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
          <BarChart data={data} layout="vertical" margin={{ left: 40 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis type="number" allowDecimals={false} />
            <YAxis type="category" dataKey="name" width={130} tick={{ fontSize: 11 }} />
            <Tooltip />
            <Bar dataKey="count" fill={color} />
          </BarChart>
        </ResponsiveContainer>
      ) : (
        <Empty description={emptyText} />
      )}
    </Card>
  )
}
