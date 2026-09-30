import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { skus } from '../test/fixtures'
import { renderWithProviders } from '../test/render'
import { EvidencePanel } from './EvidencePanel'

describe('EvidencePanel', () => {
  it('shows a predicted price with its peer basis', () => {
    renderWithProviders(
      <EvidencePanel
        dimension="price_provenance"
        skus={skus}
        rows={[
          { line_index: 0, sku_id: 'SKU-1', price_source: 'predicted', list_price: null, predicted_price: 20, peer_count: 3, low: 10, high: 30 },
        ]}
      />,
    )

    expect(screen.getByText('SKU-1 (Widget)')).toBeInTheDocument()
    expect(screen.getByText('Predicted')).toBeInTheDocument()
    expect(screen.getByText('$20.00')).toBeInTheDocument()
    expect(screen.getByText('$10.00 to $30.00')).toBeInTheDocument()
  })

  it('shows contract coverage as not applicable when no discount was claimed', () => {
    renderWithProviders(
      <EvidencePanel
        dimension="contract_discount"
        skus={skus}
        rows={[
          { line_index: 0, sku_id: 'SKU-1', discount_pct: 0, contract_id: 'CTR-1', covered: null, active_on_as_of: null, days_to_expiry: null },
        ]}
      />,
    )

    expect(screen.getByText('CTR-1')).toBeInTheDocument()
    expect(screen.getAllByText('not applicable').length).toBeGreaterThan(0)
  })

  it('lists required parts and marks the missing ones', () => {
    renderWithProviders(
      <EvidencePanel
        dimension="graph_completion"
        skus={skus}
        rows={[
          { line_index: 0, sku_id: 'SKU-1', discontinued: false, live_sku_id: 'SKU-1', required_part_ids: ['SKU-2'], missing_required_part_ids: ['SKU-2'] },
        ]}
      />,
    )

    expect(screen.getByText('Missing from the draft')).toBeInTheDocument()
    expect(screen.getAllByText('SKU-2').length).toBe(2)
  })

  it('says so when no line evidence was stored', () => {
    renderWithProviders(<EvidencePanel dimension="price_provenance" skus={skus} rows={[]} />)

    expect(screen.getByText('No line evidence was stored for this fact.')).toBeInTheDocument()
  })
})

describe('EvidencePanel graph link', () => {
  it('links each line to the graph explorer at its SKU', () => {
    renderWithProviders(
      <EvidencePanel
        dimension="graph_completion"
        skus={skus}
        rows={[{ line_index: 0, sku_id: 'SKU-1', discontinued: false, live_sku_id: 'SKU-1', required_part_ids: [], missing_required_part_ids: [] }]}
      />,
    )

    expect(screen.getByRole('link', { name: 'View in graph' })).toHaveAttribute('href', '/graph?node=SKU-1')
  })
})
