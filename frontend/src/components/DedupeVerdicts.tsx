import { Tag } from 'antd'
import { Link } from 'react-router'
import type { DedupeVerdict } from '../api/types'
import { percent } from '../lib/format'
import { dedupeSignal, dedupeVerdict } from '../lib/labels'
import { LabelTag } from './LabelTag'

export function DedupeVerdicts({ verdicts }: { verdicts: DedupeVerdict[] }) {
  if (verdicts.length === 0) {
    return <p className="m-0 text-slate-500">No similar requests were found for this customer.</p>
  }
  return (
    <ul className="m-0 flex list-none flex-col divide-y divide-slate-100 p-0">
      {verdicts.map((verdict) => (
        <li key={verdict.candidate_quote_request_id} className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0">
          <div className="flex items-center justify-between gap-3">
            <LabelTag label={dedupeVerdict(verdict.verdict)} />
            <Link to={`/quotes/${verdict.candidate_quote_request_id}`}>Open earlier request</Link>
          </div>
          <dl className="m-0 grid grid-cols-2 gap-2">
            <div>
              <dt className="text-xs text-slate-500">Same items</dt>
              <dd className="m-0 font-medium tabular-nums">{percent(verdict.content_jaccard)}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Same wording</dt>
              <dd className="m-0 font-medium tabular-nums">{percent(verdict.style_jaccard)}</dd>
            </div>
          </dl>
          {verdict.signals_fired.length > 0 && (
            <div>
              {verdict.signals_fired.map((signal) => (
                <Tag key={signal}>{dedupeSignal(signal)}</Tag>
              ))}
            </div>
          )}
        </li>
      ))}
    </ul>
  )
}
