import { Alert, Spin, Table, Tag } from 'antd'
import type { TableProps } from 'antd'
import { Link } from 'react-router'
import { useQuotes } from '../api/queries'
import type { QuoteSummary } from '../api/types'
import { dateTime } from '../lib/format'

function judgeTag(trusted: boolean | null) {
  if (trusted === null) return <Tag>Not judged</Tag>
  return trusted ? <Tag color="green">Auto-send</Tag> : <Tag color="gold">Needs review</Tag>
}

const COLUMNS: TableProps<QuoteSummary>['columns'] = [
  {
    title: 'Quote',
    render: (_, quote) => (
      <Link to={`/quotes/${quote.quote_request_id}`}>{quote.case_id ?? quote.quote_request_id.slice(0, 8)}</Link>
    ),
  },
  { title: 'Customer', render: (_, quote) => quote.customer_id ?? 'unresolved' },
  {
    title: 'Latest estimate',
    render: (_, quote) =>
      quote.latest_estimate_status ? (
        <Tag color={quote.latest_estimate_status === 'ready' ? 'green' : 'red'}>{quote.latest_estimate_status}</Tag>
      ) : (
        'none'
      ),
  },
  { title: 'Judge', render: (_, quote) => judgeTag(quote.latest_trusted) },
  { title: 'Open flags', dataIndex: 'open_review_items' },
  { title: 'Duplicate', render: (_, quote) => (quote.is_duplicate ? <Tag color="red">duplicate</Tag> : null) },
  { title: 'Received', render: (_, quote) => dateTime(quote.created_at) },
]

export function QuotesPage() {
  const { data, error, isLoading } = useQuotes()
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold">All quotes</h1>
      {isLoading && <Spin />}
      {error && <Alert type="error" title={error.message} />}
      {data && (
        <Table<QuoteSummary>
          columns={COLUMNS}
          dataSource={data}
          rowKey="quote_request_id"
          pagination={false}
          locale={{ emptyText: 'No quotes yet.' }}
        />
      )}
    </div>
  )
}
