import { Empty, Table, Tag } from 'antd'
import type { TableProps } from 'antd'
import type { DraftLine, QuoteEstimate, QuoteSkuInfo } from '../api/types'
import { money } from '../lib/format'

interface Props {
  estimate: QuoteEstimate
  skus: Record<string, QuoteSkuInfo>
}

function lineTotal(line: DraftLine): number {
  return (line.quantity ?? 0) * (line.unit_price ?? 0) * (1 - (line.discount_pct ?? 0) / 100)
}

export function EstimateLinesTable({ estimate, skus }: Props) {
  const { draft, totals } = estimate
  if (!draft) return <Empty description={estimate.reason ?? 'No draft was produced for this estimate.'} />

  const columns: TableProps<DraftLine>['columns'] = [
    {
      title: 'SKU',
      render: (_, line) => (line.sku_id && skus[line.sku_id] ? `${line.sku_id} (${skus[line.sku_id].name})` : line.sku_id),
    },
    { title: 'Qty', dataIndex: 'quantity' },
    { title: 'Unit price', render: (_, line) => money(line.unit_price) },
    {
      title: 'Source',
      render: (_, line) => <Tag color={line.price_source === 'predicted' ? 'orange' : 'green'}>{line.price_source}</Tag>,
    },
    { title: 'Discount', render: (_, line) => `${line.discount_pct ?? 0}%` },
    { title: 'Line total', render: (_, line) => money(lineTotal(line)) },
  ]

  return (
    <div className="flex flex-col gap-4">
      <Table<DraftLine>
        size="small"
        pagination={false}
        columns={columns}
        dataSource={draft.lines}
        rowKey={(line, index) => `${line.sku_id}-${index}`}
      />
      {totals && (
        <dl className="flex justify-end gap-8">
          <div><dt className="text-gray-500">List total</dt><dd>{money(totals.list_total)}</dd></div>
          <div><dt className="text-gray-500">Discount</dt><dd>{money(totals.discount_total)}</dd></div>
          <div><dt className="text-gray-500">Net total</dt><dd className="font-semibold">{money(totals.net_total)}</dd></div>
        </dl>
      )}
      {(draft.adjustments ?? []).length > 0 && (
        <ul className="list-disc pl-5">
          {(draft.adjustments ?? []).map((adjustment, index) => (
            <li key={index}>{adjustment.kind}: {adjustment.detail}</li>
          ))}
        </ul>
      )}
      {estimate.violations.length > 0 && (
        <ul className="list-disc pl-5 text-red-700">
          {estimate.violations.map((violation, index) => (
            <li key={index}>{violation.guardrail}: {violation.message}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
