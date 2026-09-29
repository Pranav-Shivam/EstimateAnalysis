import uuid
from typing import Literal

from pydantic import BaseModel

DimensionName = Literal["contract_discount", "graph_completion", "price_provenance"]


class DimensionScore(BaseModel):
    name: DimensionName
    score: float
    rationale: str
    evidence: list[dict]


class JudgeVerdict(BaseModel):
    estimate_id: uuid.UUID
    model: str
    dimensions: list[DimensionScore]
    overall_confidence: float
    flagged_dimension: str
    trusted: bool


class ReviewItem(BaseModel):
    dimension: str
    fact: str
    evidence: dict
    line_index: int | None
