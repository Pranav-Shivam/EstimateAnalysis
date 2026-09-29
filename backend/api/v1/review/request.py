from typing import Literal

from pydantic import BaseModel


class ResolveReviewItemRequest(BaseModel):
    outcome: Literal["approved", "corrected"]
    correction: dict | None = None
