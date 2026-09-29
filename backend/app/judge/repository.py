import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.judge.models import JudgeVerdictRow, ReviewItemRow


def save_judge_verdict(
    session: Session, *, estimate_id: uuid.UUID, model: str, dimensions: list[dict], overall_confidence: float,
    flagged_dimension: str, trusted: bool,
) -> JudgeVerdictRow:
    row = JudgeVerdictRow(
        id=uuid.uuid4(), estimate_id=estimate_id, model=model, dimensions=dimensions,
        overall_confidence=overall_confidence, flagged_dimension=flagged_dimension, trusted=trusted,
    )
    session.add(row)
    session.flush()
    return row


def save_review_item(
    session: Session, *, judge_verdict_id: uuid.UUID, estimate_id: uuid.UUID, dimension: str, fact: str,
    evidence: dict, line_index: int | None,
) -> ReviewItemRow:
    row = ReviewItemRow(
        id=uuid.uuid4(), judge_verdict_id=judge_verdict_id, estimate_id=estimate_id, dimension=dimension,
        fact=fact, evidence=evidence, line_index=line_index, status="open",
    )
    session.add(row)
    session.flush()
    return row


def get_judge_verdict(session: Session, verdict_id: uuid.UUID) -> JudgeVerdictRow | None:
    return session.get(JudgeVerdictRow, verdict_id)


def list_open_review_items(session: Session) -> list[ReviewItemRow]:
    return list(
        session.scalars(
            select(ReviewItemRow)
            .where(ReviewItemRow.status == "open")
            .order_by(ReviewItemRow.created_at, ReviewItemRow.id)
        )
    )
