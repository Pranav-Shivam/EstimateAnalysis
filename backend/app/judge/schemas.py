import uuid
from typing import Literal

from pydantic import BaseModel

from app.judge.models import ReviewItemRow
from app.reference_data.repository import get_sku

DimensionName = Literal["contract_discount", "graph_completion", "price_provenance"]
RESOLVABLE_DIMENSIONS = frozenset({"price_provenance", "graph_completion", "contract_discount"})


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


class InvalidCorrection(Exception):
    pass


class EvalCase(BaseModel):
    case_id: str
    label: Literal["trust", "escalate"]
    estimate_status: str
    evidence: list[dict]
    source_review_item_id: uuid.UUID


def build_eval_case(row: ReviewItemRow, outcome: str, case_id: str) -> EvalCase:
    return EvalCase(
        case_id=case_id, label="trust" if outcome == "approved" else "escalate",
        estimate_status="ready", evidence=row.evidence["lines"], source_review_item_id=row.id,
    )


def validate_correction(session, dimension: str, correction: dict, evidence: dict | None = None) -> None:
    if dimension not in RESOLVABLE_DIMENSIONS:
        raise InvalidCorrection(f"dimension {dimension!r} has no consolidation handler")
    lines = (evidence or {}).get("lines", [])
    line_sku_ids = {line["sku_id"] for line in lines}

    if dimension == "price_provenance":
        if correction.get("sku_id") not in line_sku_ids:
            raise InvalidCorrection(f"sku_id {correction.get('sku_id')!r} was not flagged by this review item")
    elif dimension == "graph_completion":
        if correction.get("sku_id") not in line_sku_ids:
            raise InvalidCorrection(f"sku_id {correction.get('sku_id')!r} was not flagged by this review item")
        if get_sku(session, correction.get("required_sku_id")) is None:
            raise InvalidCorrection(f"required_sku_id {correction.get('required_sku_id')!r} is not a known SKU")
    elif dimension == "contract_discount":
        contract_ids = {line.get("contract_id") for line in lines}
        if correction.get("contract_id") not in contract_ids:
            raise InvalidCorrection(f"contract_id {correction.get('contract_id')!r} was not flagged by this review item")
