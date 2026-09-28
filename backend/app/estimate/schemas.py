from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.estimate.constant import MAX_LINE_QUANTITY

PriceSource = Literal["list", "predicted"]
AdjustmentKind = Literal["substituted", "added_required", "discount_removed", "quantity_assumed"]
EstimateStatus = Literal["ready", "needs_review"]


class DraftLine(BaseModel):
    sku_id: str | None = None
    quantity: int | None = Field(default=None, le=MAX_LINE_QUANTITY)
    unit_price: float | None = None
    price_source: PriceSource | None = None
    discount_pct: float = 0.0


class Adjustment(BaseModel):
    kind: AdjustmentKind
    sku_id: str | None = None
    detail: str


class EstimateDraft(BaseModel):
    customer_id: str | None = None
    contract_id: str | None = None
    lines: list[DraftLine]
    adjustments: list[Adjustment] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class Violation(BaseModel):
    guardrail: str
    line_index: int | None = None
    message: str


class Totals(BaseModel):
    list_total: float
    discount_total: float
    net_total: float


class EstimateResult(BaseModel):
    status: EstimateStatus
    as_of: date
    draft: EstimateDraft | None = None
    totals: Totals | None = None
    violations: list[Violation] = Field(default_factory=list)
    iterations: int
    reason: str | None = None
