import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.v1.judge.response import JudgeResponse, ReviewItemResponse
from app.estimate.constant import DATASET_AS_OF
from app.graph.reader import GraphReader
from app.judge.service import EstimateNotFound, run_judge
from core.config.settings import Settings
from core.db.session import get_session
from core.graph.client import GraphClient, GraphError, GraphUnavailable, get_graph_client, get_graph_namespace
from core.llm.anthropic_judge_client import AnthropicJudgeClient, JudgeError

router = APIRouter(prefix="/v1/judge", tags=["judge"])


def get_judge_client() -> AnthropicJudgeClient:
    from anthropic import Anthropic

    settings = Settings()
    return AnthropicJudgeClient(client=Anthropic(api_key=settings.anthropic_api_key))


@router.post("/{estimate_id}", response_model=JudgeResponse)
def judge_estimate(
    estimate_id: uuid.UUID,
    session: Session = Depends(get_session),
    graph_client: GraphClient = Depends(get_graph_client),
    ns: str = Depends(get_graph_namespace),
    llm_client: AnthropicJudgeClient = Depends(get_judge_client),
) -> JudgeResponse:
    try:
        run = run_judge(session, GraphReader(graph_client, ns), DATASET_AS_OF, estimate_id, llm_client)
    except EstimateNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except JudgeError as exc:
        raise HTTPException(status_code=502, detail="judge failed to score the estimate") from exc
    except GraphUnavailable as exc:
        raise HTTPException(status_code=503, detail="knowledge graph unavailable") from exc
    except GraphError as exc:
        raise HTTPException(status_code=502, detail="graph query failed") from exc

    session.commit()
    review_item = (
        ReviewItemResponse(
            dimension=run.review_item.dimension, fact=run.review_item.fact, evidence=run.review_item.evidence,
            line_index=run.review_item.line_index,
        )
        if run.review_item else None
    )
    return JudgeResponse(
        judge_verdict_id=run.verdict_id, estimate_id=run.verdict.estimate_id, model=run.verdict.model,
        dimensions=run.verdict.dimensions, overall_confidence=run.verdict.overall_confidence,
        flagged_dimension=run.verdict.flagged_dimension, trusted=run.verdict.trusted, review_item=review_item,
    )
