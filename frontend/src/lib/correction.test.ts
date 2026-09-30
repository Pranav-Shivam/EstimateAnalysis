import { describe, expect, it } from 'vitest'
import {
  buildCorrection,
  correctableSkuIds,
  flaggedCategories,
  flaggedContractId,
  flaggedRows,
  flaggedSkuIds,
  type CorrectionDraft,
} from './correction'

const blank: CorrectionDraft = { skuId: 'SKU-1', price: '', requiredSkuId: '', contractId: '', category: '' }

describe('buildCorrection for price_provenance', () => {
  it('accepts a positive decimal price', () => {
    expect(buildCorrection('price_provenance', { ...blank, price: '42.50' })).toEqual({
      ok: true,
      correction: { sku_id: 'SKU-1', corrected_unit_price: 42.5 },
    })
  })

  it.each(['', '  ', '0', '-3', 'NaN', 'Infinity', '1e3', '0x10', '4,5', 'abc'])(
    'rejects %j before any network call',
    (price) => {
      const result = buildCorrection('price_provenance', { ...blank, price })
      expect(result.ok).toBe(false)
    },
  )
})

describe('buildCorrection for graph_completion', () => {
  it('accepts a different required SKU and trims it', () => {
    expect(buildCorrection('graph_completion', { ...blank, requiredSkuId: ' SKU-2 ' })).toEqual({
      ok: true,
      correction: { sku_id: 'SKU-1', required_sku_id: 'SKU-2' },
    })
  })

  it('rejects an empty required SKU', () => {
    expect(buildCorrection('graph_completion', blank)).toEqual({
      ok: false,
      error: 'Enter the SKU id of the required part.',
    })
  })

  it('rejects a SKU that requires itself', () => {
    expect(buildCorrection('graph_completion', { ...blank, requiredSkuId: 'SKU-1' })).toEqual({
      ok: false,
      error: 'A SKU cannot require itself.',
    })
  })
})

describe('buildCorrection for contract_discount', () => {
  it('accepts a contract and category', () => {
    expect(
      buildCorrection('contract_discount', { ...blank, contractId: 'CTR-1', category: 'Cat-A' }),
    ).toEqual({ ok: true, correction: { contract_id: 'CTR-1', category: 'Cat-A' } })
  })

  it('rejects a missing category', () => {
    expect(buildCorrection('contract_discount', { ...blank, contractId: 'CTR-1' }).ok).toBe(false)
  })
})

it('refuses a dimension it has no form for', () => {
  expect(buildCorrection('guardrail', blank)).toEqual({
    ok: false,
    error: 'Dimension guardrail cannot be corrected here.',
  })
})

describe('flagged evidence helpers', () => {
  const evidence = {
    dimension: 'contract_discount',
    lines: [
      { line_index: 0, sku_id: 'SKU-1', contract_id: 'CTR-1' },
      { line_index: 1, sku_id: 'SKU-2', contract_id: 'CTR-1' },
      { line_index: 2, sku_id: 'SKU-1', contract_id: 'CTR-1' },
    ],
  }

  it('reads the flagged rows, SKUs, contract and categories', () => {
    const rows = flaggedRows(evidence)
    expect(flaggedSkuIds(rows)).toEqual(['SKU-1', 'SKU-2'])
    expect(flaggedContractId(rows)).toBe('CTR-1')
    expect(
      flaggedCategories(rows, { 'SKU-1': { category: 'Cat-A' }, 'SKU-2': { category: 'Cat-A' } }),
    ).toEqual(['Cat-A'])
  })

  it('returns empty results for evidence with no lines', () => {
    expect(flaggedRows({})).toEqual([])
    expect(flaggedContractId([])).toBeNull()
  })
})

describe('correctableSkuIds', () => {
  it('offers only the predicted-price lines for a price correction, never a list-priced one', () => {
    const rows = [
      { sku_id: 'SKU-LISTED', price_source: 'list' },
      { sku_id: 'SKU-GUESS', price_source: 'predicted' },
    ]
    expect(correctableSkuIds('price_provenance', rows)).toEqual(['SKU-GUESS'])
  })

  it('offers the lines with no recorded required part for a graph correction', () => {
    const rows = [
      { sku_id: 'SKU-A', required_part_ids: ['SKU-B'] },
      { sku_id: 'SKU-C', required_part_ids: [] },
    ]
    expect(correctableSkuIds('graph_completion', rows)).toEqual(['SKU-C'])
  })

  it('falls back to every flagged SKU when no row matches', () => {
    expect(correctableSkuIds('price_provenance', [{ sku_id: 'SKU-A', price_source: 'list' }])).toEqual(['SKU-A'])
  })
})
