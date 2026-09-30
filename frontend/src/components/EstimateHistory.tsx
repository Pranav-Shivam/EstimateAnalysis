import { Alert, Empty, Tabs } from 'antd'
import type { ReactNode } from 'react'
import type { QuoteEstimate, QuoteSkuInfo } from '../api/types'
import { dateTime } from '../lib/format'
import { estimateStatus } from '../lib/labels'
import { EstimateLinesTable } from './EstimateLinesTable'
import { FlaggedFactCard } from './FlaggedFactCard'
import { JudgePanel } from './JudgePanel'
import { LabelTag } from './LabelTag'

interface Props {
  estimates: QuoteEstimate[]
  skus: Record<string, QuoteSkuInfo>
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="m-0 text-xs font-semibold tracking-wide text-slate-500 uppercase">{title}</h2>
      {children}
    </section>
  )
}

function EstimatePanel({ estimate, skus }: { estimate: QuoteEstimate; skus: Record<string, QuoteSkuInfo> }) {
  const autoSent = estimate.judge_verdict?.trusted === true && estimate.review_items.length === 0
  const submissions = `${estimate.iterations} submission${estimate.iterations === 1 ? '' : 's'}`
  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-wrap items-center gap-3">
        <LabelTag label={estimateStatus(estimate.status)} />
        <span className="text-slate-500">
          {submissions} to the guardrails, created {dateTime(estimate.created_at)}
        </span>
      </div>
      {autoSent && (
        <Alert
          type="success"
          showIcon
          title="Auto-sent: the judge trusted this estimate, so no reviewer action was needed."
        />
      )}
      {estimate.review_items.length > 0 && (
        <Section title="Needs your review">
          {estimate.review_items.map((item) => (
            <FlaggedFactCard key={item.id} item={item} skus={skus} />
          ))}
        </Section>
      )}
      <Section title="Line items">
        <EstimateLinesTable estimate={estimate} skus={skus} />
      </Section>
      <Section title="Judge">
        <JudgePanel verdict={estimate.judge_verdict} />
      </Section>
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
