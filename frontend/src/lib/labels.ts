// Human labels for the machine values the API returns. A value with no entry is shown as sent, so a new backend
// value degrades to its raw name instead of disappearing.

export interface Label {
  text: string
  /** An antd Tag preset color; omitted for neutral. */
  color?: string
}

const DIMENSIONS: Record<string, string> = {
  price_provenance: 'Price source',
  contract_discount: 'Contract discount',
  graph_completion: 'Graph completeness',
  guardrail: 'Guardrail',
}

const ESTIMATE_STATUS: Record<string, Label> = {
  ready: { text: 'Draft ready', color: 'green' },
  needs_review: { text: 'Draft needs review', color: 'volcano' },
}

const PRICE_SOURCE: Record<string, Label> = {
  list: { text: 'List price', color: 'green' },
  predicted: { text: 'Predicted', color: 'orange' },
}

const DEDUPE_VERDICTS: Record<string, Label> = {
  DUPLICATE_OF: { text: 'Duplicate', color: 'red' },
  REVISION_OF: { text: 'Revision', color: 'gold' },
  DISTINCT: { text: 'Distinct' },
}

const DEDUPE_SIGNALS: Record<string, string> = {
  same_customer: 'Same customer',
  same_site: 'Same site',
  same_contract: 'Same contract',
  identical_sku_set: 'Same item list',
  superset_relation: 'Adds items to the earlier list',
}

const GUARDRAILS: Record<string, string> = {
  required_fields: 'Required fields',
  customer_identity: 'Customer identity',
  price_provenance: 'Price source',
  contract_discount: 'Contract discount',
  graph_integrity: 'Graph integrity',
}

const ADJUSTMENTS: Record<string, string> = {
  substituted: 'Substituted',
  added_required: 'Added required part',
  discount_removed: 'Discount removed',
  quantity_assumed: 'Quantity assumed',
}

const REVIEW_STATUS: Record<string, Label> = {
  open: { text: 'Open', color: 'gold' },
  approved: { text: 'Approved', color: 'green' },
  corrected: { text: 'Corrected', color: 'blue' },
  consolidated: { text: 'Applied', color: 'green' },
}

const CORRECTION_FIELDS: Record<string, string> = {
  sku_id: 'SKU',
  corrected_unit_price: 'Corrected unit price',
  required_sku_id: 'Required part',
  contract_id: 'Contract',
  category: 'Category',
}

const lookup = (table: Record<string, Label>, value: string): Label => table[value] ?? { text: value }

export const dimensionLabel = (dimension: string): string => DIMENSIONS[dimension] ?? dimension
export const estimateStatus = (status: string): Label => lookup(ESTIMATE_STATUS, status)
export const priceSource = (source: string): Label => lookup(PRICE_SOURCE, source)
export const dedupeVerdict = (verdict: string): Label => lookup(DEDUPE_VERDICTS, verdict)
export const dedupeSignal = (signal: string): string => DEDUPE_SIGNALS[signal] ?? signal
export const guardrailLabel = (guardrail: string): string => GUARDRAILS[guardrail] ?? guardrail
export const adjustmentLabel = (kind: string): string => ADJUSTMENTS[kind] ?? kind
export const reviewStatus = (status: string): Label => lookup(REVIEW_STATUS, status)
export const correctionField = (field: string): string => CORRECTION_FIELDS[field] ?? field

/** Line indexes are zero-based in the API; reviewers count from one. */
export const lineNumber = (index: number): string => `Line ${index + 1}`
