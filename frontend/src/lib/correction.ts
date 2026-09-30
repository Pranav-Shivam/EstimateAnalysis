export type EvidenceRow = Record<string, unknown>

export interface CorrectionDraft {
  skuId: string
  price: string
  requiredSkuId: string
  contractId: string
  category: string
}

export type CorrectionResult =
  | { ok: true; correction: Record<string, string | number> }
  | { ok: false; error: string }

// A plain decimal only: Number() alone would also accept '1e3', '0x10' and 'Infinity'.
const DECIMAL_PRICE = /^\d+(\.\d+)?$/

/** The client-side mirror of `CORRECTION_FIELDS` and `validate_correction` in backend/app/judge/schemas.py. It only
 * saves a round trip; the backend still validates and its message is shown if it disagrees. */
export function buildCorrection(dimension: string, draft: CorrectionDraft): CorrectionResult {
  switch (dimension) {
    case 'price_provenance': {
      const text = draft.price.trim()
      const price = Number(text)
      if (!DECIMAL_PRICE.test(text) || price <= 0) return { ok: false, error: 'Enter a price above zero.' }
      return { ok: true, correction: { sku_id: draft.skuId, corrected_unit_price: price } }
    }
    case 'graph_completion': {
      const required = draft.requiredSkuId.trim()
      if (required === '') return { ok: false, error: 'Enter the SKU id of the required part.' }
      if (required === draft.skuId) return { ok: false, error: 'A SKU cannot require itself.' }
      return { ok: true, correction: { sku_id: draft.skuId, required_sku_id: required } }
    }
    case 'contract_discount': {
      if (draft.contractId === '' || draft.category === '') {
        return { ok: false, error: 'Pick the contract category to confirm.' }
      }
      return { ok: true, correction: { contract_id: draft.contractId, category: draft.category } }
    }
    default:
      return { ok: false, error: `Dimension ${dimension} cannot be corrected here.` }
  }
}

export function flaggedRows(evidence: Record<string, unknown>): EvidenceRow[] {
  const lines = evidence.lines
  return Array.isArray(lines) ? (lines as EvidenceRow[]) : []
}

export function flaggedSkuIds(rows: EvidenceRow[]): string[] {
  const ids = rows.map((row) => row.sku_id).filter((id): id is string => typeof id === 'string')
  return [...new Set(ids)]
}

export function flaggedContractId(rows: EvidenceRow[]): string | null {
  const row = rows.find((candidate) => typeof candidate.contract_id === 'string')
  return row ? (row.contract_id as string) : null
}

export function flaggedCategories(rows: EvidenceRow[], skus: Record<string, { category: string }>): string[] {
  const categories = flaggedSkuIds(rows)
    .map((id) => skus[id]?.category)
    .filter((category): category is string => category !== undefined)
  return [...new Set(categories)]
}

/** The SKUs a correction can target. `lines` holds every line of the estimate, so the form narrows it to the
 * lines the judge doubted: predicted prices for a price fix, lines with no recorded required part for a graph fix.
 * A reviewer must not be able to overwrite a real list price by picking the wrong line. */
export function correctableSkuIds(dimension: string, rows: EvidenceRow[]): string[] {
  const doubted =
    dimension === 'price_provenance'
      ? rows.filter((row) => row.price_source === 'predicted')
      : dimension === 'graph_completion'
        ? rows.filter((row) => Array.isArray(row.required_part_ids) && row.required_part_ids.length === 0)
        : rows
  return flaggedSkuIds(doubted.length > 0 ? doubted : rows)
}
