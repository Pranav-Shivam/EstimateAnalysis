import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { json, mockApi, renderWithProviders } from '../test/render'
import { reviewItem, skus } from '../test/fixtures'
import { FlaggedFactCard } from './FlaggedFactCard'

const RESOLVE = 'POST /v1/review/item-1/resolve'
const RESOLVED_OK = { id: 'item-1', status: 'corrected', outcome: 'corrected', correction: null, consolidation_enqueued: true }

function resolveMock(status = 200, body: unknown = RESOLVED_OK) {
  const bodies: unknown[] = []
  mockApi({
    [RESOLVE]: async (request) => {
      bodies.push(await request.json())
      return json(body, status)
    },
    'GET /v1/review': () => json([]),
  })
  return bodies
}

describe('FlaggedFactCard open item', () => {
  it('shows the one fact and the evidence with Approve and Correct actions', () => {
    renderWithProviders(<FlaggedFactCard item={reviewItem()} skus={skus} />)

    expect(screen.getByText(/the price is a peer-median prediction/)).toBeInTheDocument()
    expect(screen.getByText('Predicted price')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve as is' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Correct' })).toBeInTheDocument()
  })

  it('approves without a correction', async () => {
    const bodies = resolveMock(200, { ...RESOLVED_OK, status: 'approved', outcome: 'approved' })
    renderWithProviders(<FlaggedFactCard item={reviewItem()} skus={skus} />)

    await userEvent.click(screen.getByRole('button', { name: 'Approve as is' }))

    await waitFor(() => expect(bodies).toEqual([{ outcome: 'approved' }]))
  })

  it('blocks a bad price before any network call', async () => {
    const bodies = resolveMock()
    renderWithProviders(<FlaggedFactCard item={reviewItem()} skus={skus} />)

    await userEvent.click(screen.getByRole('button', { name: 'Correct' }))
    await userEvent.type(screen.getByLabelText('Correct unit price (USD)'), '0')
    await userEvent.click(screen.getByRole('button', { name: 'Save correction' }))

    expect(screen.getByText('Enter a price above zero.')).toBeInTheDocument()
    expect(bodies).toEqual([])
  })

  it('submits a valid price correction and says it is applied in the background', async () => {
    const bodies = resolveMock()
    renderWithProviders(<FlaggedFactCard item={reviewItem()} skus={skus} />)

    await userEvent.click(screen.getByRole('button', { name: 'Correct' }))
    await userEvent.type(screen.getByLabelText('Correct unit price (USD)'), '42.5')
    await userEvent.click(screen.getByRole('button', { name: 'Save correction' }))

    await waitFor(() =>
      expect(bodies).toEqual([
        { outcome: 'corrected', correction: { sku_id: 'SKU-1', corrected_unit_price: 42.5 } },
      ]),
    )
    expect(
      await screen.findByText('Correction saved. It is applied to the reference data in the background.'),
    ).toBeInTheDocument()
  })

  it('shows the backend detail verbatim when the item was already resolved', async () => {
    resolveMock(409, { detail: "review item item-1 is already 'corrected'" })
    renderWithProviders(<FlaggedFactCard item={reviewItem()} skus={skus} />)

    await userEvent.click(screen.getByRole('button', { name: 'Approve as is' }))

    expect(await screen.findByText("review item item-1 is already 'corrected'")).toBeInTheDocument()
  })

  it('shows the backend detail verbatim when the correction is rejected', async () => {
    resolveMock(422, { detail: "sku_id 'SKU-9' was not flagged by this review item" })
    renderWithProviders(<FlaggedFactCard item={reviewItem()} skus={skus} />)

    await userEvent.click(screen.getByRole('button', { name: 'Correct' }))
    await userEvent.type(screen.getByLabelText('Correct unit price (USD)'), '10')
    await userEvent.click(screen.getByRole('button', { name: 'Save correction' }))

    expect(await screen.findByText("sku_id 'SKU-9' was not flagged by this review item")).toBeInTheDocument()
  })
})

describe('FlaggedFactCard other dimensions', () => {
  it('asks for the required part of a graph_completion item and refuses a self-requirement', async () => {
    const item = reviewItem({
      dimension: 'graph_completion',
      fact: 'SKU-1 is quoted with no required part recorded',
      evidence: {
        dimension: 'graph_completion',
        lines: [
          { line_index: 0, sku_id: 'SKU-1', discontinued: false, live_sku_id: 'SKU-1', required_part_ids: [], missing_required_part_ids: [] },
        ],
      },
    })
    const bodies = resolveMock()
    renderWithProviders(<FlaggedFactCard item={item} skus={skus} />)

    await userEvent.click(screen.getByRole('button', { name: 'Correct' }))
    await userEvent.type(screen.getByLabelText('Required part (SKU id)'), 'SKU-1')
    await userEvent.click(screen.getByRole('button', { name: 'Save correction' }))

    expect(screen.getByText('A SKU cannot require itself.')).toBeInTheDocument()

    await userEvent.clear(screen.getByLabelText('Required part (SKU id)'))
    await userEvent.type(screen.getByLabelText('Required part (SKU id)'), 'SKU-2')
    await userEvent.click(screen.getByRole('button', { name: 'Save correction' }))

    await waitFor(() =>
      expect(bodies).toEqual([
        { outcome: 'corrected', correction: { sku_id: 'SKU-1', required_sku_id: 'SKU-2' } },
      ]),
    )
  })

  it('prefills the contract and category of a contract_discount item', async () => {
    const item = reviewItem({
      dimension: 'contract_discount',
      fact: 'SKU-1: a contract customer is quoted at full price',
      evidence: {
        dimension: 'contract_discount',
        lines: [
          { line_index: 0, sku_id: 'SKU-1', discount_pct: 0, contract_id: 'CTR-1', covered: null, active_on_as_of: null, days_to_expiry: null },
        ],
      },
    })
    const bodies = resolveMock()
    renderWithProviders(<FlaggedFactCard item={item} skus={skus} />)

    await userEvent.click(screen.getByRole('button', { name: 'Correct' }))
    expect(screen.getByText('Confirm that CTR-1 covers Cat-A.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Save correction' }))

    await waitFor(() =>
      expect(bodies).toEqual([
        { outcome: 'corrected', correction: { contract_id: 'CTR-1', category: 'Cat-A' } },
      ]),
    )
  })
})

describe('FlaggedFactCard read-only states', () => {
  it('shows a resolved item as read-only with its outcome and correction', () => {
    const item = reviewItem({
      status: 'consolidated',
      outcome: 'corrected',
      correction: { sku_id: 'SKU-1', corrected_unit_price: 42.5 },
      resolved_at: '2030-01-02T09:00:00',
    })

    renderWithProviders(<FlaggedFactCard item={item} skus={skus} />)

    expect(screen.getByText('Applied to the reference data.')).toBeInTheDocument()
    expect(screen.getByText('Corrected unit price')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('shows a guardrail item with its violations and no actions', () => {
    const item = reviewItem({
      dimension: 'guardrail',
      fact: 'guardrail violations persisted after 3 retries',
      evidence: { violations: [{ guardrail: 'required_fields', line_index: 0, message: 'line quantity must be a whole number above 0' }] },
    })

    renderWithProviders(<FlaggedFactCard item={item} skus={skus} />)

    expect(screen.getByText('line quantity must be a whole number above 0', { exact: false })).toBeInTheDocument()
    expect(screen.getByText('Guardrail-blocked drafts cannot be resolved from this screen yet.')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
