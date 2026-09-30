import { Alert, Segmented, Spin, Table, Tag } from 'antd'
import type { TableProps } from 'antd'
import { useState } from 'react'
import { Link } from 'react-router'
import { useReviewItems } from '../api/queries'
import type { ReviewItem, ReviewStatus } from '../api/types'
import { dimensionLabel } from '../lib/dimensions'
import { dateTime } from '../lib/format'

const COLUMNS: TableProps<ReviewItem>['columns'] = [
  { title: 'Flag', render: (_, item) => <Tag color="gold">{dimensionLabel(item.dimension)}</Tag> },
  { title: 'Fact to check', dataIndex: 'fact' },
  { title: 'Quote', render: (_, item) => <Link to={`/quotes/${item.quote_request_id}`}>Open quote</Link> },
  { title: 'Raised', render: (_, item) => dateTime(item.created_at) },
  {
    title: 'Status',
    render: (_, item) => (item.status === 'open' ? <Tag color="gold">open</Tag> : <Tag>{item.outcome ?? item.status}</Tag>),
  },
]

export function QueuePage() {
  const [status, setStatus] = useState<ReviewStatus>('open')
  const { data, error, isLoading } = useReviewItems(status)

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold">Review queue</h1>
      <Segmented<ReviewStatus>
        value={status}
        onChange={setStatus}
        options={[
          { label: 'Open', value: 'open' },
          { label: 'Resolved', value: 'resolved' },
          { label: 'All', value: 'all' },
        ]}
      />
      {isLoading && <Spin />}
      {error && <Alert type="error" title={error.message} />}
      {data && (
        <Table<ReviewItem>
          columns={COLUMNS}
          dataSource={data}
          rowKey="id"
          pagination={false}
          locale={{ emptyText: status === 'open' ? 'The queue is clear.' : 'Nothing to show for this filter.' }}
        />
      )}
    </div>
  )
}
