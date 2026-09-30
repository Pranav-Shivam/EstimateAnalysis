import { Descriptions, Tag } from 'antd'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import type { QuoteSkuInfo } from '../api/types'
import type { EvidenceRow } from '../lib/correction'
import { money } from '../lib/format'
import { priceSource } from '../lib/labels'
import { LabelTag } from './LabelTag'

interface Props {
  dimension: string
  rows: EvidenceRow[]
  skus: Record<string, QuoteSkuInfo>
}

// The judge stores these row shapes (see build_evidence in backend/app/judge/evidence.py), so a field can be null
// or absent and each reader below tolerates both.
const asText = (value: unknown): string => (typeof value === 'string' ? value : 'Not recorded')
const asNumber = (value: unknown): number | null => (typeof value === 'number' ? value : null)
const asList = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === 'string') : []
const yesNo = (value: unknown): string => (value === true ? 'yes' : value === false ? 'no' : 'not applicable')

function skuLabel(id: unknown, skus: Record<string, QuoteSkuInfo>): string {
  if (typeof id !== 'string') return 'unknown SKU'
  const sku = skus[id]
  return sku ? `${id} (${sku.name})` : id
}

function skuTitle(id: unknown, skus: Record<string, QuoteSkuInfo>): ReactNode {
  if (typeof id !== 'string') return skuLabel(id, skus)
  return (
    <>
      {skuLabel(id, skus)} <Link to={`/graph?node=${encodeURIComponent(id)}`} className="ml-2 text-sm font-normal">View in graph</Link>
    </>
  )
}

function tags(ids: string[], color?: string): ReactNode {
  return ids.length === 0 ? 'None' : ids.map((id) => <Tag key={id} color={color}>{id}</Tag>)
}

function itemsFor(dimension: string, row: EvidenceRow) {
  switch (dimension) {
    case 'price_provenance':
      // A list-priced line has no prediction and a predicted line has no list price; only what exists is shown.
      return [
        {
          key: 'source',
          label: 'Price source',
          children: <LabelTag label={priceSource(asText(row.price_source))} />,
        },
        { key: 'list', label: 'List price', value: asNumber(row.list_price), children: money(asNumber(row.list_price)) },
        {
          key: 'predicted', label: 'Predicted price', value: asNumber(row.predicted_price),
          children: money(asNumber(row.predicted_price)),
        },
        { key: 'peers', label: 'Peers', value: asNumber(row.peer_count), children: asNumber(row.peer_count) },
        {
          key: 'range',
          label: 'Peer range',
          value: asNumber(row.low),
          children: `${money(asNumber(row.low))} to ${money(asNumber(row.high))}`,
        },
      ]
        .filter((item) => !('value' in item) || item.value !== null)
        .map(({ key, label, children }) => ({ key, label, children }))
    case 'contract_discount':
      return [
        { key: 'contract', label: 'Contract', children: asText(row.contract_id) },
        { key: 'discount', label: 'Discount claimed', children: `${asNumber(row.discount_pct) ?? 0}%` },
        { key: 'covered', label: 'Category covered', children: yesNo(row.covered) },
        { key: 'active', label: 'Active on the quote date', children: yesNo(row.active_on_as_of) },
        { key: 'expiry', label: 'Days to expiry', children: asNumber(row.days_to_expiry) ?? 'not applicable' },
      ]
    case 'graph_completion':
      return [
        { key: 'discontinued', label: 'Discontinued', children: yesNo(row.discontinued) },
        { key: 'live', label: 'Live replacement', children: asText(row.live_sku_id) },
        { key: 'required', label: 'Required parts', children: tags(asList(row.required_part_ids)) },
        { key: 'missing', label: 'Missing from the draft', children: tags(asList(row.missing_required_part_ids), 'red') },
      ]
    default:
      return []
  }
}

export function EvidencePanel({ dimension, rows, skus }: Props) {
  if (rows.length === 0) return <p className="m-0 text-slate-500">No line evidence was stored for this fact.</p>
  return (
    <div className="flex flex-col gap-4">
      {rows.map((row) => (
        <Descriptions
          key={`${asText(row.line_index)}-${asText(row.sku_id)}`}
          size="small"
          column={{ xs: 1, sm: 2 }}
          className="[&_.ant-descriptions-title]:whitespace-normal"
          title={skuTitle(row.sku_id, skus)}
          items={itemsFor(dimension, row)}
        />
      ))}
    </div>
  )
}
