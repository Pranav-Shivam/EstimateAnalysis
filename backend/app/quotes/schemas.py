import uuid
from dataclasses import dataclass
from datetime import datetime

from app.estimate.schemas import Totals


@dataclass(frozen=True)
class QuoteSummary:
    quote_request_id: uuid.UUID
    case_id: str | None
    customer_id: str | None
    created_at: datetime
    estimate_count: int
    latest_estimate_status: str | None
    latest_trusted: bool | None
    open_review_items: int
    is_duplicate: bool


@dataclass(frozen=True)
class SkuInfo:
    name: str
    category: str
    discontinued: bool


@dataclass(frozen=True)
class DedupeVerdictView:
    candidate_quote_request_id: uuid.UUID
    verdict: str
    content_jaccard: float
    style_jaccard: float
    signals_fired: list[str]
    created_at: datetime


@dataclass(frozen=True)
class JudgeVerdictView:
    id: uuid.UUID
    model: str
    dimensions: list[dict]
    overall_confidence: float
    flagged_dimension: str
    trusted: bool
    created_at: datetime


@dataclass(frozen=True)
class ReviewItemView:
    id: uuid.UUID
    dimension: str
    fact: str
    evidence: dict
    line_index: int | None
    status: str
    outcome: str | None
    correction: dict | None
    resolved_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class EstimateView:
    estimate_id: uuid.UUID
    status: str
    draft: dict | None
    totals: Totals | None
    violations: list[dict]
    iterations: int
    reason: str | None
    created_at: datetime
    judge_verdict: JudgeVerdictView | None
    review_items: list[ReviewItemView]


@dataclass(frozen=True)
class QuoteDetail:
    quote_request_id: uuid.UUID
    case_id: str | None
    customer_id: str | None
    site_id: str | None
    contract_id: str | None
    raw_email_text: str
    parsed_json: dict
    created_at: datetime
    dedupe_verdicts: list[DedupeVerdictView]
    estimates: list[EstimateView]
    skus: dict[str, SkuInfo]
