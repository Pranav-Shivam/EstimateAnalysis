import uuid

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
