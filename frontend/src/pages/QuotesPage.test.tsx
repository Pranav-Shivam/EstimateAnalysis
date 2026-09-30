import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { json, mockApi, renderWithProviders } from '../test/render'
import { QuotesPage } from './QuotesPage'

const base = {
  quote_request_id: 'q1', case_id: 'sc-0001', customer_id: 'CUST-1', created_at: '2030-01-01T12:00:00',
  estimate_count: 2, latest_estimate_status: 'ready', latest_trusted: true, open_review_items: 0, is_duplicate: false,
}

describe('QuotesPage', () => {
  it('shows each quote with its latest estimate, judge outcome and duplicate flag', async () => {
    mockApi({
      'GET /v1/quotes': () =>
        json([
          base,
          { ...base, quote_request_id: 'q2', case_id: 'sc-0002', latest_trusted: null, is_duplicate: true },
          { ...base, quote_request_id: 'q3', case_id: 'sc-0003', latest_estimate_status: null, latest_trusted: false, estimate_count: 0 },
        ]),
    })

    renderWithProviders(<QuotesPage />)

    expect(await screen.findByRole('link', { name: 'sc-0001' })).toHaveAttribute('href', '/quotes/q1')
    expect(screen.getByText('Auto-send')).toBeInTheDocument()
    expect(screen.getByText('Not judged')).toBeInTheDocument()
    // One is the column header, the other the tag on the duplicate row.
    expect(screen.getAllByText('Duplicate')).toHaveLength(2)
    expect(screen.getByText('No estimate')).toBeInTheDocument()
  })
})
