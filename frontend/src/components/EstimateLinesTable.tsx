import { Alert, Empty, Table, Tag } from 'antd'
import type { TableProps } from 'antd'
import type { DraftLine, QuoteEstimate, QuoteSkuInfo } from '../api/types'
import { money } from '../lib/format'
import { adjustmentLabel, guardrailLabel, lineNumber, priceSource } from '../lib/labels'
import { LabelTag } from './LabelTag'
import { RichText } from './RichText'

interface Props {
  estimate: QuoteEstimate
  skus: Record<string, QuoteSkuInfo>
}

function lineTotal(line: DraftLine): number {
  return (line.quantity ?? 0) * (line.unit_price ?? 0) * (1 - (line.discount_pct ?? 0) / 100)
}

const numeric = (text: string) => <span className="tabular-nums">{text}</span>

export function EstimateLinesTable({ estimate, skus }: Props) {
  const { draft, totals } = estimate
  if (!draft) {
    return <Empty description={<RichText>{estimate.reason ?? 'No draft was produced for this estimate.'}</RichText>} />
  }

  const columns: TableProps<DraftLine>['columns'] = [
    {
      title: 'Item',
      render: (_, line) => {
        const sku = line.sku_id ? skus[line.sku_id] : undefined
        if (!sku) return line.sku_id ?? <span className="text-slate-400">Unresolved</span>
        return (
          <div className="flex flex-col">
            <span className="font-medium text-slate-800">{sku.name}</span>
            <span className="text-xs text-slate-500">{line.sku_id}</span>
          </div>
        )
      },
    },
    { title: 'Qty', align: 'right', render: (_, line) => numeric(String(line.quantity ?? 0)) },
    { title: 'Unit price', align: 'right', render: (_, line) => numeric(money(line.unit_price)) },
    { title: 'Source', render: (_, line) => (line.price_source ? <LabelTag label={priceSource(line.price_source)} /> : null) },
    { title: 'Discount', align: 'right', render: (_, line) => numeric(`${line.discount_pct ?? 0}%`) },
    { title: 'Line total', align: 'right', render: (_, line) => <span className="font-medium">{numeric(money(lineTotal(line)))}</span> },
  ]

  const adjustments = draft.adjustments ?? []
  return (
    <div className="flex flex-col gap-4">
      <Table<DraftLine>
        size="small"
        pagination={false}
        columns={columns}
        dataSource={draft.lines}
        rowKey={(line, index) => `${line.sku_id}-${index}`}
        scroll={{ x: 'max-content' }}
      />
      {totals && (
        <dl className="m-0 ml-auto grid w-full max-w-xs grid-cols-[1fr_auto] gap-x-6 gap-y-1 rounded-lg bg-slate-50 p-4 tabular-nums">
          <dt className="text-slate-500">List total</dt>
          <dd className="m-0 text-right">{money(totals.list_total)}</dd>
          <dt className="text-slate-500">Discount</dt>
          <dd className="m-0 text-right">{money(totals.discount_total)}</dd>
          <dt className="mt-1 border-t border-slate-200 pt-2 font-medium text-slate-800">Net total</dt>
          <dd className="m-0 mt-1 border-t border-slate-200 pt-2 text-right text-base font-semibold text-slate-900">
            {money(totals.net_total)}
          </dd>
        </dl>
      )}
      {adjustments.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {adjustments.map((adjustment, index) => (
            <li key={index} className="flex items-start gap-2">
              <Tag color="blue">{adjustmentLabel(adjustment.kind)}</Tag>
              <span className="text-slate-700"><RichText>{adjustment.detail}</RichText></span>
            </li>
          ))}
        </ul>
      )}
      {estimate.violations.length > 0 && (
        <Alert
          type="error"
          showIcon
          title="Guardrail violations"
          description={
            <ul className="m-0 list-disc pl-5">
              {estimate.violations.map((violation, index) => (
                <li key={index}>
                  {violation.line_index != null && `${lineNumber(violation.line_index)}, `}
                  {guardrailLabel(violation.guardrail)}: {violation.message}
                </li>
              ))}
            </ul>
          }
        />
      )}
    </div>
  )
}
