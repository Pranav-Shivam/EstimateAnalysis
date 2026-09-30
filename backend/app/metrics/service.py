from sqlalchemy.orm import Session

from app.metrics.repository import count_metric_inputs
from app.metrics.schemas import MetricCounts, Metrics


def ratio(numerator: int, denominator: int) -> float | None:
    """None, not 0, when nothing has been measured yet, so a dashboard cannot show a real-looking 0%."""
    return numerator / denominator if denominator else None


def metrics_from_counts(counts: MetricCounts) -> Metrics:
    return Metrics(
        auto_send_rate=ratio(counts.verdicts_trusted, counts.verdicts_total),
        correction_rate=ratio(counts.review_items_corrected, counts.review_items_resolved),
        duplicate_rate=ratio(counts.requests_duplicate, counts.requests_compared),
        counts=counts,
    )


def compute_metrics(session: Session) -> Metrics:
    return metrics_from_counts(count_metric_inputs(session))
