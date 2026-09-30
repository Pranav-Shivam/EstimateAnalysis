import { describe, expect, it } from 'vitest'
import { colorFor, DENSE_NODE_COUNT, emptyGraph, mergeNeighborhood, schemaToGraph, toElements } from './graph'

const hood = {
  center: { id: 'A', label: 'SKU', name: 'A', community: 1 },
  nodes: [{ id: 'B', label: 'SKU', name: 'B', community: 1 }],
  edges: [{ source: 'A', target: 'B', type: 'REQUIRES' }],
  truncated: false,
}

describe('mergeNeighborhood', () => {
  it('adds the center, its neighbors and the edges', () => {
    const graph = mergeNeighborhood(emptyGraph(), hood)

    expect([...graph.nodes.keys()].sort()).toEqual(['A', 'B'])
    expect(graph.edges.size).toBe(1)
  })

  it('does not duplicate anything when the same node is expanded twice', () => {
    const graph = mergeNeighborhood(mergeNeighborhood(emptyGraph(), hood), hood)

    expect(graph.nodes.size).toBe(2)
    expect(graph.edges.size).toBe(1)
  })

  it('does not mutate the graph it was given', () => {
    const before = emptyGraph()
    mergeNeighborhood(before, hood)

    expect(before.nodes.size).toBe(0)
  })
})

describe('toElements', () => {
  it('drops an edge whose endpoint is not on screen', () => {
    const graph = mergeNeighborhood(emptyGraph(), hood)
    graph.nodes.delete('B')

    expect(toElements(graph, null).filter((e) => e.data.source)).toHaveLength(0)
  })

  it('gives every schema label a colour and falls back for an unknown one', () => {
    expect(colorFor('SKU')).not.toBe(colorFor('Customer'))
    expect(colorFor('Unheard')).toBe('#8c8c8c')
  })
})

describe('schemaToGraph', () => {
  const schema = {
    node_counts: { SKU: 650, Customer: 125 },
    edges: [{ source: 'SKU', target: 'SKU', type: 'REQUIRES', count: 91 }],
  }

  it('makes one node per type with its count and one counted edge per relationship', () => {
    const graph = schemaToGraph(schema)

    expect(graph.nodes.get('SKU')?.name).toBe('SKU (650)')
    expect([...graph.edges.values()]).toEqual([{ source: 'SKU', target: 'SKU', type: 'REQUIRES (91)' }])
  })
})

describe('toElements density', () => {
  it('hides names once the graph is too big to read', () => {
    const graph = emptyGraph()
    for (let i = 0; i <= DENSE_NODE_COUNT; i++) graph.nodes.set(`N${i}`, { id: `N${i}`, label: 'SKU', name: `n${i}`, community: null })

    expect(toElements(graph, null)[0].data.caption).toBe('')
  })
})
