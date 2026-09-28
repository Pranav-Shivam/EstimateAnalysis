import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.dedupe.models import DedupeVerdictRow
from app.intake.models import QuoteRequestRow


def find_blocked_candidates(session: Session, target: QuoteRequestRow) -> list[QuoteRequestRow]:
    conditions = []
    if target.customer_id:
        conditions.append(QuoteRequestRow.customer_id == target.customer_id)
    if target.site_id:
        conditions.append(QuoteRequestRow.site_id == target.site_id)
    if target.contract_id:
        conditions.append(QuoteRequestRow.contract_id == target.contract_id)

    if not conditions:
        return []

    stmt = select(QuoteRequestRow).where(or_(*conditions), QuoteRequestRow.id != target.id)
    return list(session.scalars(stmt))


def save_verdict(
    session: Session, *, quote_request_id: uuid.UUID, candidate_quote_request_id: uuid.UUID,
    verdict: str, content_jaccard: float, style_jaccard: float, signals_fired: list[str],
) -> DedupeVerdictRow:
    row = DedupeVerdictRow(
        id=uuid.uuid4(), quote_request_id=quote_request_id,
        candidate_quote_request_id=candidate_quote_request_id, verdict=verdict,
        content_jaccard=content_jaccard, style_jaccard=style_jaccard, signals_fired=signals_fired,
    )
    session.add(row)
    session.flush()
    return row


def verdicts_for_request(session: Session, quote_request_id: uuid.UUID) -> list[DedupeVerdictRow]:
    return list(session.scalars(
        select(DedupeVerdictRow).where(DedupeVerdictRow.quote_request_id == quote_request_id)
        .order_by(DedupeVerdictRow.created_at, DedupeVerdictRow.id)
    ))


def all_verdict_request_ids(session: Session) -> list[uuid.UUID]:
    return list(session.scalars(select(DedupeVerdictRow.quote_request_id).distinct()))
