import uuid
from datetime import datetime

from pydantic import BaseModel


class ReviewItemListResponse(BaseModel):
    id: uuid.UUID
    estimate_id: uuid.UUID
    dimension: str
    fact: str
    evidence: dict
    line_index: int | None
    status: str
    created_at: datetime


class ResolveReviewItemResponse(BaseModel):
    id: uuid.UUID
    status: str
    outcome: str
    correction: dict | None
    consolidation_enqueued: bool
