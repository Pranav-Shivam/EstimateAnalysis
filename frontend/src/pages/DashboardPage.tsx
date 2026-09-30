import { Alert, Card, Skeleton, Statistic } from 'antd'
import { useGraphStats, useMetrics } from '../api/queries'
import { CountBarChart } from '../components/CountBarChart'
import { PageHeader } from '../components/PageHeader'
import { percent } from '../lib/format'
import { dimensionLabel } from '../lib/labels'

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
      <p className="mt-2 mb-0 text-slate-700">{detail}</p>
      <p className="mt-1 mb-0 text-sm text-slate-500">{definition}</p>
    </Card>
  )
}

// GraphMeta holds the graph's own build fingerprint; it is not data a reviewer cares about.
const withoutBookkeeping = ({ GraphMeta: _meta, ...counts }: Record<string, number>) => counts

export function DashboardPage() {
  const { data, error, isLoading } = useMetrics()
  const graphStats = useGraphStats()
  if (isLoading) return <Skeleton active paragraph={{ rows: 8 }} />
  if (error) return <Alert type="error" showIcon title={error.message} />
  if (!data) return null

  const { counts } = data
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Dashboard" description="How often estimates go out untouched, how often reviewers correct them, and what the graph holds." />
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
          definition="Requests with a duplicate verdict divided by requests that have any dedupe verdict."
        />
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <CountBarChart
          title="Flags by dimension"
          counts={Object.fromEntries(
            Object.entries(counts.flags_by_dimension).map(([dimension, count]) => [dimensionLabel(dimension), count]),
          )}
          emptyText="No flags yet"
          color="#d97706"
        />
        {graphStats.data ? (
          <CountBarChart title="Graph nodes by type" counts={withoutBookkeeping(graphStats.data.node_counts)} emptyText="Graph is empty" />
        ) : (
          <Alert type="info" title={graphStats.error?.message ?? 'Loading graph counts'} />
        )}
        {graphStats.data && (
          <CountBarChart
            title="Graph edges by type"
            counts={graphStats.data.edge_counts}
            emptyText="Graph is empty"
            color="#0d9488"
          />
        )}
      </div>
    </div>
  )
}
