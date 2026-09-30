import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { ReviewItem } from '../api/types'
import { json, mockApi, renderWithProviders } from '../test/render'
import { QueuePage } from './QueuePage'

function queueItem(overrides: Partial<ReviewItem> = {}): ReviewItem {
  return {
    id: 'item-1', estimate_id: 'est-1', quote_request_id: 'q1', dimension: 'price_provenance',
    fact: 'SKU-1: the price is a peer-median prediction', evidence: {}, line_index: 0, status: 'open',
    outcome: null, correction: null, resolved_at: null, created_at: '2030-01-01T12:00:00', ...overrides,
  }
}

describe('QueuePage', () => {
  it('lists open flags with the fact to check and a link to the quote', async () => {
    mockApi({ 'GET /v1/review': () => json([queueItem()]) })

    renderWithProviders(<QueuePage />)

    expect(await screen.findByText('SKU-1: the price is a peer-median prediction')).toBeInTheDocument()
    expect(screen.getByText('Price source')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open quote' })).toHaveAttribute('href', '/quotes/q1')
  })

  it('says the queue is clear when nothing is open', async () => {
    mockApi({ 'GET /v1/review': () => json([]) })

    renderWithProviders(<QueuePage />)

    expect(await screen.findByText('The queue is clear.')).toBeInTheDocument()
  })

  it('asks for resolved items when the filter changes and shows their outcome', async () => {
    mockApi({
      'GET /v1/review': (request) =>
        json(
          new URL(request.url).searchParams.get('status') === 'resolved'
            ? [queueItem({ id: 'item-2', status: 'consolidated', outcome: 'corrected', fact: 'an old fact' })]
            : [],
        ),
    })

    renderWithProviders(<QueuePage />)
    await userEvent.click(await screen.findByText('Resolved'))

    expect(await screen.findByText('an old fact')).toBeInTheDocument()
    expect(screen.getByText('corrected')).toBeInTheDocument()
  })

  it('shows the backend detail when the request fails', async () => {
    mockApi({ 'GET /v1/review': () => json({ detail: 'database unavailable' }, 500) })

    renderWithProviders(<QueuePage />)

    expect(await screen.findByText('database unavailable')).toBeInTheDocument()
  })
})
