import { Alert, Breadcrumb, Card, Skeleton, Tag } from 'antd'
import { Link, useParams } from 'react-router'
import { useQuote } from '../api/queries'
import { DedupeVerdicts } from '../components/DedupeVerdicts'
import { EstimateHistory } from '../components/EstimateHistory'
import { LabelTag } from '../components/LabelTag'
import { PageHeader } from '../components/PageHeader'
import { dateTime } from '../lib/format'
import { estimateStatus } from '../lib/labels'

export function QuoteDetailPage() {
  const { id = '' } = useParams<{ id: string }>()
  const { data, error, isLoading } = useQuote(id)

  if (isLoading) return <Skeleton active paragraph={{ rows: 10 }} />
  if (error) return <Alert type="error" showIcon title={error.message} />
  if (!data) return null

  const name = data.case_id ?? data.quote_request_id.slice(0, 8)
  const isDuplicate = data.dedupe_verdicts.some((verdict) => verdict.verdict === 'DUPLICATE_OF')
  const latest = data.estimates[0]
  const meta = [
    `Customer ${data.customer_id ?? 'unresolved'}`,
    data.contract_id && `Contract ${data.contract_id}`,
    `Received ${dateTime(data.created_at)}`,
  ].filter(Boolean)

  return (
    <div className="flex flex-col gap-6">
      <Breadcrumb items={[{ title: <Link to="/quotes">All quotes</Link> }, { title: name }]} />
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-3">
            Quote {name}
            {latest && <LabelTag label={estimateStatus(latest.status)} />}
            {isDuplicate && <Tag color="red">Duplicate</Tag>}
          </span>
        }
        description={meta.join('  ·  ')}
      />
      <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div className="flex flex-col gap-6 lg:sticky lg:top-20">
          <Card title="Customer email">
            <pre className="m-0 max-h-[28rem] overflow-auto whitespace-pre-wrap font-sans leading-relaxed text-slate-700">
              {data.raw_email_text}
            </pre>
          </Card>
          <Card title="Similar requests">
            <DedupeVerdicts verdicts={data.dedupe_verdicts} />
          </Card>
        </div>
        <Card title="Estimates">
          <EstimateHistory estimates={data.estimates} skus={data.skus} />
        </Card>
      </div>
    </div>
  )
}
