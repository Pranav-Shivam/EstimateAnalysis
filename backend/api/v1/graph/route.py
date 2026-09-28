from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.v1.graph.response import RebuildResponse
from app.graph.service import rebuild_graph, run_communities
from core.db.session import get_session
from core.graph.client import GraphClient, GraphUnavailable, get_graph_client, get_graph_namespace

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
    except GraphUnavailable as exc:
        raise HTTPException(status_code=503, detail="knowledge graph unavailable") from exc
    return RebuildResponse(
        namespace=summary.namespace, fingerprint=summary.fingerprint, node_counts=summary.node_counts,
        edge_counts=summary.edge_counts, community_count=communities.community_count,
        largest_community_size=communities.largest_community_size,
    )
