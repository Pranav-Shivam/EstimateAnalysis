import uuid
from datetime import datetime

from pydantic import BaseModel

from app.estimate.schemas import EstimateDraft, Totals, Violation
from app.judge.schemas import DimensionScore


class QuoteSummaryResponse(BaseModel):
    quote_request_id: uuid.UUID
    case_id: str | None
    customer_id: str | None
    created_at: datetime
    estimate_count: int
    latest_estimate_status: str | None
    latest_trusted: bool | None
    open_review_items: int
    is_duplicate: bool


class QuoteSkuInfoResponse(BaseModel):
    name: str
    category: str
    discontinued: bool


class QuoteDedupeVerdictResponse(BaseModel):
    candidate_quote_request_id: uuid.UUID
    verdict: str
    content_jaccard: float
    style_jaccard: float
    signals_fired: list[str]
    created_at: datetime


class QuoteJudgeVerdictResponse(BaseModel):
    id: uuid.UUID
    model: str
    dimensions: list[DimensionScore]
    overall_confidence: float
    flagged_dimension: str
    trusted: bool
    created_at: datetime


class QuoteReviewItemResponse(BaseModel):
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


class QuoteEstimateResponse(BaseModel):
    estimate_id: uuid.UUID
    status: str
    draft: EstimateDraft | None
    totals: Totals | None
    violations: list[Violation]
    iterations: int
    reason: str | None
    created_at: datetime
    judge_verdict: QuoteJudgeVerdictResponse | None
    review_items: list[QuoteReviewItemResponse]


class QuoteDetailResponse(BaseModel):
    quote_request_id: uuid.UUID
    case_id: str | None
    customer_id: str | None
    site_id: str | None
    contract_id: str | None
    raw_email_text: str
    parsed_json: dict
    created_at: datetime
    dedupe_verdicts: list[QuoteDedupeVerdictResponse]
    estimates: list[QuoteEstimateResponse]
    skus: dict[str, QuoteSkuInfoResponse]
