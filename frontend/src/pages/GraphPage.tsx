import { ArrowLeftOutlined, ArrowRightOutlined } from '@ant-design/icons'
import { Alert, Breadcrumb, Button, Input, List, Spin, Tag, Tooltip } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { fetchFullGraph, fetchLabelNodes, fetchNeighborhood, fetchSchema, useGraphSearch } from '../api/queries'
import type { GraphNode } from '../api/types'
import { GraphCanvas } from '../components/GraphCanvas'
import { PageHeader } from '../components/PageHeader'
import { colorFor, DENSE_NODE_COUNT, emptyGraph, mergeNeighborhood, schemaToGraph, type GraphState } from '../lib/graph'

type Mode = 'schema' | 'graph'

const HINTS: Record<Mode, string> = {
  schema: 'This is the shape of the whole graph: one circle per node type, one arrow per relationship type, with counts. Click a type to see its most connected nodes.',
  graph: 'Click any node to add its neighbors. Scroll to zoom, drag to pan.',
}

/** One step of exploration. Each step keeps its own snapshot, so going back restores it without refetching. */
interface View {
  title: string
  mode: Mode
  graph: GraphState
  selected: string | null
  truncated: string | null
}

interface History {
  views: View[]
  index: number
}

// A new step after going back drops the steps ahead of it, the way a browser does. Reloading the step already
// shown (Overview clicked twice, or StrictMode running the first load twice) replaces it instead of stacking a copy.
function push(history: History, view: View): History {
  const current = history.views[history.index]
  const index = current && current.title === view.title && current.mode === view.mode ? history.index : history.index + 1
  return { views: [...history.views.slice(0, index), view], index }
}

export function GraphPage() {
  const [params, setParams] = useSearchParams()
  const startId = params.get('node')
  const [text, setText] = useState('')
  const [history, setHistory] = useState<History>({ views: [], index: -1 })
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const search = useGraphSearch(text)

  const run = useCallback(async (load: () => Promise<void>) => {
    setError(null)
    setLoading(true)
    try {
      await load()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not load the graph')
    } finally {
      setLoading(false)
    }
  }, [])

  const showSchema = useCallback(
    () =>
      run(async () => {
        const graph = schemaToGraph(await fetchSchema())
        setHistory((current) => push(current, { title: 'Overview', mode: 'schema', graph, selected: null, truncated: null }))
      }),
    [run],
  )

  const showLabel = (label: string) =>
    run(async () => {
      const found = await fetchLabelNodes(label)
      const next = emptyGraph()
      for (const node of found.nodes) next.nodes.set(node.id, node)
      const truncated = found.truncated ? `${label} has more nodes than are shown` : null
      setHistory((current) => push(current, { title: label, mode: 'graph', graph: next, selected: null, truncated }))
    })

  const showFull = () =>
    run(async () => {
      const full = await fetchFullGraph()
      const next = emptyGraph()
      for (const node of full.nodes) next.nodes.set(node.id, node)
      for (const edge of full.edges) next.edges.set(`${edge.source}|${edge.type}|${edge.target}`, edge)
      setHistory((current) => push(current, { title: 'Full graph', mode: 'graph', graph: next, selected: null, truncated: null }))
    })

  const expand = useCallback(
    (nodeId: string) =>
      run(async () => {
        const hood = await fetchNeighborhood(nodeId)
        const truncated = hood.truncated ? `${hood.center.name} has more neighbors than are shown` : null
        setHistory((current) => {
          const base = current.views[current.index]?.graph ?? emptyGraph()
          const graph = mergeNeighborhood(base, hood)
          return push(current, { title: hood.center.name, mode: 'graph', graph, selected: nodeId, truncated })
        })
      }),
    [run],
  )

  useEffect(() => {
    if (startId) void expand(startId)
    else void showSchema()
  }, [startId, expand, showSchema])

  const pick = (node: GraphNode) => {
    setText('')
    setParams({ node: node.id })
  }

  const view = history.views[history.index]
  const { mode, graph, selected, truncated } = view ?? { mode: 'schema', graph: emptyGraph(), selected: null, truncated: null }
  const goTo = (index: number) => setHistory((current) => ({ ...current, index }))
  const canBack = history.index > 0
  const canForward = history.index < history.views.length - 1

  const onNodeClick = (id: string) => (mode === 'schema' ? void showLabel(id) : void expand(id))

  const labels = [...new Set([...graph.nodes.values()].map((node) => node.label))].sort()
  const chosen = selected ? graph.nodes.get(selected) : undefined
  const dense = graph.nodes.size > DENSE_NODE_COUNT

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="Knowledge graph" description={HINTS[mode]} />
      <div className="flex gap-2">
        <Tooltip title="Back">
          <Button aria-label="Back" icon={<ArrowLeftOutlined />} disabled={!canBack} onClick={() => goTo(history.index - 1)} />
        </Tooltip>
        <Tooltip title="Forward">
          <Button
            aria-label="Forward"
            icon={<ArrowRightOutlined />}
            disabled={!canForward}
            onClick={() => goTo(history.index + 1)}
          />
        </Tooltip>
        <Input.Search
          allowClear
          placeholder="Search by id or name, for example SKU-0001 or Crown"
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        <Button onClick={() => (startId ? setParams({}) : void showSchema())}>Overview</Button>
        <Button onClick={() => void showFull()}>Show full graph</Button>
      </div>
      {search.error && <Alert type="error" title={search.error.message} />}
      {text.trim().length >= 2 && search.data && (
        <List
          size="small"
          bordered
          locale={{ emptyText: 'No matching node' }}
          dataSource={search.data}
          renderItem={(node) => (
            <List.Item className="cursor-pointer" onClick={() => pick(node)}>
              <Tag color={colorFor(node.label)}>{node.label}</Tag>
              {node.id}
              {node.name !== node.id && <span className="ml-2 text-slate-500">{node.name}</span>}
            </List.Item>
          )}
        />
      )}
      {error && <Alert type="error" title={error} />}
      {truncated && <Alert type="warning" title={`${truncated}; only the first ones were loaded.`} />}
      {dense && (
        <Alert type="info" title="Names are hidden on a graph this size. Zoom in, or click a node to see what it is." />
      )}
      {history.views.length > 1 && (
        <Breadcrumb
          aria-label="Exploration path"
          items={history.views.slice(0, history.index + 1).map((step, index) => ({
            key: index,
            title:
              index === history.index ? (
                <span className="font-medium text-slate-800">{step.title}</span>
              ) : (
                <button type="button" className="cursor-pointer text-indigo-600 hover:underline" onClick={() => goTo(index)}>
                  {step.title}
                </button>
              ),
          }))}
        />
      )}
      <div className="flex flex-wrap items-center gap-2">
        {labels.map((label) => (
          <Tag key={label} color={colorFor(label)}>{label}</Tag>
        ))}
        {chosen && mode === 'graph' && (
          <span className="ml-auto text-slate-600">
            Selected: <b>{chosen.name}</b> ({chosen.label}, {chosen.id})
          </span>
        )}
        {loading && <Spin size="small" className="ml-auto" />}
      </div>
      <GraphCanvas graph={graph} selectedId={selected} onExpand={onNodeClick} />
    </div>
  )
}
