import { Alert, Card, Spin, Statistic } from 'antd'
import { useGraphStats, useMetrics } from '../api/queries'
import { CountBarChart } from '../components/CountBarChart'
import { percent } from '../lib/format'

interface RateCardProps {
  title: string
  rate: number | null
  detail: string
  definition: string
}

function RateCard({ title, rate, detail, definition }: RateCardProps) {
  return (
    <Card>
      <Statistic title={title} value={percent(rate)} />
      <p className="mt-2">{detail}</p>
      <p className="mt-1 text-gray-500">{definition}</p>
    </Card>
  )
}

export function DashboardPage() {
  const { data, error, isLoading } = useMetrics()
  const graphStats = useGraphStats()
  if (isLoading) return <Spin />
  if (error) return <Alert type="error" title={error.message} />
  if (!data) return null

  const { counts } = data
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <div className="grid gap-4 md:grid-cols-3">
        <RateCard
          title="Auto-send rate"
          rate={data.auto_send_rate}
          detail={`${counts.verdicts_trusted} of ${counts.verdicts_total} judge verdicts were trusted`}
          definition="Trusted judge verdicts divided by all judge verdicts."
        />
        <RateCard
          title="Correction rate"
          rate={data.correction_rate}
          detail={`${counts.review_items_corrected} of ${counts.review_items_resolved} resolved review items were corrected`}
          definition="Corrected review items divided by resolved review items."
        />
        <RateCard
          title="Duplicate rate"
          rate={data.duplicate_rate}
          detail={`${counts.requests_duplicate} of ${counts.requests_compared} compared requests are duplicates`}
          definition="Requests with a DUPLICATE_OF verdict divided by requests that have any dedupe verdict."
        />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <CountBarChart
          title="Flags by dimension"
          counts={counts.flags_by_dimension}
          emptyText="No flags yet"
          color="#fa541c"
        />
        {graphStats.data ? (
          <CountBarChart title="Graph nodes by type" counts={graphStats.data.node_counts} emptyText="Graph is empty" />
        ) : (
          <Alert type="info" title={graphStats.error?.message ?? 'Loading graph counts'} />
        )}
        {graphStats.data && (
          <CountBarChart
            title="Graph edges by type"
            counts={graphStats.data.edge_counts}
            emptyText="Graph is empty"
            color="#722ed1"
          />
        )}
      </div>
    </div>
  )
}
