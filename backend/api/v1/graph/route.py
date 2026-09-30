from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.v1.graph.response import (
    FullGraphResponse, GraphNode, GraphStatsResponse, LabelNodesResponse, NeighborhoodResponse, RebuildResponse,
    SchemaOverviewResponse,
)
from app.graph.constant import NODE_LABELS
from app.graph.service import (
    GraphNodeNotFound, GraphRebuildInProgress, full_graph, neighborhood, nodes_of_label, rebuild_graph, run_communities,
    schema_overview, schema_stats, search,
)
from core.db.session import get_session
from core.graph.client import GraphClient, GraphError, GraphUnavailable, get_graph_client, get_graph_namespace

router = APIRouter(prefix="/v1/graph", tags=["graph"])


@router.post("/rebuild", response_model=RebuildResponse)
def rebuild(
    session: Session = Depends(get_session),
    graph_client: GraphClient = Depends(get_graph_client),
    ns: str = Depends(get_graph_namespace),
) -> RebuildResponse:
    try:
        summary = rebuild_graph(session, graph_client, ns)
        communities = run_communities(graph_client, ns)
    except GraphRebuildInProgress as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GraphUnavailable as exc:
        raise HTTPException(status_code=503, detail="knowledge graph unavailable") from exc
    except GraphError as exc:
        raise HTTPException(status_code=502, detail="graph query failed") from exc
    return RebuildResponse(
        namespace=summary.namespace, fingerprint=summary.fingerprint, node_counts=summary.node_counts,
        edge_counts=summary.edge_counts, community_count=communities.community_count,
        largest_community_size=communities.largest_community_size,
    )


@contextmanager
def _graph_errors() -> Iterator[None]:
    try:
        yield
    except GraphUnavailable as exc:
        raise HTTPException(status_code=503, detail="knowledge graph unavailable") from exc
    except GraphError as exc:
        raise HTTPException(status_code=502, detail="graph query failed") from exc


@router.get("/search", response_model=list[GraphNode])
def search_graph(
    q: str = Query(min_length=1),
    graph_client: GraphClient = Depends(get_graph_client),
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


@router.get("/schema", response_model=SchemaOverviewResponse)
def graph_schema(graph_client: GraphClient = Depends(get_graph_client), ns: str = Depends(get_graph_namespace)) -> dict:
    with _graph_errors():
        return schema_overview(graph_client, ns)


@router.get("/nodes", response_model=LabelNodesResponse)
def graph_nodes_of_label(
    label: str, graph_client: GraphClient = Depends(get_graph_client), ns: str = Depends(get_graph_namespace),
) -> dict:
    if label not in NODE_LABELS:
        raise HTTPException(status_code=422, detail=f"unknown node label {label}")
    with _graph_errors():
        return nodes_of_label(graph_client, ns, label)


@router.get("/full", response_model=FullGraphResponse)
def graph_full(graph_client: GraphClient = Depends(get_graph_client), ns: str = Depends(get_graph_namespace)) -> dict:
    with _graph_errors():
        return full_graph(graph_client, ns)
