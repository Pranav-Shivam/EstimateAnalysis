import uuid
from datetime import date

from pydantic import BaseModel


class EstimateRequest(BaseModel):
    quote_request_id: uuid.UUID
    as_of: date | None = None
