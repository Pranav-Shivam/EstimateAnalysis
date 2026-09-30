import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dedupe.models import DedupeVerdictRow
from app.estimate.models import EstimateDraftRow
from app.intake.models import QuoteRequestRow
from app.judge.models import JudgeVerdictRow, ReviewItemRow


def list_quote_requests(session: Session) -> list[QuoteRequestRow]:
    return list(session.scalars(select(QuoteRequestRow).order_by(QuoteRequestRow.created_at.desc(), QuoteRequestRow.id)))


def estimates_for_requests(session: Session, request_ids: list[uuid.UUID]) -> list[EstimateDraftRow]:
    """Newest first."""
    if not request_ids:
        return []
    return list(session.scalars(
        select(EstimateDraftRow)
        .where(EstimateDraftRow.quote_request_id.in_(request_ids))
        .order_by(EstimateDraftRow.created_at.desc(), EstimateDraftRow.id)
    ))


def verdicts_for_estimates(session: Session, estimate_ids: list[uuid.UUID]) -> list[JudgeVerdictRow]:
    """Newest first, so the first row seen per estimate is its latest verdict."""
    if not estimate_ids:
        return []
    return list(session.scalars(
        select(JudgeVerdictRow)
        .where(JudgeVerdictRow.estimate_id.in_(estimate_ids))
        .order_by(JudgeVerdictRow.created_at.desc(), JudgeVerdictRow.id)
    ))


def review_items_for_estimates(session: Session, estimate_ids: list[uuid.UUID]) -> list[ReviewItemRow]:
    if not estimate_ids:
        return []
    return list(session.scalars(
        select(ReviewItemRow)
        .where(ReviewItemRow.estimate_id.in_(estimate_ids))
        .order_by(ReviewItemRow.created_at, ReviewItemRow.id)
    ))


def dedupe_verdicts_for_requests(session: Session, request_ids: list[uuid.UUID]) -> list[DedupeVerdictRow]:
    if not request_ids:
        return []
    return list(session.scalars(
        select(DedupeVerdictRow)
        .where(DedupeVerdictRow.quote_request_id.in_(request_ids))
        .order_by(DedupeVerdictRow.created_at, DedupeVerdictRow.id)
    ))
