import { Alert, Empty, Tabs, Tag } from 'antd'
import type { QuoteEstimate, QuoteSkuInfo } from '../api/types'
import { dateTime } from '../lib/format'
import { EstimateLinesTable } from './EstimateLinesTable'
import { FlaggedFactCard } from './FlaggedFactCard'
import { JudgePanel } from './JudgePanel'

interface Props {
  estimates: QuoteEstimate[]
  skus: Record<string, QuoteSkuInfo>
}

function EstimatePanel({ estimate, skus }: { estimate: QuoteEstimate; skus: Record<string, QuoteSkuInfo> }) {
  const autoSent = estimate.judge_verdict?.trusted === true && estimate.review_items.length === 0
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <Tag color={estimate.status === 'ready' ? 'green' : 'red'}>{estimate.status}</Tag>
        <span className="text-gray-500">
          {estimate.iterations} submission(s), created {dateTime(estimate.created_at)}
        </span>
      </div>
      {autoSent && (
        <Alert type="success" title="Auto-sent: the judge trusted this estimate, so no reviewer action was needed." />
      )}
      <EstimateLinesTable estimate={estimate} skus={skus} />
      <JudgePanel verdict={estimate.judge_verdict} />
      {estimate.review_items.map((item) => (
        <FlaggedFactCard key={item.id} item={item} skus={skus} />
      ))}
    </div>
  )
}

export function EstimateHistory({ estimates, skus }: Props) {
  if (estimates.length === 0) return <Empty description="No estimate has been run for this quote yet." />
  return (
    <Tabs
      items={estimates.map((estimate, index) => ({
        key: estimate.estimate_id,
        label: index === 0 ? 'Latest estimate' : `Earlier estimate ${estimates.length - index}`,
        children: <EstimatePanel estimate={estimate} skus={skus} />,
      }))}
    />
  )
}
