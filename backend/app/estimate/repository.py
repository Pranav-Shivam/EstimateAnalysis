import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.estimate.models import EstimateDraftRow


def save_estimate_draft(
    session: Session, *, quote_request_id: uuid.UUID, status: str, draft: dict | None, violations: list[dict],
    iterations: int, reason: str | None,
) -> EstimateDraftRow:
    row = EstimateDraftRow(
        id=uuid.uuid4(), quote_request_id=quote_request_id, status=status, draft=draft, violations=violations,
        iterations=iterations, reason=reason,
    )
    session.add(row)
    session.flush()
    return row


def get_estimate_draft(session: Session, estimate_id: uuid.UUID) -> EstimateDraftRow | None:
    return session.get(EstimateDraftRow, estimate_id)


def all_estimate_draft_ids(session: Session) -> list[uuid.UUID]:
    return list(session.scalars(select(EstimateDraftRow.id).order_by(EstimateDraftRow.created_at, EstimateDraftRow.id)))


def previous_estimate_draft(session: Session, row: EstimateDraftRow) -> EstimateDraftRow | None:
    """The latest draft for the same quote request created strictly before this one. Equal timestamps (one
    transaction stamps every row alike) are not ordered, so they do not supersede each other."""
    return session.scalars(
        select(EstimateDraftRow)
        .where(EstimateDraftRow.quote_request_id == row.quote_request_id, EstimateDraftRow.created_at < row.created_at)
        .order_by(EstimateDraftRow.created_at.desc())
        .limit(1)
    ).first()


def quote_request_ids_for_estimates(session: Session, estimate_ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    if not estimate_ids:
        return {}
    rows = session.execute(
        select(EstimateDraftRow.id, EstimateDraftRow.quote_request_id).where(EstimateDraftRow.id.in_(estimate_ids))
    )
    return {estimate_id: quote_request_id for estimate_id, quote_request_id in rows}
