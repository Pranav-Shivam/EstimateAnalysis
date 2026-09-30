# Graph Explorer and Dashboard Charts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (native, inline). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Let a reviewer search the knowledge graph, hop from node to node, and see charts on the dashboard.

**Architecture:** Three read-only graph routes (search, one-hop neighbors, schema stats) over the existing `GraphClient`, plus a `flags_by_dimension` count on `/v1/metrics`. The frontend adds a `/graph` page (Cytoscape.js, click a node to expand its neighbors, deep-linkable with `?node=`) and Recharts bar charts on the dashboard. Phase 7 left the graph as text only ("Evidence is a stored snapshot, not a live graph view"); this adds the live view.

**Tech Stack:** FastAPI, Neo4j (existing `GraphClient`), React 19, Ant Design 6, Cytoscape.js, Recharts, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-30-phase7-review-ui-design.md` (non-goal "live graph view" is lifted by this plan) and `docs/roadmap.md` Phase 4 (10 node types, 15 edge types).

## Global Constraints

- No em dash anywhere (code, comments, docs). No emojis. No AI attribution in commits.
- Backend layering: route, service, repository. Labels and edge types are never interpolated unless checked against `NODE_LABELS` / `EDGE_TYPES`.
- Every query is scoped by `ns` (graph namespace); results never cross namespaces.
- Neighbor results are capped (`NEIGHBOR_LIMIT = 60`) and flagged `truncated`; hub nodes (`PricingCategory`, `ProductFamily`) can be opened but the cap still applies.
- Frontend types come from the generated `src/api/schema.d.ts` (`npm run gen:api`), not hand-written.

## Review Focus

- Search with empty or whitespace query returns 422/empty, not the whole graph.
- Unknown node id returns 404, not an empty 200.
- Expanding a hub with hundreds of members returns at most 60 nodes and `truncated: true`.
- Neo4j down returns 503 (same as `/rebuild`), not a 500 trace.
- Node ids containing `/` or `:` (site ids, `ns:` keys) must round-trip through the URL.
- Dashboard with zero flags renders an empty-state, not a broken chart.

---

### Task 1: Graph read routes (search, neighbors, stats)

**Files:**
- Modify: `backend/app/graph/repository.py` (add `search_nodes`, `fetch_neighborhood`)
- Modify: `backend/app/graph/constant.py` (add `NEIGHBOR_LIMIT`, `SEARCH_LIMIT`)
- Modify: `backend/app/graph/service.py` (add `search`, `neighborhood`, `schema_stats`)
- Modify: `backend/api/v1/graph/response.py`, `backend/api/v1/graph/route.py`
- Test: `backend/tests/api/v1/test_graph_explorer_route.py`

**Interfaces:**
- Produces: `GET /v1/graph/search?q=` -> `list[GraphNode]`; `GET /v1/graph/nodes/{node_id:path}/neighbors` -> `NeighborhoodResponse(center, nodes, edges, truncated)`; `GET /v1/graph/stats` -> `GraphStatsResponse(node_counts, edge_counts)`.
- `GraphNode = {id: str, label: str, name: str, community: int | None}`; `GraphEdge = {source: str, target: str, type: str}`.

- [ ] **Step 1: Write the failing tests** (`backend/tests/api/v1/test_graph_explorer_route.py`)

```python
from fastapi.testclient import TestClient

from core.db.session import get_session
from core.graph.client import get_graph_client
from main import app
from tests.app.estimate.seed import seed_structure, seed_world
from tests.graph_support import FailingGraphClient


def _client(db_session, graph_ns):
    from app.graph.service import rebuild_graph
    seed_world(db_session)
    seed_structure(db_session)
    rebuild_graph(db_session, get_graph_client(), graph_ns)
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def test_search_finds_a_node_by_id_fragment(db_session, graph_client, graph_ns):
    body = _client(db_session, graph_ns).get("/v1/graph/search", params={"q": "SKU-E-A1"}).json()
    assert any(n["id"] == "SKU-E-A1" and n["label"] == "SKU" for n in body)


def test_search_rejects_a_blank_query(db_session, graph_client, graph_ns):
    assert _client(db_session, graph_ns).get("/v1/graph/search", params={"q": "  "}).status_code == 422


def test_neighbors_return_center_nodes_and_edges(db_session, graph_client, graph_ns):
    body = _client(db_session, graph_ns).get("/v1/graph/nodes/SKU-E-A1/neighbors").json()
    assert body["center"]["id"] == "SKU-E-A1"
    ids = {n["id"] for n in body["nodes"]}
    assert all(e["source"] in ids | {"SKU-E-A1"} and e["target"] in ids | {"SKU-E-A1"} for e in body["edges"])
    assert body["edges"] and body["truncated"] is False


def test_neighbors_of_an_unknown_node_is_404(db_session, graph_client, graph_ns):
    assert _client(db_session, graph_ns).get("/v1/graph/nodes/NOPE/neighbors").status_code == 404


def test_stats_reports_counts_by_label_and_type(db_session, graph_client, graph_ns):
    body = _client(db_session, graph_ns).get("/v1/graph/stats").json()
    assert body["node_counts"]["SKU"] >= 8 and body["edge_counts"]["REQUIRES"] >= 1


def test_graph_down_is_503(db_session, graph_ns):
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_graph_client] = lambda: FailingGraphClient()
    assert TestClient(app).get("/v1/graph/stats").status_code == 503
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/api/v1/test_graph_explorer_route.py -q`
Expected: FAIL (404 on the new routes).

- [ ] **Step 3: Implement**

`constant.py` additions:
```python
NEIGHBOR_LIMIT = 60
SEARCH_LIMIT = 15
```

`repository.py` additions (import the two constants):
```python
def search_nodes(client: GraphClient, ns: str, text: str, limit: int) -> list[dict]:
    return client.read(
        "MATCH (n {ns: $ns}) WHERE NOT n:GraphMeta "
        "AND (toLower(n.id) CONTAINS toLower($text) OR toLower(coalesce(n.name, '')) CONTAINS toLower($text)) "
        "RETURN n.id AS id, labels(n)[0] AS label, coalesce(n.name, n.id) AS name, n.community_id AS community "
        "ORDER BY n.id LIMIT $limit",
        ns=ns, text=text, limit=limit,
    )


def fetch_neighborhood(client: GraphClient, ns: str, node_id: str, limit: int) -> dict | None:
    """The node, its one-hop neighbors (at most `limit`) and the edges to them. None when the node is absent."""
    center = client.read(
        "MATCH (n {key: $key}) RETURN n.id AS id, labels(n)[0] AS label, coalesce(n.name, n.id) AS name, "
        "n.community_id AS community", key=node_key(ns, node_id),
    )
    if not center:
        return None
    rows = client.read(
        "MATCH (c {key: $key})-[r]-(m) WHERE m.ns = $ns AND NOT m:GraphMeta "
        "RETURN m.id AS id, labels(m)[0] AS label, coalesce(m.name, m.id) AS name, m.community_id AS community, "
        "type(r) AS type, startNode(r).id AS source, endNode(r).id AS target LIMIT $fetch",
        key=node_key(ns, node_id), ns=ns, fetch=limit + 1,
    )
    return {"center": center[0], "rows": rows}
```

`service.py` additions:
```python
class GraphNodeNotFound(Exception):
    pass


def search(client: GraphClient, ns: str, text: str) -> list[dict]:
    return search_nodes(client, ns, text.strip(), SEARCH_LIMIT)


def neighborhood(client: GraphClient, ns: str, node_id: str) -> dict:
    found = fetch_neighborhood(client, ns, node_id, NEIGHBOR_LIMIT)
    if found is None:
        raise GraphNodeNotFound(node_id)
    truncated = len(found["rows"]) > NEIGHBOR_LIMIT
    rows = found["rows"][:NEIGHBOR_LIMIT]
    nodes = {r["id"]: {k: r[k] for k in ("id", "label", "name", "community")} for r in rows}
    edges = [{"source": r["source"], "target": r["target"], "type": r["type"]} for r in rows]
    return {"center": found["center"], "nodes": list(nodes.values()), "edges": edges, "truncated": truncated}


def schema_stats(client: GraphClient, ns: str) -> dict:
    return {"node_counts": count_nodes_by_label(client, ns), "edge_counts": count_edges_by_type(client, ns)}
```

`response.py` additions:
```python
class GraphNode(BaseModel):
    id: str
    label: str
    name: str
    community: int | None


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str


class NeighborhoodResponse(BaseModel):
    center: GraphNode
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool


class GraphStatsResponse(BaseModel):
    node_counts: dict[str, int]
    edge_counts: dict[str, int]
```

`route.py` additions (a shared `_graph_errors` context is NOT introduced; repeat the two except clauses as `/rebuild` does, via a small helper):
```python
@contextmanager
def _graph_errors():
    try:
        yield
    except GraphUnavailable as exc:
        raise HTTPException(status_code=503, detail="knowledge graph unavailable") from exc
    except GraphError as exc:
        raise HTTPException(status_code=502, detail="graph query failed") from exc


@router.get("/search", response_model=list[GraphNode])
def search_graph(
    q: str = Query(min_length=1), graph_client: GraphClient = Depends(get_graph_client),
    ns: str = Depends(get_graph_namespace),
) -> list[dict]:
    if not q.strip():
        raise HTTPException(status_code=422, detail="query must not be blank")
    with _graph_errors():
        return search(graph_client, ns, q)


@router.get("/nodes/{node_id:path}/neighbors", response_model=NeighborhoodResponse)
def node_neighbors(
    node_id: str, graph_client: GraphClient = Depends(get_graph_client), ns: str = Depends(get_graph_namespace),
) -> dict:
    with _graph_errors():
        try:
            return neighborhood(graph_client, ns, node_id)
        except GraphNodeNotFound as exc:
            raise HTTPException(status_code=404, detail=f"no graph node {node_id}") from exc


@router.get("/stats", response_model=GraphStatsResponse)
def graph_stats(graph_client: GraphClient = Depends(get_graph_client), ns: str = Depends(get_graph_namespace)) -> dict:
    with _graph_errors():
        return schema_stats(graph_client, ns)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/api/v1/test_graph_explorer_route.py tests/api/v1/test_graph_route.py -q`
Expected: PASS.

- [ ] **Step 5: Commit** `feat: add graph search, neighbors and stats routes`

### Task 2: Flags-by-dimension metric

**Files:**
- Modify: `backend/app/metrics/schemas.py`, `backend/app/metrics/repository.py`, `backend/app/metrics/service.py`, `backend/api/v1/metrics/response.py`
- Test: `backend/tests/api/v1/test_metrics_route.py`, `backend/tests/app/metrics/`

**Interfaces:** `MetricCounts.flags_by_dimension: dict[str, int]` (count of review items per `dimension`); response field `counts.flags_by_dimension`.

- [ ] **Step 1: Failing test** - append to `test_metrics_route.py`:

```python
def test_flags_by_dimension_counts_review_items_per_dimension(db_session):
    before = _counts(db_session)["flags_by_dimension"].get("graph_completion", 0)
    request = _request(db_session)
    estimate = _estimate(db_session, request)
    verdict = _verdict(db_session, estimate, False)
    save_review_item(
        db_session, judge_verdict_id=verdict.id, estimate_id=estimate.id, dimension="graph_completion",
        fact="x", evidence={}, line_index=None,
    )
    assert _counts(db_session)["flags_by_dimension"]["graph_completion"] == before + 1
```

- [ ] **Step 2: Run** `uv run pytest tests/api/v1/test_metrics_route.py -q` -> FAIL (KeyError).
- [ ] **Step 3: Implement.** Add `flags_by_dimension: dict[str, int]` to `MetricCounts` (dataclass) and `MetricCountsResponse`. In `count_metric_inputs` add:

```python
flags_by_dimension=dict(
    session.execute(select(ReviewItemRow.dimension, func.count()).group_by(ReviewItemRow.dimension)).all()
),
```
Fix any existing `MetricCounts(...)` constructions in tests to pass `flags_by_dimension={}`.
- [ ] **Step 4: Run** `uv run pytest tests/api/v1/test_metrics_route.py tests/app/metrics -q` -> PASS.
- [ ] **Step 5: Commit** `feat: report review flags per dimension in metrics`

### Task 3: Regenerate API types, add frontend dependencies

**Files:** `frontend/package.json`, `frontend/src/api/schema.d.ts`, `frontend/openapi.json`

- [ ] **Step 1:** `cd frontend && npm install cytoscape recharts && npm install -D @types/cytoscape` (drop `@types/cytoscape` if cytoscape ships its own types; check `npm ls`).
- [ ] **Step 2:** `cd frontend && npm run gen:api && npm run check:api` -> exit 0.
- [ ] **Step 3: Commit** `chore: add cytoscape and recharts, regenerate api types`

### Task 4: Graph explorer page

**Files:**
- Create: `frontend/src/lib/graph.ts` (pure helpers), `frontend/src/lib/graph.test.ts`
- Create: `frontend/src/components/GraphCanvas.tsx`, `frontend/src/pages/GraphPage.tsx`, `frontend/src/pages/GraphPage.test.tsx`
- Modify: `frontend/src/api/queries.ts` (hooks), `frontend/src/api/types.ts`, `frontend/src/App.tsx`, `frontend/src/components/AppLayout.tsx`

**Interfaces:**
- `graph.ts`: `mergeNeighborhood(state: GraphState, hood: Neighborhood): GraphState` where `GraphState = { nodes: Map<string, GraphNode>; edges: Map<string, GraphEdge> }`, edge key `${source}|${type}|${target}` so re-expanding never duplicates; `LABEL_COLORS: Record<string, string>` covering all 11 labels in `NODE_LABELS`; `toElements(state): ElementDefinition[]`.
- Queries: `useGraphSearch(text)` (enabled when `text.trim().length >= 2`), `fetchNeighborhood(id)` (plain async, used by expand handler).

- [ ] **Step 1: Failing tests** (`graph.test.ts`)

```ts
import { describe, expect, it } from 'vitest'
import { emptyGraph, mergeNeighborhood } from './graph'

const hood = {
  center: { id: 'A', label: 'SKU', name: 'A', community: 1 },
  nodes: [{ id: 'B', label: 'SKU', name: 'B', community: 1 }],
  edges: [{ source: 'A', target: 'B', type: 'REQUIRES' }],
  truncated: false,
}

describe('mergeNeighborhood', () => {
  it('adds the center, neighbors and edges', () => {
    const g = mergeNeighborhood(emptyGraph(), hood)
    expect([...g.nodes.keys()].sort()).toEqual(['A', 'B'])
    expect(g.edges.size).toBe(1)
  })
  it('does not duplicate when the same node is expanded twice', () => {
    const g = mergeNeighborhood(mergeNeighborhood(emptyGraph(), hood), hood)
    expect(g.nodes.size).toBe(2)
    expect(g.edges.size).toBe(1)
  })
})
```

`GraphPage.test.tsx`: mock `../components/GraphCanvas` with a stub that renders each node name as a button calling `onExpand(id)`; mock `globalThis.fetch` for `/v1/graph/search` and `/neighbors`; assert typing "SKU-0001" then picking the result shows its neighbors, and the truncated notice shows when `truncated: true`.

- [ ] **Step 2:** `npx vitest run src/lib/graph.test.ts` -> FAIL.
- [ ] **Step 3: Implement.** `graph.ts` per interface above. `GraphCanvas.tsx`: creates one cytoscape instance in `useEffect` (container ref, style: node background from `LABEL_COLORS`, `label: data(name)`, edge `label: data(type)`, arrow), `cy.on('tap','node', e => onExpand(e.target.id()))`, re-runs `layout({name:'cose', animate:false}).run()` when elements change, destroys on unmount. `GraphPage.tsx`: antd `Input.Search` with results list (label tag + name), `?node=` search param seeds the first expansion, clicking a node calls `fetchNeighborhood`, merges, shows legend (color per label present), a clear button, and an `Alert` when `truncated`. Add route `graph` and a "Graph" menu item (`selectedKey` returns `'graph'`).
- [ ] **Step 4:** `npm test && npx tsc --noEmit` -> PASS.
- [ ] **Step 5: Commit** `feat: add live graph explorer page`

### Task 5: Dashboard charts and evidence deep links

**Files:**
- Modify: `frontend/src/pages/DashboardPage.tsx` (+ test), `frontend/src/api/queries.ts` (`useGraphStats`), `frontend/src/components/EvidencePanel.tsx` (+ test)
- Create: `frontend/src/components/CountBarChart.tsx`

**Interfaces:** `CountBarChart({ title, counts: Record<string, number>, color? })` renders a Recharts horizontal `BarChart` sorted descending, or `Empty` when all counts are zero.

- [ ] **Step 1: Failing tests.** Dashboard test: mock fetch for `/v1/metrics` (with `flags_by_dimension`) and `/v1/graph/stats`; assert headings "Flags by dimension", "Graph nodes by type", "Graph edges by type" are present; with `flags_by_dimension: {}` assert the empty state text "No flags yet". EvidencePanel test: a line with a SKU renders a link to `/graph?node=<sku_id>`.
- [ ] **Step 2:** run -> FAIL.
- [ ] **Step 3: Implement.** `CountBarChart` uses `ResponsiveContainer` with fixed `height={260}`; Dashboard adds three chart cards below the rate cards. In `EvidencePanel`, add `<Link to={`/graph?node=${encodeURIComponent(sku_id)}`}>View in graph</Link>`; the page decodes with `useSearchParams` (which already decodes).
- [ ] **Step 4:** `npm test && npx tsc --noEmit && npm run build` -> PASS.
- [ ] **Step 5: Commit** `feat: add dashboard charts and graph deep links`

### Task 6: Verify and document

- [ ] Backend: `cd backend && uv run pytest -q` all green.
- [ ] Frontend: `npm test`, `npx tsc --noEmit`, `npm run check:api`, `npm run build`.
- [ ] Live: start API, `curl` the three graph routes and `/v1/metrics` against the seeded dev DB; check real counts (SKU 650, REQUIRES 91).
- [ ] Update `frontend/README.md` (Graph page, charts; remove "snapshot, not live graph" gap wording where now false), the roadmap Phase 7 status line, and `docs/interview-prep/phase7-interview.md` with a short graph-explorer section.
- [ ] Commit `docs: document graph explorer and dashboard charts`.
