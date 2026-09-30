import { ArrowRightOutlined } from '@ant-design/icons'
import { Alert, Segmented, Skeleton, Table, Tag } from 'antd'
import type { TableProps } from 'antd'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { useReviewItems } from '../api/queries'
import type { ReviewItem, ReviewStatus } from '../api/types'
import { LabelTag } from '../components/LabelTag'
import { PageHeader } from '../components/PageHeader'
import { RichText } from '../components/RichText'
import { dimensionLabel, reviewStatus } from '../lib/labels'
import { dateTime } from '../lib/format'

const quotePath = (item: ReviewItem) => `/quotes/${item.quote_request_id}`

const COLUMNS: TableProps<ReviewItem>['columns'] = [
  { title: 'Flag', width: 180, render: (_, item) => <Tag color="gold">{dimensionLabel(item.dimension)}</Tag> },
  { title: 'Fact to check', render: (_, item) => <span className="font-medium text-slate-800"><RichText>{item.fact}</RichText></span> },
  {
    title: 'Raised',
    width: 190,
    render: (_, item) => <span className="whitespace-nowrap text-slate-500">{dateTime(item.created_at)}</span>,
  },
  { title: 'Status', width: 120, render: (_, item) => <LabelTag label={reviewStatus(item.outcome ?? item.status)} /> },
  {
    title: <span className="sr-only">Quote</span>,
    width: 130,
    align: 'right',
    render: (_, item) => (
      <Link to={quotePath(item)} onClick={(event) => event.stopPropagation()} className="whitespace-nowrap">
        Open quote <ArrowRightOutlined aria-hidden />
      </Link>
    ),
  },
]

export function QueuePage() {
  const [status, setStatus] = useState<ReviewStatus>('open')
  const { data, error, isLoading } = useReviewItems(status)
  const navigate = useNavigate()

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Review queue"
        description="Facts the judge could not confirm on its own. Each one needs a single decision: approve or correct."
        extra={
          <Segmented<ReviewStatus>
            value={status}
            onChange={setStatus}
            options={[
              { label: 'Open', value: 'open' },
              { label: 'Resolved', value: 'resolved' },
              { label: 'All', value: 'all' },
            ]}
          />
        }
      />
      {isLoading && <Skeleton active paragraph={{ rows: 6 }} />}
      {error && <Alert type="error" showIcon title={error.message} />}
      {data && (
        <Table<ReviewItem>
          className="overflow-hidden rounded-lg border border-slate-200"
          columns={COLUMNS}
          dataSource={data}
          rowKey="id"
          rowClassName="cursor-pointer"
          onRow={(item) => ({ onClick: () => navigate(quotePath(item)) })}
          pagination={data.length > 20 ? { pageSize: 20, hideOnSinglePage: true } : false}
          locale={{ emptyText: status === 'open' ? 'The queue is clear. Nothing needs a reviewer right now.' : 'Nothing to show for this filter.' }}
        />
      )}
    </div>
  )
}
