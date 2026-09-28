import uuid
from datetime import date

from pydantic import BaseModel

from app.estimate.schemas import EstimateDraft, EstimateStatus, Totals, Violation


class EstimateResponse(BaseModel):
    estimate_id: uuid.UUID
    quote_request_id: uuid.UUID
    status: EstimateStatus
    as_of: date
    draft: EstimateDraft | None
    totals: Totals | None
    violations: list[Violation]
    iterations: int
    reason: str | None
