import cytoscape from 'cytoscape'
import fcose from 'cytoscape-fcose'
import { useEffect, useRef } from 'react'
import { DENSE_NODE_COUNT, toElements, type GraphState } from '../lib/graph'

cytoscape.use(fcose)

// A small graph is fitted to the box, and without a cap it is zoomed until its labels fill the screen.
const MAX_ZOOM = 1.2

interface Props {
  graph: GraphState
  selectedId: string | null
  onExpand: (nodeId: string) => void
}

const STYLE: cytoscape.StylesheetJson = [
  {
    selector: 'node',
    style: {
      'background-color': 'data(color)', label: 'data(caption)', 'font-size': 10, 'text-valign': 'bottom',
      'text-margin-y': 4, width: 26, height: 26, 'text-wrap': 'ellipsis', 'text-max-width': '110px',
    },
  },
  { selector: 'node:selected', style: { 'border-width': 3, 'border-color': '#000' } },
  {
    selector: 'edge',
    style: {
      width: 1.5, 'line-color': '#bfbfbf', 'target-arrow-color': '#bfbfbf', 'target-arrow-shape': 'triangle',
      'curve-style': 'bezier', label: 'data(edgeLabel)', 'font-size': 8, color: '#595959',
      'text-background-color': '#fff', 'text-background-opacity': 0.8,
    },
  },
]

export function GraphCanvas({ graph, selectedId, onExpand }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const cy = useRef<cytoscape.Core | null>(null)
  const expand = useRef(onExpand)
  expand.current = onExpand

  useEffect(() => {
    if (!container.current) return
    const instance = cytoscape({ container: container.current, style: STYLE, wheelSensitivity: 0.3, maxZoom: MAX_ZOOM })
    instance.on('tap', 'node', (event) => expand.current(event.target.id()))
    cy.current = instance
    return () => {
      instance.destroy()
      cy.current = null
    }
  }, [])

  useEffect(() => {
    const instance = cy.current
    if (!instance) return
    // Expanding a node keeps what is already placed where it is; a wholly new graph is laid out from scratch.
    const shown = new Set(instance.nodes().map((node) => node.id()))
    const carriedOver = [...graph.nodes.keys()].filter((id) => shown.has(id)).length
    instance.json({ elements: toElements(graph, null) })
    // fCoSE lays out the full graph (1.7k nodes) in about a second at draft quality; the built-in cose takes 20s.
    const dense = graph.nodes.size > DENSE_NODE_COUNT
    instance
      .layout({
        name: 'fcose', animate: false, padding: 40, randomize: carriedOver === 0, fit: carriedOver === 0,
        quality: dense ? 'draft' : 'default', nodeRepulsion: 9000, idealEdgeLength: 110, nodeSeparation: 90,
      } as cytoscape.LayoutOptions)
      .run()
  }, [graph])

  useEffect(() => {
    const instance = cy.current
    if (!instance) return
    instance.elements(':selected').unselect()
    if (selectedId) instance.getElementById(selectedId).select()
  }, [graph, selectedId])

  return <div ref={container} className="h-[560px] w-full rounded-lg border border-slate-200 bg-white" data-testid="graph-canvas" />
}
