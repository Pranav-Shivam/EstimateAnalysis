import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.v1.dedupe.response import DedupeResponse, DedupeVerdictResponse
from app.dedupe.service import run_dedupe
from app.graph.service import sync_best_effort, sync_dedupe_verdicts
from core.db.session import get_session
from core.graph.client import GraphClient, get_graph_client, get_graph_namespace
from core.tracing.langfuse_client import TracingClient, get_tracing_client

router = APIRouter(prefix="/v1/dedupe", tags=["dedupe"])


@router.post("/{quote_request_id}", response_model=DedupeResponse)
def dedupe_quote_request(
    quote_request_id: uuid.UUID,
    session: Session = Depends(get_session),
    graph_client: GraphClient = Depends(get_graph_client),
    ns: str = Depends(get_graph_namespace),
    tracing: TracingClient = Depends(get_tracing_client),
) -> DedupeResponse:
    try:
        verdicts = run_dedupe(session, quote_request_id, tracing)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    session.commit()
    sync_best_effort("dedupe verdicts", sync_dedupe_verdicts, session, graph_client, ns, quote_request_id)

    return DedupeResponse(
        quote_request_id=quote_request_id,
        verdicts=[
            DedupeVerdictResponse(
                candidate_quote_request_id=v.candidate_quote_request_id, verdict=v.verdict,
                content_jaccard=v.content_jaccard, style_jaccard=v.style_jaccard, signals_fired=v.signals_fired,
            )
            for v in verdicts
        ],
    )
