import math
import uuid
from typing import Literal

from pydantic import BaseModel

from app.judge.models import ReviewItemRow
from app.reference_data.repository import get_sku

DimensionName = Literal["contract_discount", "graph_completion", "price_provenance"]
# The exact fields, and their types, of a correction per judge dimension (spec decision 4).
CORRECTION_FIELDS: dict[str, dict[str, type | tuple[type, ...]]] = {
    "price_provenance": {"sku_id": str, "corrected_unit_price": (int, float)},
    "graph_completion": {"sku_id": str, "required_sku_id": str},
    "contract_discount": {"contract_id": str, "category": str},
}
RESOLVABLE_DIMENSIONS = frozenset(CORRECTION_FIELDS)


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


def _check_shape(dimension: str, correction: dict | None) -> None:
    fields = CORRECTION_FIELDS[dimension]
    if not isinstance(correction, dict):
        raise InvalidCorrection(f"a corrected {dimension} review item needs a correction with {sorted(fields)}")
    if set(correction) != set(fields):
        raise InvalidCorrection(f"a {dimension} correction takes exactly {sorted(fields)}, got {sorted(correction)}")
    for key, kind in fields.items():
        value = correction[key]
        # bool is an int subclass, and True is not a price.
        if isinstance(value, bool) or not isinstance(value, kind):
            raise InvalidCorrection(f"{key} has the wrong type: {value!r}")


def _check_flagged_sku(correction: dict, lines: list[dict]) -> None:
    if correction["sku_id"] not in {line["sku_id"] for line in lines}:
        raise InvalidCorrection(f"sku_id {correction['sku_id']!r} was not flagged by this review item")


def validate_correction(session, dimension: str, correction: dict | None, evidence: dict | None = None) -> None:
    """A bad correction must fail the resolve request, never the background job, and can never invent a fact about
    something the judge did not flag."""
    if dimension not in RESOLVABLE_DIMENSIONS:
        raise InvalidCorrection(f"dimension {dimension!r} has no consolidation handler")
    _check_shape(dimension, correction)
    lines = (evidence or {}).get("lines", [])

    if dimension == "price_provenance":
        _check_flagged_sku(correction, lines)
        price = correction["corrected_unit_price"]
        if not math.isfinite(price) or price <= 0:
            raise InvalidCorrection(f"corrected_unit_price must be a positive amount, got {price!r}")
    elif dimension == "graph_completion":
        _check_flagged_sku(correction, lines)
        if correction["required_sku_id"] == correction["sku_id"]:
            raise InvalidCorrection("a SKU cannot require itself")
        if get_sku(session, correction["required_sku_id"]) is None:
            raise InvalidCorrection(f"required_sku_id {correction['required_sku_id']!r} is not a known SKU")
    elif dimension == "contract_discount":
        contract_lines = [line for line in lines if line.get("contract_id") == correction["contract_id"]]
        if not contract_lines:
            raise InvalidCorrection(f"contract_id {correction['contract_id']!r} was not flagged by this review item")
        # The only coverage a reviewer can confirm is the category of a line the judge doubted under that contract.
        flagged_categories = {sku.category for line in contract_lines if (sku := get_sku(session, line["sku_id"]))}
        if correction["category"] not in flagged_categories:
            raise InvalidCorrection(
                f"category {correction['category']!r} is not the category of a line flagged under this contract"
            )
