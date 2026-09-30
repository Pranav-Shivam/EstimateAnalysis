import { Alert, Button, Card, Descriptions, Tag } from 'antd'
import { useState } from 'react'
import { useResolveReviewItem } from '../api/queries'
import type { QuoteReviewItem, QuoteSkuInfo } from '../api/types'
import { flaggedRows } from '../lib/correction'
import { correctionField, dimensionLabel, guardrailLabel, lineNumber } from '../lib/labels'
import { dateTime, money } from '../lib/format'
import { CorrectionForm } from './CorrectionForm'
import { EvidencePanel } from './EvidencePanel'
import { RichText } from './RichText'

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
    <Card className="border-l-4 border-l-red-500" title="Blocked by guardrails">
      <div className="flex flex-col gap-3">
        <p className="m-0 text-base font-medium text-slate-900"><RichText>{item.fact}</RichText></p>
        {violations.length > 0 && (
          <ul className="list-disc pl-5">
            {violations.map((violation, index) => (
              <li key={index}>
                {violation.line_index != null && `${lineNumber(violation.line_index)}, `}
                {violation.guardrail && `${guardrailLabel(violation.guardrail)}: `}
                {violation.message}
              </li>
            ))}
          </ul>
        )}
        <Alert type="info" showIcon title="Guardrail-blocked drafts cannot be resolved from this screen yet." />
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
        <p className="m-0 text-base font-medium text-slate-900"><RichText>{item.fact}</RichText></p>
        <Alert type="success" showIcon title={message} />
        {item.correction && (
          <Descriptions
            size="small"
            bordered
            column={1}
            items={Object.entries(item.correction).map(([field, value]) => ({
              key: field,
              label: correctionField(field),
              children: typeof value === 'number' && field === 'corrected_unit_price' ? money(value) : String(value),
            }))}
          />
        )}
        {item.resolved_at && <p className="m-0 text-slate-500">Resolved {dateTime(item.resolved_at)}</p>}
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
    <Card className="border-l-4 border-l-amber-400" title={<>Check this <Tag color="gold">{dimensionLabel(item.dimension)}</Tag></>}>
      <div className="flex flex-col gap-4">
        <p className="m-0 text-base font-medium text-slate-900"><RichText>{item.fact}</RichText></p>
        <EvidencePanel dimension={item.dimension} rows={flaggedRows(item.evidence)} skus={skus} />
        {resolve.isError && <Alert type="error" showIcon title={resolve.error.message} />}
        {saved ? (
          <Alert type="success" showIcon title={CORRECTION_SAVED} />
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
