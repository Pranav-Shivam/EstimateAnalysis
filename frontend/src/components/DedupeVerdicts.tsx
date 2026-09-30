import { Table, Tag } from 'antd'
import type { TableProps } from 'antd'
import { Link } from 'react-router'
import type { DedupeVerdict } from '../api/types'
import { percent } from '../lib/format'

const VERDICT_COLORS: Record<string, string> = { DUPLICATE_OF: 'red', REVISION_OF: 'gold', DISTINCT: 'default' }

export function DedupeVerdicts({ verdicts }: { verdicts: DedupeVerdict[] }) {
  if (verdicts.length === 0) {
    return <p className="text-gray-500">No similar requests were found for this customer.</p>
  }
  const columns: TableProps<DedupeVerdict>['columns'] = [
    {
      title: 'Compared with',
      render: (_, verdict) => <Link to={`/quotes/${verdict.candidate_quote_request_id}`}>Open earlier request</Link>,
    },
    {
      title: 'Verdict',
      render: (_, verdict) => <Tag color={VERDICT_COLORS[verdict.verdict]}>{verdict.verdict}</Tag>,
    },
    { title: 'Same items', render: (_, verdict) => percent(verdict.content_jaccard) },
    { title: 'Same wording', render: (_, verdict) => percent(verdict.style_jaccard) },
    {
      title: 'Signals',
      render: (_, verdict) => verdict.signals_fired.map((signal) => <Tag key={signal}>{signal}</Tag>),
    },
  ]
  return (
    <Table<DedupeVerdict>
      size="small"
      pagination={false}
      columns={columns}
      dataSource={verdicts}
      rowKey="candidate_quote_request_id"
    />
  )
}
