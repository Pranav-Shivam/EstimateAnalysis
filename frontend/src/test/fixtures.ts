import type { QuoteDetail, QuoteEstimate, QuoteReviewItem, QuoteSkuInfo } from '../api/types'

export const skus: Record<string, QuoteSkuInfo> = {
  'SKU-1': { name: 'Widget', category: 'Cat-A', discontinued: false },
  'SKU-2': { name: 'Widget Mount', category: 'Cat-B', discontinued: false },
}

export function reviewItem(overrides: Partial<QuoteReviewItem> = {}): QuoteReviewItem {
  return {
    id: 'item-1',
    dimension: 'price_provenance',
    fact: 'SKU-1: the price is a peer-median prediction, not a reference list price',
    evidence: {
      dimension: 'price_provenance',
      lines: [
        {
          line_index: 0, sku_id: 'SKU-1', price_source: 'predicted', list_price: null, predicted_price: 20,
          peer_count: 3, low: 10, high: 30,
        },
      ],
    },
    line_index: 0,
    status: 'open',
    outcome: null,
    correction: null,
    resolved_at: null,
    created_at: '2030-01-01T12:00:00',
    ...overrides,
  }
}

export function estimate(overrides: Partial<QuoteEstimate> = {}): QuoteEstimate {
  return {
    estimate_id: 'est-1',
    status: 'ready',
    draft: {
      customer_id: 'CUST-1',
      contract_id: null,
      lines: [
        { sku_id: 'SKU-1', quantity: 2, unit_price: 20, price_source: 'predicted', discount_pct: 0 },
      ],
      adjustments: [],
      flags: [],
    },
    totals: { list_total: 40, discount_total: 0, net_total: 40 },
    violations: [],
    iterations: 1,
    reason: null,
    created_at: '2030-01-01T12:00:00',
    judge_verdict: {
      id: 'verdict-1',
      model: 'test-judge',
      dimensions: [
        { name: 'price_provenance', score: 0.2, rationale: 'price is a prediction', evidence: [] },
        { name: 'contract_discount', score: 0.95, rationale: 'no discount claimed', evidence: [] },
        { name: 'graph_completion', score: 0.9, rationale: 'live SKUs', evidence: [] },
      ],
      overall_confidence: 0.2,
      flagged_dimension: 'price_provenance',
      trusted: false,
      created_at: '2030-01-01T12:01:00',
    },
    review_items: [reviewItem()],
    ...overrides,
  }
}

export function quoteDetail(overrides: Partial<QuoteDetail> = {}): QuoteDetail {
  return {
    quote_request_id: 'q1',
    case_id: 'sc-0001',
    customer_id: 'CUST-1',
    site_id: null,
    contract_id: null,
    raw_email_text: 'Hi, please quote two Widgets.',
    parsed_json: {},
    created_at: '2030-01-01T11:00:00',
    dedupe_verdicts: [],
    estimates: [estimate()],
    skus,
    ...overrides,
  }
}
