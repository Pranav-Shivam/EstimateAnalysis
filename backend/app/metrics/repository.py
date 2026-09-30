from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.dedupe.models import DedupeVerdictRow
from app.judge.models import JudgeVerdictRow, ReviewItemRow
from app.metrics.schemas import MetricCounts

DUPLICATE_VERDICT = "DUPLICATE_OF"


def _count(session: Session, statement: Select) -> int:
    return session.scalar(statement) or 0


def count_metric_inputs(session: Session) -> MetricCounts:
    distinct_requests = func.count(func.distinct(DedupeVerdictRow.quote_request_id))
    return MetricCounts(
        verdicts_total=_count(session, select(func.count()).select_from(JudgeVerdictRow)),
        verdicts_trusted=_count(
            session, select(func.count()).select_from(JudgeVerdictRow).where(JudgeVerdictRow.trusted.is_(True))
        ),
        review_items_resolved=_count(
            session, select(func.count()).select_from(ReviewItemRow).where(ReviewItemRow.outcome.is_not(None))
        ),
        review_items_corrected=_count(
            session, select(func.count()).select_from(ReviewItemRow).where(ReviewItemRow.outcome == "corrected")
        ),
        requests_compared=_count(session, select(distinct_requests)),
        requests_duplicate=_count(session, select(distinct_requests).where(DedupeVerdictRow.verdict == DUPLICATE_VERDICT)),
        flags_by_dimension=dict(
            session.execute(select(ReviewItemRow.dimension, func.count()).group_by(ReviewItemRow.dimension)).all()
        ),
    )
