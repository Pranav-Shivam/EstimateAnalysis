import { fireEvent, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { json, mockApi, renderWithProviders } from '../test/render'
import { GraphPage } from './GraphPage'

// jsdom has no canvas, so the canvas stub renders each node as a button that expands it like a click would.
vi.mock('../components/GraphCanvas', () => ({
  GraphCanvas: ({ graph, onExpand }: { graph: { nodes: Map<string, { id: string; name: string }> }; onExpand: (id: string) => void }) => (
    <div>
      {[...graph.nodes.values()].map((node) => (
        <button key={node.id} onClick={() => onExpand(node.id)}>{`node ${node.name}`}</button>
      ))}
    </div>
  ),
}))

const sku = { id: 'SKU-1', label: 'SKU', name: 'Widget', community: 1 }
const part = { id: 'SKU-2', label: 'SKU', name: 'Gasket', community: 1 }
const schema = () =>
  json({
    node_counts: { SKU: 650, Contract: 125 },
    edges: [{ source: 'SKU', target: 'SKU', type: 'REQUIRES', count: 91 }],
  })

const hood = (truncated = false) => ({
  center: sku, nodes: [part], edges: [{ source: 'SKU-1', target: 'SKU-2', type: 'REQUIRES' }], truncated,
})

describe('GraphPage', () => {
  it('starts from the node in the URL and shows its neighbors', async () => {
    mockApi({ 'GET /v1/graph/nodes/SKU-1/neighbors': () => json(hood()) })

    renderWithProviders(<GraphPage />, { route: '/graph?node=SKU-1' })

    expect(await screen.findByText('node Widget')).toBeInTheDocument()
    expect(screen.getByText('node Gasket')).toBeInTheDocument()
  })

  it('expands another node when it is clicked', async () => {
    const expanded = vi.fn(() => json({ center: part, nodes: [{ id: 'SKU-3', label: 'SKU', name: 'Bolt', community: 1 }], edges: [], truncated: false }))
    mockApi({ 'GET /v1/graph/nodes/SKU-1/neighbors': () => json(hood()), 'GET /v1/graph/nodes/SKU-2/neighbors': expanded })
    renderWithProviders(<GraphPage />, { route: '/graph?node=SKU-1' })

    fireEvent.click(await screen.findByText('node Gasket'))

    expect(await screen.findByText('node Bolt')).toBeInTheDocument()
    expect(screen.getByText('node Widget')).toBeInTheDocument()
  })

  it('warns when a node has more neighbors than were loaded', async () => {
    mockApi({ 'GET /v1/graph/nodes/SKU-1/neighbors': () => json(hood(true)) })

    renderWithProviders(<GraphPage />, { route: '/graph?node=SKU-1' })

    expect(await screen.findByText(/has more neighbors than are shown/)).toBeInTheDocument()
  })

  it('shows the backend message when a node is not found', async () => {
    mockApi({ 'GET /v1/graph/nodes/NOPE/neighbors': () => json({ detail: 'no graph node NOPE' }, 404) })

    renderWithProviders(<GraphPage />, { route: '/graph?node=NOPE' })

    expect(await screen.findByText('no graph node NOPE')).toBeInTheDocument()
  })

  it('searches, lists matches and loads the one picked', async () => {
    mockApi({
      'GET /v1/graph/schema': schema,
      'GET /v1/graph/search': () => json([sku]),
      'GET /v1/graph/nodes/SKU-1/neighbors': () => json(hood()),
    })
    renderWithProviders(<GraphPage />, { route: '/graph' })

    await userEvent.type(screen.getByPlaceholderText(/Search by id or name/), 'Wid')
    await userEvent.click(await screen.findByText('SKU-1'))

    expect(await screen.findByText('node Widget')).toBeInTheDocument()
  })

  it('does not search on a single character', async () => {
    const fetchMock = mockApi({ 'GET /v1/graph/schema': schema, 'GET /v1/graph/search': () => json([]) })
    renderWithProviders(<GraphPage />, { route: '/graph' })
    await screen.findByText('node SKU (650)')

    await userEvent.type(screen.getByPlaceholderText(/Search by id or name/), 'W')

    const urls = fetchMock.mock.calls.map(([input]) => (input instanceof Request ? input.url : String(input)))
    expect(urls.some((url) => url.includes('/search'))).toBe(false)
  })

  it('opens on the schema map with a count per node type', async () => {
    mockApi({ 'GET /v1/graph/schema': schema })

    renderWithProviders(<GraphPage />, { route: '/graph' })

    expect(await screen.findByText('node SKU (650)')).toBeInTheDocument()
    expect(screen.getByText('node Contract (125)')).toBeInTheDocument()
  })

  it('loads the members of a type when its schema node is clicked', async () => {
    mockApi({
      'GET /v1/graph/schema': schema,
      'GET /v1/graph/nodes': () => json({ nodes: [sku, part], truncated: true }),
    })
    renderWithProviders(<GraphPage />, { route: '/graph' })

    fireEvent.click(await screen.findByText('node SKU (650)'))

    expect(await screen.findByText('node Widget')).toBeInTheDocument()
    expect(screen.getByText(/SKU has more nodes than are shown/)).toBeInTheDocument()
  })

  it('draws the whole graph on demand', async () => {
    mockApi({
      'GET /v1/graph/schema': schema,
      'GET /v1/graph/full': () => json({ nodes: [sku, part], edges: hood().edges }),
    })
    renderWithProviders(<GraphPage />, { route: '/graph' })
    await screen.findByText('node SKU (650)')

    fireEvent.click(screen.getByRole('button', { name: 'Show full graph' }))

    expect(await screen.findByText('node Widget')).toBeInTheDocument()
    expect(screen.getByText('node Gasket')).toBeInTheDocument()
  })
  it('goes back and forward through the steps explored, without refetching', async () => {
    const schemaCalls = vi.fn(schema)
    mockApi({
      'GET /v1/graph/schema': schemaCalls,
      'GET /v1/graph/nodes': () => json({ nodes: [sku, part], truncated: false }),
    })
    renderWithProviders(<GraphPage />, { route: '/graph' })
    expect(screen.getByRole('button', { name: 'Back' })).toBeDisabled()

    fireEvent.click(await screen.findByText('node SKU (650)'))
    expect(await screen.findByText('node Widget')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Back' }))
    expect(screen.getByText('node SKU (650)')).toBeInTheDocument()
    expect(screen.queryByText('node Widget')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Forward' })).toBeEnabled()

    await userEvent.click(screen.getByRole('button', { name: 'Forward' }))
    expect(screen.getByText('node Widget')).toBeInTheDocument()
    expect(schemaCalls).toHaveBeenCalledTimes(1)
  })

  it('shows the path explored and jumps to any earlier step from it', async () => {
    mockApi({
      'GET /v1/graph/schema': schema,
      'GET /v1/graph/nodes': () => json({ nodes: [sku], truncated: false }),
      'GET /v1/graph/nodes/SKU-1/neighbors': () => json(hood()),
    })
    renderWithProviders(<GraphPage />, { route: '/graph' })

    fireEvent.click(await screen.findByText('node SKU (650)'))
    fireEvent.click(await screen.findByText('node Widget'))
    expect(await screen.findByText('node Gasket')).toBeInTheDocument()

    const path = within(screen.getByRole('navigation', { name: 'Exploration path' }))
    expect(path.getByRole('button', { name: 'SKU' })).toBeInTheDocument()
    expect(path.getByText('Widget')).toBeInTheDocument()

    await userEvent.click(path.getByRole('button', { name: 'Overview' }))

    expect(screen.getByText('node SKU (650)')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Forward' })).toBeEnabled()
  })
})
