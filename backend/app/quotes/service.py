import uuid
from collections import Counter, defaultdict

from sqlalchemy.orm import Session

from app.estimate.helper import compute_totals
from app.estimate.models import EstimateDraftRow
from app.estimate.schemas import EstimateDraft
from app.intake.repository import get_quote_request
from app.judge.models import JudgeVerdictRow, ReviewItemRow
from app.quotes.repository import (
    dedupe_verdicts_for_requests, estimates_for_requests, list_quote_requests, review_items_for_estimates,
    verdicts_for_estimates,
)
from app.quotes.schemas import (
    DedupeVerdictView, EstimateView, JudgeVerdictView, QuoteDetail, QuoteSummary, ReviewItemView, SkuInfo,
)
from app.reference_data.repository import skus_by_ids

DUPLICATE_VERDICT = "DUPLICATE_OF"
_SINGLE_SKU_KEYS = ("sku_id", "live_sku_id")
_SKU_LIST_KEYS = ("required_part_ids", "missing_required_part_ids")


class QuoteNotFound(Exception):
    pass


def _latest_verdict_by_estimate(verdicts: list[JudgeVerdictRow]) -> dict[uuid.UUID, JudgeVerdictRow]:
    latest: dict[uuid.UUID, JudgeVerdictRow] = {}
    for verdict in verdicts:  # newest first
        latest.setdefault(verdict.estimate_id, verdict)
    return latest


def _group_by_request(estimates: list[EstimateDraftRow]) -> dict[uuid.UUID, list[EstimateDraftRow]]:
    grouped: dict[uuid.UUID, list[EstimateDraftRow]] = defaultdict(list)
    for estimate in estimates:
        grouped[estimate.quote_request_id].append(estimate)
    return grouped


def list_quotes(session: Session) -> list[QuoteSummary]:
    requests = list_quote_requests(session)
    request_ids = [request.id for request in requests]
    by_request = _group_by_request(estimates_for_requests(session, request_ids))
    estimate_ids = [estimate.id for rows in by_request.values() for estimate in rows]
    latest_verdict = _latest_verdict_by_estimate(verdicts_for_estimates(session, estimate_ids))
    open_items = Counter(
        item.estimate_id for item in review_items_for_estimates(session, estimate_ids) if item.status == "open"
    )
    duplicates = {
        verdict.quote_request_id
        for verdict in dedupe_verdicts_for_requests(session, request_ids)
        if verdict.verdict == DUPLICATE_VERDICT
    }

    summaries = []
    for request in requests:
        estimates = by_request.get(request.id, [])
        latest = estimates[0] if estimates else None
        verdict = latest_verdict.get(latest.id) if latest else None
        summaries.append(QuoteSummary(
            quote_request_id=request.id, case_id=request.case_id, customer_id=request.customer_id,
            created_at=request.created_at, estimate_count=len(estimates),
            latest_estimate_status=latest.status if latest else None,
            latest_trusted=verdict.trusted if verdict else None,
            open_review_items=sum(open_items[estimate.id] for estimate in estimates),
            is_duplicate=request.id in duplicates,
        ))
    return summaries


def _collect_sku_ids(node, found: set[str]) -> None:
    """Every SKU id an estimate or a review item's evidence mentions, wherever it is nested."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _SINGLE_SKU_KEYS and isinstance(value, str):
                found.add(value)
            elif key in _SKU_LIST_KEYS and isinstance(value, list):
                found.update(part for part in value if isinstance(part, str))
            else:
                _collect_sku_ids(value, found)
    elif isinstance(node, list):
        for child in node:
            _collect_sku_ids(child, found)


def _estimate_view(
    estimate: EstimateDraftRow, verdict: JudgeVerdictRow | None, items: list[ReviewItemRow],
) -> EstimateView:
    draft = EstimateDraft.model_validate(estimate.draft) if estimate.draft else None
    return EstimateView(
        estimate_id=estimate.id, status=estimate.status, draft=estimate.draft,
        totals=compute_totals(draft.lines) if draft else None, violations=estimate.violations,
        iterations=estimate.iterations, reason=estimate.reason, created_at=estimate.created_at,
        judge_verdict=None if verdict is None else JudgeVerdictView(
            id=verdict.id, model=verdict.model, dimensions=verdict.dimensions,
            overall_confidence=verdict.overall_confidence, flagged_dimension=verdict.flagged_dimension,
            trusted=verdict.trusted, created_at=verdict.created_at,
        ),
        review_items=[
            ReviewItemView(
                id=item.id, dimension=item.dimension, fact=item.fact, evidence=item.evidence,
                line_index=item.line_index, status=item.status, outcome=item.outcome, correction=item.correction,
                resolved_at=item.resolved_at, created_at=item.created_at,
            )
            for item in items
        ],
    )


def get_quote_detail(session: Session, quote_request_id: uuid.UUID) -> QuoteDetail:
    request = get_quote_request(session, quote_request_id)
    if request is None:
        raise QuoteNotFound(f"quote request {quote_request_id} not found")

    estimates = estimates_for_requests(session, [request.id])
    estimate_ids = [estimate.id for estimate in estimates]
    latest_verdict = _latest_verdict_by_estimate(verdicts_for_estimates(session, estimate_ids))
    items_by_estimate: dict[uuid.UUID, list[ReviewItemRow]] = defaultdict(list)
    for item in review_items_for_estimates(session, estimate_ids):
        items_by_estimate[item.estimate_id].append(item)

    sku_ids: set[str] = set()
    for estimate in estimates:
        _collect_sku_ids(estimate.draft, sku_ids)
        for item in items_by_estimate[estimate.id]:
            _collect_sku_ids(item.evidence, sku_ids)

    return QuoteDetail(
        quote_request_id=request.id, case_id=request.case_id, customer_id=request.customer_id,
        site_id=request.site_id, contract_id=request.contract_id, raw_email_text=request.raw_email_text,
        parsed_json=request.parsed_json, created_at=request.created_at,
        dedupe_verdicts=[
            DedupeVerdictView(
                candidate_quote_request_id=verdict.candidate_quote_request_id, verdict=verdict.verdict,
                content_jaccard=verdict.content_jaccard, style_jaccard=verdict.style_jaccard,
                signals_fired=list(verdict.signals_fired), created_at=verdict.created_at,
            )
            for verdict in dedupe_verdicts_for_requests(session, [request.id])
        ],
        estimates=[
            _estimate_view(estimate, latest_verdict.get(estimate.id), items_by_estimate[estimate.id])
            for estimate in estimates
        ],
        skus={
            sku.sku_id: SkuInfo(name=sku.name, category=sku.category, discontinued=sku.discontinued)
            for sku in skus_by_ids(session, sku_ids)
        },
    )
