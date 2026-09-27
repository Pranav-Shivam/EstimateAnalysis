import uuid

from pydantic import BaseModel


class DedupeVerdictResponse(BaseModel):
    candidate_quote_request_id: uuid.UUID
    verdict: str
    content_jaccard: float
    style_jaccard: float
    signals_fired: list[str]


class DedupeResponse(BaseModel):
    quote_request_id: uuid.UUID
    verdicts: list[DedupeVerdictResponse]
