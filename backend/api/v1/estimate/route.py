from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.v1.estimate.request import EstimateRequest
from api.v1.estimate.response import EstimateResponse
from app.estimate.constant import DATASET_AS_OF
from app.estimate.service import run_estimate
from core.config.settings import Settings
from core.db.session import get_session
from core.llm.openai_agent_client import AgentError, OpenAIAgentClient

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
) -> EstimateResponse:
    try:
        run = run_estimate(session, body.quote_request_id, body.as_of or DATASET_AS_OF, llm_client)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentError as exc:
        raise HTTPException(status_code=502, detail="agent failed to produce an estimate") from exc

    session.commit()

    result = run.result
    return EstimateResponse(
        estimate_id=run.row.id, quote_request_id=body.quote_request_id, status=result.status, as_of=result.as_of,
        draft=result.draft, totals=result.totals, violations=result.violations, iterations=result.iterations,
        reason=result.reason,
    )
