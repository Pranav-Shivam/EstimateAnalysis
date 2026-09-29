import uuid

from pydantic import BaseModel

from app.judge.schemas import DimensionScore


class ReviewItemResponse(BaseModel):
    dimension: str
    fact: str
    evidence: dict
    line_index: int | None


class JudgeResponse(BaseModel):
    judge_verdict_id: uuid.UUID
    estimate_id: uuid.UUID
    model: str
    dimensions: list[DimensionScore]
    overall_confidence: float
    flagged_dimension: str
    trusted: bool
    review_item: ReviewItemResponse | None
