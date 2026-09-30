import { Alert, Button, Input, List, Spin, Tag } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { fetchFullGraph, fetchLabelNodes, fetchNeighborhood, fetchSchema, useGraphSearch } from '../api/queries'
import type { GraphNode } from '../api/types'
import { GraphCanvas } from '../components/GraphCanvas'
import { colorFor, DENSE_NODE_COUNT, emptyGraph, mergeNeighborhood, schemaToGraph, type GraphState } from '../lib/graph'

type Mode = 'schema' | 'graph'

const HINTS: Record<Mode, string> = {
  schema: 'This is the shape of the whole graph: one circle per node type, one arrow per relationship type, with counts. Click a type to see its most connected nodes.',
  graph: 'Click any node to add its neighbors. Scroll to zoom, drag to pan.',
}

export function GraphPage() {
  const [params, setParams] = useSearchParams()
  const startId = params.get('node')
  const [text, setText] = useState('')
  const [mode, setMode] = useState<Mode>('schema')
  const [graph, setGraph] = useState<GraphState>(emptyGraph)
  const [selected, setSelected] = useState<string | null>(null)
  const [truncated, setTruncated] = useState<string | null>(null)
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
        setGraph(schemaToGraph(await fetchSchema()))
        setMode('schema')
        setSelected(null)
        setTruncated(null)
      }),
    [run],
  )

  const showLabel = (label: string) =>
    run(async () => {
      const found = await fetchLabelNodes(label)
      const next = emptyGraph()
      for (const node of found.nodes) next.nodes.set(node.id, node)
      setGraph(next)
      setMode('graph')
      setSelected(null)
      setTruncated(found.truncated ? `${label} has more nodes than are shown` : null)
    })

  const showFull = () =>
    run(async () => {
      const full = await fetchFullGraph()
      const next = emptyGraph()
      for (const node of full.nodes) next.nodes.set(node.id, node)
      for (const edge of full.edges) next.edges.set(`${edge.source}|${edge.type}|${edge.target}`, edge)
      setGraph(next)
      setMode('graph')
      setSelected(null)
      setTruncated(null)
    })

  const expand = useCallback(
    (nodeId: string) =>
      run(async () => {
        const hood = await fetchNeighborhood(nodeId)
        setGraph((current) => mergeNeighborhood(current, hood))
        setMode('graph')
        setSelected(nodeId)
        setTruncated(hood.truncated ? `${hood.center.name} has more neighbors than are shown` : null)
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

  const onNodeClick = (id: string) => (mode === 'schema' ? void showLabel(id) : void expand(id))

  const labels = [...new Set([...graph.nodes.values()].map((node) => node.label))].sort()
  const chosen = selected ? graph.nodes.get(selected) : undefined
  const dense = graph.nodes.size > DENSE_NODE_COUNT

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold">Knowledge graph</h1>
      <p className="text-gray-500">{HINTS[mode]}</p>
      <div className="flex gap-2">
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
              {node.name !== node.id && <span className="ml-2 text-gray-500">{node.name}</span>}
            </List.Item>
          )}
        />
      )}
      {error && <Alert type="error" title={error} />}
      {truncated && <Alert type="warning" title={`${truncated}; only the first ones were loaded.`} />}
      {dense && (
        <Alert type="info" title="Names are hidden on a graph this size. Zoom in, or click a node to see what it is." />
      )}
      <div className="flex flex-wrap items-center gap-2">
        {labels.map((label) => (
          <Tag key={label} color={colorFor(label)}>{label}</Tag>
        ))}
        {chosen && mode === 'graph' && (
          <span className="ml-auto text-gray-600">
            Selected: <b>{chosen.name}</b> ({chosen.label}, {chosen.id})
          </span>
        )}
        {loading && <Spin size="small" className="ml-auto" />}
      </div>
      <GraphCanvas graph={graph} selectedId={selected} onExpand={onNodeClick} />
    </div>
  )
}
