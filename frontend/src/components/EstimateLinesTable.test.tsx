import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { estimate, skus } from '../test/fixtures'
import { EstimateLinesTable } from './EstimateLinesTable'

describe('EstimateLinesTable', () => {
  it('shows the reason instead of a table when no draft was produced', () => {
    render(
      <EstimateLinesTable
        estimate={estimate({ draft: null, totals: null, reason: 'guardrail violations persisted after 3 retries' })}
        skus={skus}
      />,
    )

    expect(screen.getByText('guardrail violations persisted after 3 retries')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('shows each line with its price source, line total and the totals', () => {
    render(<EstimateLinesTable estimate={estimate()} skus={skus} />)

    expect(screen.getByText('SKU-1 (Widget)')).toBeInTheDocument()
    expect(screen.getByText('predicted')).toBeInTheDocument()
    expect(screen.getAllByText('$40.00').length).toBeGreaterThan(0)
    expect(screen.getByText('Net total')).toBeInTheDocument()
  })

  it('lists adjustments and guardrail violations', () => {
    const withNotes = estimate()
    withNotes.draft!.adjustments = [{ kind: 'substituted', sku_id: 'SKU-2', detail: 'SKU-9 is discontinued' }]
    withNotes.violations = [{ guardrail: 'price_provenance', line_index: 0, message: 'unit_price does not match' }]

    render(<EstimateLinesTable estimate={withNotes} skus={skus} />)

    expect(screen.getByText(/SKU-9 is discontinued/)).toBeInTheDocument()
    expect(screen.getByText(/unit_price does not match/)).toBeInTheDocument()
  })
})
