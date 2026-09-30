from pydantic import BaseModel


class MetricCountsResponse(BaseModel):
    verdicts_total: int
    verdicts_trusted: int
    review_items_resolved: int
    review_items_corrected: int
    requests_compared: int
    requests_duplicate: int
    flags_by_dimension: dict[str, int]


class MetricsResponse(BaseModel):
    auto_send_rate: float | None
    correction_rate: float | None
    duplicate_rate: float | None
    counts: MetricCountsResponse
