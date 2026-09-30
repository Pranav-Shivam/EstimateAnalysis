import uuid
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.judge.models import EvalCaseRow, JudgeVerdictRow, ReviewItemRow
from app.judge.schemas import EvalCase


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


def list_review_items(session: Session, status: Literal["open", "resolved", "all"] = "open") -> list[ReviewItemRow]:
    statement = select(ReviewItemRow).order_by(ReviewItemRow.created_at, ReviewItemRow.id)
    if status == "open":
        statement = statement.where(ReviewItemRow.status == "open")
    elif status == "resolved":
        statement = statement.where(ReviewItemRow.status != "open")
    return list(session.scalars(statement))


def lock_review_item(session: Session, review_item_id: uuid.UUID) -> ReviewItemRow | None:
    """SELECT ... FOR UPDATE, held until the transaction ends, and always a fresh read: a caller that checks the
    row's status and then changes it must not race another transaction doing the same."""
    return session.get(ReviewItemRow, review_item_id, with_for_update=True, populate_existing=True)


def next_eval_case_id(session: Session) -> str:
    count = session.scalar(select(func.count()).select_from(EvalCaseRow))
    return f"rc-{count + 1:04d}"


def save_eval_case(session: Session, case: EvalCase) -> EvalCaseRow:
    row = EvalCaseRow(
        id=uuid.uuid4(), source_review_item_id=case.source_review_item_id, case_id=case.case_id, label=case.label,
        estimate_status=case.estimate_status, evidence=case.evidence,
    )
    session.add(row)
    session.flush()
    return row
