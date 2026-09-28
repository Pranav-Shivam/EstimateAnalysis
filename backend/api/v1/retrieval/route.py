from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.v1.retrieval.request import AskRequest
from api.v1.retrieval.response import AskResponse
from app.graph.reader import GraphReader
from app.retrieval.service import KnowledgeService
from app.retrieval.vector import EmbeddingsNotBuilt
from core.config.settings import Settings
from core.db.session import get_session
from core.graph.client import GraphClient, GraphUnavailable, get_graph_client, get_graph_namespace
from core.llm.openai_embedding_client import EmbeddingError, OpenAIEmbeddingClient

router = APIRouter(prefix="/v1/retrieval", tags=["retrieval"])


def get_embedding_client() -> OpenAIEmbeddingClient:
    from openai import OpenAI

    settings = Settings()
    return OpenAIEmbeddingClient(client=OpenAI(api_key=settings.openai_api_key))


@router.post("/ask", response_model=AskResponse)
def ask(
    body: AskRequest,
    session: Session = Depends(get_session),
    graph_client: GraphClient = Depends(get_graph_client),
    ns: str = Depends(get_graph_namespace),
    embedder: OpenAIEmbeddingClient = Depends(get_embedding_client),
) -> AskResponse:
    service = KnowledgeService(session=session, graph=GraphReader(graph_client, ns), embedder=embedder)
    try:
        result = service.ask(body.question)
    except GraphUnavailable as exc:
        raise HTTPException(status_code=503, detail="knowledge graph unavailable") from exc
    except EmbeddingsNotBuilt as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except EmbeddingError as exc:
        raise HTTPException(status_code=502, detail="embedding call failed") from exc
    return AskResponse(route=result.route.value, rule=result.rule, evidence=result.evidence)
