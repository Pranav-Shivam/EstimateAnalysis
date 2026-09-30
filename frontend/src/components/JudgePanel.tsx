import { Progress, Tag } from 'antd'
import type { QuoteJudgeVerdict } from '../api/types'
import { dimensionLabel } from '../lib/dimensions'

export function JudgePanel({ verdict }: { verdict: QuoteJudgeVerdict | null }) {
  if (verdict === null) return <p className="text-gray-500">Not judged yet.</p>
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <Tag color={verdict.trusted ? 'green' : 'gold'}>{verdict.trusted ? 'Auto-send' : 'Needs review'}</Tag>
        <span className="text-gray-500">
          {verdict.model}, overall confidence {verdict.overall_confidence.toFixed(2)}
        </span>
      </div>
      {verdict.dimensions.length === 0 ? (
        <p>The guardrails blocked this draft before the judge ran.</p>
      ) : (
        verdict.dimensions.map((dimension) => (
          <div key={dimension.name} className="grid grid-cols-[10rem_12rem_1fr] items-center gap-3">
            <span>{dimensionLabel(dimension.name)}</span>
            <Progress percent={Math.round(dimension.score * 100)} size="small" />
            <span className="text-gray-600">{dimension.rationale}</span>
          </div>
        ))
      )}
    </div>
  )
}
