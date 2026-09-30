import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { json, mockApi, renderWithProviders } from '../test/render'
import { DashboardPage } from './DashboardPage'

const counts = {
  verdicts_total: 10, verdicts_trusted: 7, review_items_resolved: 4, review_items_corrected: 3,
  requests_compared: 5, requests_duplicate: 1, flags_by_dimension: { graph_completion: 2, price_provenance: 1 },
}

const graphStats = () => json({ node_counts: { SKU: 650 }, edge_counts: { REQUIRES: 91 } })

describe('DashboardPage', () => {
  it('shows each rate with the count it was computed from', async () => {
    mockApi({
      'GET /v1/graph/stats': graphStats,
      'GET /v1/metrics': () => json({ auto_send_rate: 0.7, correction_rate: 0.75, duplicate_rate: 0.2, counts }),
    })

    renderWithProviders(<DashboardPage />)

    expect(await screen.findByText('70.0%')).toBeInTheDocument()
    expect(screen.getByText('7 of 10 judge verdicts were trusted')).toBeInTheDocument()
    expect(screen.getByText('75.0%')).toBeInTheDocument()
    expect(screen.getByText('3 of 4 resolved review items were corrected')).toBeInTheDocument()
    expect(screen.getByText('20.0%')).toBeInTheDocument()
    expect(screen.getByText('1 of 5 compared requests are duplicates')).toBeInTheDocument()
  })

  it('says "no data yet" for a rate with nothing behind it, never 0%', async () => {
    mockApi({
      'GET /v1/graph/stats': graphStats,
      'GET /v1/metrics': () =>
        json({
          auto_send_rate: null, correction_rate: null, duplicate_rate: null,
          counts: {
            verdicts_total: 0, verdicts_trusted: 0, review_items_resolved: 0, review_items_corrected: 0,
            requests_compared: 0, requests_duplicate: 0, flags_by_dimension: {},
          },
        }),
    })

    renderWithProviders(<DashboardPage />)

    expect(await screen.findAllByText('no data yet')).toHaveLength(3)
    expect(screen.queryByText('0.0%')).not.toBeInTheDocument()
  })

  it('shows the three charts, and an empty state when nothing has been flagged', async () => {
    mockApi({
      'GET /v1/graph/stats': graphStats,
      'GET /v1/metrics': () =>
        json({ auto_send_rate: null, correction_rate: null, duplicate_rate: null, counts: { ...counts, flags_by_dimension: {} } }),
    })

    renderWithProviders(<DashboardPage />)

    expect(await screen.findByText('Flags by dimension')).toBeInTheDocument()
    expect(await screen.findByText('Graph nodes by type')).toBeInTheDocument()
    expect(await screen.findByText('Graph edges by type')).toBeInTheDocument()
    expect(screen.getByText('No flags yet')).toBeInTheDocument()
  })
})
