from app.metrics.schemas import MetricCounts
from app.metrics.service import metrics_from_counts, ratio


def test_ratio_is_none_not_zero_when_the_denominator_is_zero():
    assert ratio(0, 0) is None
    assert ratio(3, 0) is None


def test_ratio_divides():
    assert ratio(1, 4) == 0.25


def test_empty_counts_give_null_rates():
    metrics = metrics_from_counts(MetricCounts(0, 0, 0, 0, 0, 0, {}))

    assert metrics.auto_send_rate is None
    assert metrics.correction_rate is None
    assert metrics.duplicate_rate is None


def test_rates_follow_the_stated_definitions():
    metrics = metrics_from_counts(MetricCounts(
        verdicts_total=10, verdicts_trusted=7, review_items_resolved=4, review_items_corrected=3,
        requests_compared=5, requests_duplicate=1, flags_by_dimension={},
    ))

    assert metrics.auto_send_rate == 0.7
    assert metrics.correction_rate == 0.75
    assert metrics.duplicate_rate == 0.2
