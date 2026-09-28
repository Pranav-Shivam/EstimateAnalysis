import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.estimate.graph import run_agent
from app.estimate.helper import compute_totals
from app.estimate.models import EstimateDraftRow
from app.estimate.prompts import build_request_message
from app.estimate.repository import save_estimate_draft
from app.estimate.schemas import EstimateResult
from app.estimate.tools import ToolContext
from app.intake.repository import get_quote_request


@dataclass
class EstimateRunResult:
    row: EstimateDraftRow
    result: EstimateResult


def run_estimate(session: Session, quote_request_id: uuid.UUID, as_of: date, llm_client) -> EstimateRunResult:
    quote_request = get_quote_request(session, quote_request_id)
    if quote_request is None:
        raise ValueError(f"quote request {quote_request_id} not found")

    ctx = ToolContext(session=session, as_of=as_of)
    state = run_agent(llm_client, ctx, build_request_message(quote_request, as_of))

    draft = state["last_draft"]
    result = EstimateResult(
        status=state["status"], as_of=as_of, draft=draft,
        totals=compute_totals(draft.lines) if draft else None,
        violations=state["violations"], iterations=state["submissions"], reason=state["reason"],
    )
    row = save_estimate_draft(
        session, quote_request_id=quote_request_id, status=result.status,
        draft=draft.model_dump(mode="json") if draft else None,
        violations=[v.model_dump(mode="json") for v in result.violations],
        iterations=result.iterations, reason=result.reason,
    )
    return EstimateRunResult(row=row, result=result)
