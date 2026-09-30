import { Alert, Button, Input, Select } from 'antd'
import { useState } from 'react'
import type { QuoteReviewItem, QuoteSkuInfo } from '../api/types'
import {
  buildCorrection,
  correctableSkuIds,
  flaggedCategories,
  flaggedContractId,
  flaggedRows,
  type CorrectionDraft,
} from '../lib/correction'

interface Props {
  item: QuoteReviewItem
  skus: Record<string, QuoteSkuInfo>
  busy: boolean
  onSubmit: (correction: Record<string, string | number>) => void
  onCancel: () => void
}

export function CorrectionForm({ item, skus, busy, onSubmit, onCancel }: Props) {
  const rows = flaggedRows(item.evidence)
  const skuIds = correctableSkuIds(item.dimension, rows)
  const categories = flaggedCategories(rows, skus)
  const [draft, setDraft] = useState<CorrectionDraft>({
    skuId: skuIds[0] ?? '',
    price: '',
    requiredSkuId: '',
    contractId: flaggedContractId(rows) ?? '',
    category: categories.length === 1 ? categories[0] : '',
  })
  const [error, setError] = useState<string | null>(null)
  const update = (patch: Partial<CorrectionDraft>) => setDraft((current) => ({ ...current, ...patch }))

  function submit() {
    const result = buildCorrection(item.dimension, draft)
    if (!result.ok) {
      setError(result.error)
      return
    }
    setError(null)
    onSubmit(result.correction)
  }

  return (
    <div className="flex flex-col gap-3">
      {(item.dimension === 'price_provenance' || item.dimension === 'graph_completion') &&
        (skuIds.length > 1 ? (
          <Select
            aria-label="SKU"
            value={draft.skuId}
            onChange={(skuId) => update({ skuId })}
            options={skuIds.map((id) => ({ value: id, label: skus[id] ? `${id} (${skus[id].name})` : id }))}
          />
        ) : (
          <p>SKU: {draft.skuId}</p>
        ))}

      {item.dimension === 'price_provenance' && (
        <div className="flex flex-col gap-1">
          <label htmlFor="corrected-price">Correct unit price (USD)</label>
          <Input
            id="corrected-price"
            inputMode="decimal"
            value={draft.price}
            onChange={(event) => update({ price: event.target.value })}
          />
        </div>
      )}

      {item.dimension === 'graph_completion' && (
        <div className="flex flex-col gap-1">
          <label htmlFor="required-sku">Required part (SKU id)</label>
          <Input
            id="required-sku"
            value={draft.requiredSkuId}
            onChange={(event) => update({ requiredSkuId: event.target.value })}
          />
        </div>
      )}

      {item.dimension === 'contract_discount' &&
        (categories.length > 1 ? (
          <Select
            aria-label="Category"
            value={draft.category || undefined}
            onChange={(category) => update({ category })}
            options={categories.map((category) => ({ value: category, label: category }))}
          />
        ) : (
          <p>Confirm that {draft.contractId} covers {draft.category}.</p>
        ))}

      {error && <Alert type="error" title={error} />}
      <div className="flex gap-3">
        <Button type="primary" loading={busy} onClick={submit}>Save correction</Button>
        <Button onClick={onCancel} disabled={busy}>Cancel</Button>
      </div>
    </div>
  )
}
