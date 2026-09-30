import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'
import { estimate, quoteDetail, reviewItem } from '../test/fixtures'
import { json, mockApi, renderWithProviders } from '../test/render'
import { QuoteDetailPage } from './QuoteDetailPage'

function renderDetail() {
  return renderWithProviders(
    <Routes>
      <Route path="/quotes/:id" element={<QuoteDetailPage />} />
    </Routes>,
    { route: '/quotes/q1' },
  )
}

describe('QuoteDetailPage', () => {
  it('shows the email, the dedupe verdicts and the flagged fact of a single estimate', async () => {
    mockApi({
      'GET /v1/quotes/q1': () =>
        json(quoteDetail({
          dedupe_verdicts: [{
            candidate_quote_request_id: 'q0', verdict: 'DUPLICATE_OF', content_jaccard: 1, style_jaccard: 0.9,
            signals_fired: ['identical_sku_set'], created_at: '2030-01-01T11:30:00',
          }],
        })),
    })

    renderDetail()

    expect(await screen.findByText('Hi, please quote two Widgets.')).toBeInTheDocument()
    expect(screen.getByText('DUPLICATE_OF')).toBeInTheDocument()
    expect(screen.getByText(/the price is a peer-median prediction/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve as is' })).toBeInTheDocument()
  })

  it('shows a corrected quote as two estimates: the clean latest one first, the flagged earlier one behind a tab', async () => {
    const earlier = estimate({
      estimate_id: 'est-1',
      review_items: [reviewItem({ status: 'consolidated', outcome: 'corrected', correction: { sku_id: 'SKU-1', corrected_unit_price: 42.5 } })],
    })
    const latest = estimate({
      estimate_id: 'est-2',
      created_at: '2030-01-02T12:00:00',
      draft: { customer_id: 'CUST-1', contract_id: null, lines: [{ sku_id: 'SKU-1', quantity: 2, unit_price: 42.5, price_source: 'list', discount_pct: 0 }], adjustments: [], flags: [] },
      totals: { list_total: 85, discount_total: 0, net_total: 85 },
      judge_verdict: { ...estimate().judge_verdict!, trusted: true, overall_confidence: 0.9 },
      review_items: [],
    })
    mockApi({ 'GET /v1/quotes/q1': () => json(quoteDetail({ estimates: [latest, earlier] })) })

    renderDetail()

    expect(await screen.findByRole('tab', { name: 'Latest estimate' })).toBeInTheDocument()
    expect(screen.getByText('Auto-sent: the judge trusted this estimate, so no reviewer action was needed.')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('tab', { name: 'Earlier estimate 1' }))

    expect(await screen.findByText('Applied to the reference data.')).toBeInTheDocument()
  })

  it('shows a guardrail-blocked estimate with its reason and no actions', async () => {
    const blocked = estimate({
      status: 'needs_review', draft: null, totals: null, reason: 'guardrail violations persisted after 3 retries',
      judge_verdict: { ...estimate().judge_verdict!, dimensions: [], model: 'none (guardrail fast path)', trusted: false },
      review_items: [reviewItem({
        dimension: 'guardrail', fact: 'guardrail violations persisted after 3 retries',
        evidence: { violations: [{ guardrail: 'required_fields', line_index: 0, message: 'line quantity must be a whole number above 0' }] },
      })],
    })
    mockApi({ 'GET /v1/quotes/q1': () => json(quoteDetail({ estimates: [blocked] })) })

    renderDetail()

    expect(await screen.findByText('Guardrail-blocked drafts cannot be resolved from this screen yet.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve as is' })).not.toBeInTheDocument()
  })

  it('says so when no estimate has run yet', async () => {
    mockApi({ 'GET /v1/quotes/q1': () => json(quoteDetail({ estimates: [] })) })

    renderDetail()

    expect(await screen.findByText('No estimate has been run for this quote yet.')).toBeInTheDocument()
  })

  it('shows the backend detail for an unknown quote', async () => {
    mockApi({ 'GET /v1/quotes/q1': () => json({ detail: 'quote request q1 not found' }, 404) })

    renderDetail()

    expect(await screen.findByText('quote request q1 not found')).toBeInTheDocument()
  })
})
