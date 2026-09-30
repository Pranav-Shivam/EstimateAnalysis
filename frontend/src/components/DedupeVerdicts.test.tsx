import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '../test/render'
import { DedupeVerdicts } from './DedupeVerdicts'

describe('DedupeVerdicts', () => {
  it('says so when nothing similar was found', () => {
    renderWithProviders(<DedupeVerdicts verdicts={[]} />)

    expect(screen.getByText('No similar requests were found for this customer.')).toBeInTheDocument()
  })

  it('links each candidate and shows its verdict and similarity', () => {
    renderWithProviders(
      <DedupeVerdicts
        verdicts={[
          {
            candidate_quote_request_id: 'q-other', verdict: 'DUPLICATE_OF', content_jaccard: 1, style_jaccard: 0.5,
            signals_fired: ['identical_sku_set'], created_at: '2030-01-01T12:00:00',
          },
        ]}
      />,
    )

    expect(screen.getByRole('link', { name: 'Open earlier request' })).toHaveAttribute('href', '/quotes/q-other')
    expect(screen.getByText('DUPLICATE_OF')).toBeInTheDocument()
    expect(screen.getByText('100.0%')).toBeInTheDocument()
    expect(screen.getByText('identical_sku_set')).toBeInTheDocument()
  })
})
