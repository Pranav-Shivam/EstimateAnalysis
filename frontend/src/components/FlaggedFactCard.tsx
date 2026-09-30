import { Alert, Button, Card, Tag } from 'antd'
import { useState } from 'react'
import { useResolveReviewItem } from '../api/queries'
import type { QuoteReviewItem, QuoteSkuInfo } from '../api/types'
import { flaggedRows } from '../lib/correction'
import { dimensionLabel } from '../lib/dimensions'
import { dateTime } from '../lib/format'
import { CorrectionForm } from './CorrectionForm'
import { EvidencePanel } from './EvidencePanel'

export const CORRECTION_SAVED = 'Correction saved. It is applied to the reference data in the background.'

interface Props {
  item: QuoteReviewItem
  skus: Record<string, QuoteSkuInfo>
}

interface Violation {
  guardrail?: string
  line_index?: number | null
  message?: string
}

function GuardrailNotice({ item }: { item: QuoteReviewItem }) {
  const violations = Array.isArray(item.evidence.violations) ? (item.evidence.violations as Violation[]) : []
  return (
    <Card title={<>Blocked by guardrails <Tag color="red">{dimensionLabel(item.dimension)}</Tag></>}>
      <div className="flex flex-col gap-3">
        <p className="text-base font-medium">{item.fact}</p>
        {violations.length > 0 && (
          <ul className="list-disc pl-5">
            {violations.map((violation, index) => (
              <li key={index}>
                {violation.line_index != null ? `line ${violation.line_index}: ` : ''}
                {violation.message}
              </li>
            ))}
          </ul>
        )}
        <Alert type="info" title="Guardrail-blocked drafts cannot be resolved from this screen yet." />
      </div>
    </Card>
  )
}

function ResolvedSummary({ item }: { item: QuoteReviewItem }) {
  const message =
    item.status === 'consolidated'
      ? 'Applied to the reference data.'
      : item.status === 'corrected'
        ? CORRECTION_SAVED
        : 'Approved as is.'
  return (
    <Card title={<>Resolved <Tag>{dimensionLabel(item.dimension)}</Tag></>}>
      <div className="flex flex-col gap-3">
        <p className="text-base font-medium">{item.fact}</p>
        <Alert type="success" title={message} />
        {item.correction && <pre className="rounded bg-gray-50 p-3">{JSON.stringify(item.correction, null, 2)}</pre>}
        {item.resolved_at && <p className="text-gray-500">Resolved {dateTime(item.resolved_at)}</p>}
      </div>
    </Card>
  )
}

export function FlaggedFactCard({ item, skus }: Props) {
  const resolve = useResolveReviewItem()
  const [correcting, setCorrecting] = useState(false)

  if (item.dimension === 'guardrail') return <GuardrailNotice item={item} />
  if (item.status !== 'open') return <ResolvedSummary item={item} />

  const saved = resolve.isSuccess && resolve.variables.body.outcome === 'corrected'
  return (
    <Card title={<>Check this <Tag color="gold">{dimensionLabel(item.dimension)}</Tag></>}>
      <div className="flex flex-col gap-4">
        <p className="text-base font-medium">{item.fact}</p>
        <EvidencePanel dimension={item.dimension} rows={flaggedRows(item.evidence)} skus={skus} />
        {resolve.isError && <Alert type="error" title={resolve.error.message} />}
        {saved ? (
          <Alert type="success" title={CORRECTION_SAVED} />
        ) : correcting ? (
          <CorrectionForm
            item={item}
            skus={skus}
            busy={resolve.isPending}
            onCancel={() => setCorrecting(false)}
            onSubmit={(correction) => resolve.mutate({ id: item.id, body: { outcome: 'corrected', correction } })}
          />
        ) : (
          <div className="flex gap-3">
            <Button
              type="primary"
              loading={resolve.isPending}
              onClick={() => resolve.mutate({ id: item.id, body: { outcome: 'approved' } })}
            >
              Approve as is
            </Button>
            <Button onClick={() => setCorrecting(true)}>Correct</Button>
          </div>
        )}
      </div>
    </Card>
  )
}
