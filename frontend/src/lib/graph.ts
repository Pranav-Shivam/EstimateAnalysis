import type { ElementDefinition } from 'cytoscape'
import type { GraphEdge, GraphNode, Neighborhood, SchemaOverview } from '../api/types'

export interface GraphState {
  nodes: Map<string, GraphNode>
  edges: Map<string, GraphEdge>
}

export const emptyGraph = (): GraphState => ({ nodes: new Map(), edges: new Map() })

const edgeKey = (edge: GraphEdge) => `${edge.source}|${edge.type}|${edge.target}`

/** Adds a node's neighborhood to what is already on screen. Keyed maps make re-expanding a node a no-op. */
export function mergeNeighborhood(state: GraphState, hood: Neighborhood): GraphState {
  const nodes = new Map(state.nodes)
  const edges = new Map(state.edges)
  for (const node of [hood.center, ...hood.nodes]) nodes.set(node.id, node)
  for (const edge of hood.edges) edges.set(edgeKey(edge), edge)
  return { nodes, edges }
}

export const LABEL_COLORS: Record<string, string> = {
  SKU: '#1677ff',
  Customer: '#52c41a',
  Contract: '#fa8c16',
  Person: '#13c2c2',
  Site: '#8c8c8c',
  Project: '#722ed1',
  ProductFamily: '#eb2f96',
  PricingCategory: '#faad14',
  QuoteRequest: '#f5222d',
  Quote: '#a0d911',
  GraphMeta: '#bfbfbf',
}

const UNKNOWN_LABEL_COLOR = '#8c8c8c'

export const colorFor = (label: string) => LABEL_COLORS[label] ?? UNKNOWN_LABEL_COLOR

/** Beyond this many nodes names and edge labels are hidden: they would overlap into noise. */
export const DENSE_NODE_COUNT = 300

/** The schema map: one node per node type, one edge per relationship type between two types, counts in the text. */
export function schemaToGraph(schema: SchemaOverview): GraphState {
  const graph = emptyGraph()
  for (const [label, count] of Object.entries(schema.node_counts)) {
    graph.nodes.set(label, { id: label, label, name: `${label} (${count})`, community: null })
  }
  for (const edge of schema.edges) {
    const shown = { source: edge.source, target: edge.target, type: `${edge.type} (${edge.count})` }
    graph.edges.set(edgeKey(shown), shown)
  }
  return graph
}

export function toElements(state: GraphState, selectedId: string | null): ElementDefinition[] {
  const dense = state.nodes.size > DENSE_NODE_COUNT
  const nodes = [...state.nodes.values()].map((node) => ({
    data: { id: node.id, caption: dense ? '' : node.name, label: node.label, color: colorFor(node.label) },
    selected: node.id === selectedId,
  }))
  const edges = [...state.edges.values()]
    .filter((edge) => state.nodes.has(edge.source) && state.nodes.has(edge.target))
    .map((edge) => ({ data: { ...edge, id: edgeKey(edge), edgeLabel: dense ? '' : edge.type } }))
  return [...nodes, ...edges]
}
