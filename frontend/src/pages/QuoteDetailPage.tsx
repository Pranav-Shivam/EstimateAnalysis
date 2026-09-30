import { Alert, Card, Spin, Tag } from 'antd'
import { useParams } from 'react-router'
import { useQuote } from '../api/queries'
import { DedupeVerdicts } from '../components/DedupeVerdicts'
import { EstimateHistory } from '../components/EstimateHistory'

export function QuoteDetailPage() {
  const { id = '' } = useParams<{ id: string }>()
  const { data, error, isLoading } = useQuote(id)

  if (isLoading) return <Spin />
  if (error) return <Alert type="error" title={error.message} />
  if (!data) return null

  const isDuplicate = data.dedupe_verdicts.some((verdict) => verdict.verdict === 'DUPLICATE_OF')
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-semibold">Quote {data.case_id ?? data.quote_request_id.slice(0, 8)}</h1>
        {isDuplicate && <Tag color="red">duplicate</Tag>}
        <span className="text-gray-500">Customer {data.customer_id ?? 'unresolved'}</span>
      </div>
      <Card title="Customer email">
        <pre className="whitespace-pre-wrap font-sans">{data.raw_email_text}</pre>
      </Card>
      <Card title="Similar requests">
        <DedupeVerdicts verdicts={data.dedupe_verdicts} />
      </Card>
      <Card title="Estimates">
        <EstimateHistory estimates={data.estimates} skus={data.skus} />
      </Card>
    </div>
  )
}
