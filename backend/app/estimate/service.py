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
from app.graph.reader import GraphReader
from app.intake.repository import get_quote_request
from app.retrieval.service import KnowledgeService
from app.retrieval.vector import Embedder
from core.tracing.langfuse_client import TracingClient


class QuoteRequestNotFound(Exception):
    pass


@dataclass
class EstimateRunResult:
    row: EstimateDraftRow
    result: EstimateResult


def _request_sku_ids(quote_request) -> tuple[str, ...]:
    """The SKUs intake resolved by code. Items intake could not resolve have no sku_id and cannot anchor a check."""
    items = quote_request.parsed_json.get("resolved_line_items", [])
    return tuple(sorted({item["sku_id"] for item in items if item.get("sku_id")}))


def run_estimate(
    session: Session, quote_request_id: uuid.UUID, as_of: date, llm_client, graph: GraphReader, embedder: Embedder,
    tracing: TracingClient,
) -> EstimateRunResult:
    quote_request = get_quote_request(session, quote_request_id)
    if quote_request is None:
        raise QuoteRequestNotFound(f"quote request {quote_request_id} not found")

    with tracing.trace("estimate_run", quote_request_id=str(quote_request_id)) as trace:
        ctx = ToolContext(
            session=session, as_of=as_of, graph=graph,
            knowledge=KnowledgeService(session=session, graph=graph, embedder=embedder),
            request_customer_id=quote_request.customer_id, request_sku_ids=_request_sku_ids(quote_request),
            trace=trace,
        )
        state = run_agent(llm_client, ctx, build_request_message(quote_request, as_of))

        draft = state["last_draft"]
        result = EstimateResult(
            status=state["status"], as_of=as_of, draft=draft,
            totals=compute_totals(draft.lines) if draft else None,
            violations=state["violations"], iterations=state["submissions"], reason=state["reason"],
        )
        trace.update(output={"status": result.status, "iterations": result.iterations})
    row = save_estimate_draft(
        session, quote_request_id=quote_request_id, status=result.status,
        draft=draft.model_dump(mode="json") if draft else None,
        violations=[v.model_dump(mode="json") for v in result.violations],
        iterations=result.iterations, reason=result.reason,
    )
    return EstimateRunResult(row=row, result=result)
