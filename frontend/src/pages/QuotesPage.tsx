import { Alert, Badge, Skeleton, Table, Tag } from 'antd'
import type { TableProps } from 'antd'
import { Link, useNavigate } from 'react-router'
import { useQuotes } from '../api/queries'
import type { QuoteSummary } from '../api/types'
import { LabelTag } from '../components/LabelTag'
import { PageHeader } from '../components/PageHeader'
import { dateTime } from '../lib/format'
import { estimateStatus } from '../lib/labels'

const quotePath = (quote: QuoteSummary) => `/quotes/${quote.quote_request_id}`

function judgeTag(trusted: boolean | null) {
  if (trusted === null) return <Tag>Not judged</Tag>
  return trusted ? <Tag color="green">Auto-send</Tag> : <Tag color="gold">Needs review</Tag>
}

const COLUMNS: TableProps<QuoteSummary>['columns'] = [
  {
    title: 'Quote',
    render: (_, quote) => (
      <Link to={quotePath(quote)} onClick={(event) => event.stopPropagation()} className="font-medium">
        {quote.case_id ?? quote.quote_request_id.slice(0, 8)}
      </Link>
    ),
  },
  {
    title: 'Customer',
    render: (_, quote) => quote.customer_id ?? <span className="text-slate-400">Unresolved</span>,
  },
  {
    title: 'Latest estimate',
    render: (_, quote) =>
      quote.latest_estimate_status ? (
        <LabelTag label={estimateStatus(quote.latest_estimate_status)} />
      ) : (
        <span className="text-slate-400">No estimate</span>
      ),
  },
  { title: 'Judge', render: (_, quote) => judgeTag(quote.latest_trusted) },
  {
    title: 'Open flags',
    align: 'right',
    sorter: (a, b) => a.open_review_items - b.open_review_items,
    render: (_, quote) =>
      quote.open_review_items > 0 ? (
        <Badge count={quote.open_review_items} color="gold" />
      ) : (
        <span className="text-slate-400 tabular-nums">0</span>
      ),
  },
  { title: 'Duplicate', render: (_, quote) => (quote.is_duplicate ? <Tag color="red">Duplicate</Tag> : null) },
  {
    title: 'Received',
    align: 'right',
    defaultSortOrder: 'descend',
    sorter: (a, b) => a.created_at.localeCompare(b.created_at),
    render: (_, quote) => <span className="whitespace-nowrap text-slate-500">{dateTime(quote.created_at)}</span>,
  },
]

export function QuotesPage() {
  const { data, error, isLoading } = useQuotes()
  const navigate = useNavigate()
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="All quotes"
        description={data ? `${data.length} quote request${data.length === 1 ? '' : 's'} received` : 'Every quote request received'}
      />
      {isLoading && <Skeleton active paragraph={{ rows: 6 }} />}
      {error && <Alert type="error" showIcon title={error.message} />}
      {data && (
        <Table<QuoteSummary>
          className="overflow-hidden rounded-lg border border-slate-200"
          columns={COLUMNS}
          dataSource={data}
          rowKey="quote_request_id"
          rowClassName="cursor-pointer"
          onRow={(quote) => ({ onClick: () => navigate(quotePath(quote)) })}
          pagination={data.length > 20 ? { pageSize: 20, hideOnSinglePage: true } : false}
          locale={{ emptyText: 'No quotes yet.' }}
        />
      )}
    </div>
  )
}
