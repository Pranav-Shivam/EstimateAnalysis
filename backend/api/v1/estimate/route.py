from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.v1.estimate.request import EstimateRequest
from api.v1.estimate.response import EstimateResponse
from api.v1.retrieval.route import get_embedding_client
from app.estimate.constant import DATASET_AS_OF
from app.estimate.service import QuoteRequestNotFound, run_estimate
from app.graph.reader import GraphReader
from app.graph.service import sync_best_effort, sync_quote
from core.config.settings import Settings
from core.db.session import get_session
from core.graph.client import GraphClient, get_graph_client, get_graph_namespace
from core.llm.openai_agent_client import AgentError, OpenAIAgentClient
from core.llm.openai_embedding_client import OpenAIEmbeddingClient
from core.tracing.langfuse_client import TracingClient, get_tracing_client

router = APIRouter(prefix="/v1/estimate", tags=["estimate"])


def get_agent_client() -> OpenAIAgentClient:
    from openai import OpenAI

    settings = Settings()
    return OpenAIAgentClient(client=OpenAI(api_key=settings.openai_api_key))


@router.post("", response_model=EstimateResponse)
def create_estimate(
    body: EstimateRequest,
    session: Session = Depends(get_session),
    llm_client: OpenAIAgentClient = Depends(get_agent_client),
    graph_client: GraphClient = Depends(get_graph_client),
    ns: str = Depends(get_graph_namespace),
    embedder: OpenAIEmbeddingClient = Depends(get_embedding_client),
    tracing: TracingClient = Depends(get_tracing_client),
) -> EstimateResponse:
    try:
        run = run_estimate(
            session, body.quote_request_id, body.as_of or DATASET_AS_OF, llm_client,
            GraphReader(graph_client, ns), embedder, tracing,
        )
    except QuoteRequestNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentError as exc:
        raise HTTPException(status_code=502, detail="agent failed to produce an estimate") from exc

    session.commit()
    sync_best_effort("estimate draft", sync_quote, session, graph_client, ns, run.row.id)

    result = run.result
    return EstimateResponse(
        estimate_id=run.row.id, quote_request_id=body.quote_request_id, status=result.status, as_of=result.as_of,
        draft=result.draft, totals=result.totals, violations=result.violations, iterations=result.iterations,
        reason=result.reason,
    )
