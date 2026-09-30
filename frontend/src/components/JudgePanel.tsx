import { Progress, Tag } from 'antd'
import type { QuoteJudgeVerdict } from '../api/types'
import { dimensionLabel } from '../lib/labels'
import { RichText } from './RichText'

// Color bands only steer the eye to weak scores. The trust decision itself uses the calibrated threshold on the
// backend (current_threshold in backend/app/judge/service.py) and arrives here as `trusted`.
const STRONG_SCORE = 0.8
const WEAK_SCORE = 0.5

function scoreColor(score: number): string {
  if (score >= STRONG_SCORE) return '#16a34a'
  return score >= WEAK_SCORE ? '#d97706' : '#dc2626'
}

const asPercent = (score: number) => `${Math.round(score * 100)}%`

export function JudgePanel({ verdict }: { verdict: QuoteJudgeVerdict | null }) {
  if (verdict === null) return <p className="m-0 text-slate-500">Not judged yet.</p>
  const skipped = verdict.dimensions.length === 0
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Tag color={verdict.trusted ? 'green' : 'gold'}>{verdict.trusted ? 'Auto-send' : 'Needs review'}</Tag>
        {!skipped && (
          <span className="text-slate-500">
            Overall confidence <span className="font-medium text-slate-800 tabular-nums">{asPercent(verdict.overall_confidence)}</span>
            , scored by {verdict.model}
          </span>
        )}
      </div>
      {skipped ? (
        <p className="m-0">The guardrails blocked this draft before the judge ran.</p>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-4 p-0">
          {verdict.dimensions.map((dimension) => (
            <li key={dimension.name} className="grid gap-1 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-4">
              <span className="font-medium text-slate-700">{dimensionLabel(dimension.name)}</span>
              <div className="flex flex-col gap-1">
                <Progress
                  percent={Math.round(dimension.score * 100)}
                  strokeColor={scoreColor(dimension.score)}
                  size="small"
                  aria-label={`${dimensionLabel(dimension.name)} score`}
                />
                <span className="text-slate-600"><RichText>{dimension.rationale}</RichText></span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
