import math
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.estimate.pricing import predict_price_for_sku
from app.estimate.schemas import DraftLine, EstimateDraft, Violation
from app.graph.reader import GraphReader
from app.reference_data.models import Contract, Sku
from app.reference_data.repository import get_contract, get_customer, get_sku, reference_fingerprint

# Tolerance checks are written as `not diff <= TOL` so a NaN or infinite value fails instead of slipping through.
# Prices are 2-decimal floats the agent copies verbatim from a tool result, so the intended rule is an exact match;
# the tolerance only absorbs float representation noise.
PRICE_TOLERANCE = 1e-9
PCT_TOLERANCE = 1e-9


def check_required_fields(draft: EstimateDraft) -> list[Violation]:
    violations = []
    if draft.customer_id is None:
        violations.append(Violation(guardrail="required_fields", message="customer is not resolved"))
    if not draft.lines:
        violations.append(Violation(guardrail="required_fields", message="draft has no lines"))
    for index, line in enumerate(draft.lines):
        if line.sku_id is None:
            violations.append(Violation(guardrail="required_fields", line_index=index, message="line has no resolved SKU"))
        if line.quantity is None or line.quantity <= 0:
            violations.append(Violation(
                guardrail="required_fields", line_index=index, message="line quantity must be a whole number above 0",
            ))
        if line.unit_price is None or line.price_source is None:
            violations.append(Violation(
                guardrail="required_fields", line_index=index, message="line must have a unit price and a price source",
            ))
        if line.unit_price is not None and not math.isfinite(line.unit_price):
            violations.append(Violation(
                guardrail="required_fields", line_index=index, message="line unit_price must be a finite number",
            ))
        if not math.isfinite(line.discount_pct):
            violations.append(Violation(
                guardrail="required_fields", line_index=index, message="line discount_pct must be a finite number",
            ))
    return violations


def check_customer_identity(session: Session, draft: EstimateDraft, request_customer_id: str | None) -> list[Violation]:
    if draft.customer_id is None:
        return []
    violations = []
    if get_customer(session, draft.customer_id) is None:
        violations.append(Violation(guardrail="customer_identity", message=f"unknown customer {draft.customer_id}"))
    if request_customer_id is not None and draft.customer_id != request_customer_id:
        violations.append(Violation(
            guardrail="customer_identity",
            message=(
                f"draft customer {draft.customer_id} does not match the request's customer {request_customer_id}; "
                f"use {request_customer_id}"
            ),
        ))
    return violations


def check_price_provenance(session: Session, draft: EstimateDraft) -> list[Violation]:
    violations = []
    for index, line in enumerate(draft.lines):
        if line.sku_id is None or line.unit_price is None or line.price_source is None:
            continue
        sku = get_sku(session, line.sku_id)
        if sku is None:
            violations.append(Violation(guardrail="price_provenance", line_index=index, message=f"unknown SKU {line.sku_id}"))
            continue
        message = _provenance_problem(session, line, sku)
        if message:
            violations.append(Violation(guardrail="price_provenance", line_index=index, message=message))
    return violations


def _provenance_problem(session: Session, line: DraftLine, sku: Sku) -> str | None:
    if line.price_source == "list":
        if sku.list_price is None:
            return f"SKU {sku.sku_id} has no list price; its price must come from predict_price"
        if not abs(line.unit_price - sku.list_price) <= PRICE_TOLERANCE:
            return f"unit_price {line.unit_price} does not match list price {sku.list_price} for {sku.sku_id}"
        return None

    if sku.list_price is not None:
        return f"SKU {sku.sku_id} has a list price ({sku.list_price}); it cannot be marked predicted"
    prediction = predict_price_for_sku(session, sku)
    if prediction is None:
        return f"price for {sku.sku_id} cannot be predicted (too few priced peers in its category)"
    if not abs(line.unit_price - prediction.price) <= PRICE_TOLERANCE:
        return f"unit_price {line.unit_price} does not match predicted price {prediction.price} for {sku.sku_id}"
    return None


def check_contract_discount(
    session: Session, draft: EstimateDraft, as_of: date, request_customer_id: str | None,
) -> list[Violation]:
    discounted = [(i, line) for i, line in enumerate(draft.lines) if line.discount_pct != 0]
    if not discounted:
        return []
    if request_customer_id is None:
        return [
            Violation(
                guardrail="contract_discount", line_index=index,
                message=(
                    "discount not allowed: intake did not resolve the customer for this request, "
                    "so a discount cannot be verified"
                ),
            )
            for index, _ in discounted
        ]

    contract = _draft_contract(session, draft)
    violations = []
    for index, line in discounted:
        if contract is None:
            violations.append(Violation(
                guardrail="contract_discount", line_index=index,
                message="discount not allowed: draft has no valid contract for this customer",
            ))
            continue
        sku = get_sku(session, line.sku_id) if line.sku_id else None
        if sku is None:
            continue
        problem = _discount_problem(contract, sku.category, line.discount_pct, as_of)
        if problem:
            violations.append(Violation(guardrail="contract_discount", line_index=index, message=problem))
    return violations


def _draft_contract(session: Session, draft: EstimateDraft) -> Contract | None:
    if draft.customer_id is None or draft.contract_id is None:
        return None
    contract = get_contract(session, draft.contract_id)
    if contract is None or contract.customer_id != draft.customer_id:
        return None
    return contract


def _discount_problem(contract: Contract, category: str, discount_pct: float, as_of: date) -> str | None:
    if category not in contract.covered_categories:
        return f"discount {discount_pct}% not allowed: category {category} is not covered by contract {contract.contract_id}"
    if not (contract.effective_from <= as_of <= contract.effective_to):
        return f"discount not allowed: contract {contract.contract_id} is not active on {as_of.isoformat()}"
    if not abs(discount_pct - contract.discount_pct) <= PCT_TOLERANCE:
        return f"discount {discount_pct}% does not match contract {contract.contract_id} discount {contract.discount_pct}%"
    return None


def run_guardrails(
    session: Session, draft: EstimateDraft, as_of: date, request_customer_id: str | None,
) -> list[Violation]:
    return (
        check_required_fields(draft)
        + check_customer_identity(session, draft, request_customer_id)
        + check_price_provenance(session, draft)
        + check_contract_discount(session, draft, as_of, request_customer_id)
    )


@dataclass(frozen=True)
class GraphCheck:
    violations: list[Violation]
    # SKUs whose replacement chain never reaches a live SKU. A retry cannot fix these, so the run ends for review.
    unreplaceable: list[str]


def graph_is_current(session: Session, reader: GraphReader) -> bool:
    """The graph stores the fingerprint of the reference data it was built from. If Postgres has moved on, the
    graph is stale and must not approve a draft."""
    stored = reader.stored_fingerprint()
    return stored is not None and stored == reference_fingerprint(session)


def check_graph_integrity(reader: GraphReader, draft: EstimateDraft, request_sku_ids: tuple[str, ...]) -> GraphCheck:
    """Discontinued lines, requested SKUs the draft dropped, and missing required parts, all read from the graph.
    Raises GraphError when the graph is unreachable; the caller must treat that as a failure, never as a pass."""
    violations: list[Violation] = []
    unreplaceable: list[str] = []
    present = {line.sku_id for line in draft.lines if line.sku_id is not None}

    def flag_unreplaceable(sku_id: str) -> None:
        if sku_id not in unreplaceable:
            unreplaceable.append(sku_id)

    for index, line in enumerate(draft.lines):
        if line.sku_id is None:
            continue
        chain = reader.sku_chain(line.sku_id)
        if chain is None or not chain.nodes[0].discontinued:
            continue
        if chain.live_end is None:
            flag_unreplaceable(line.sku_id)
        else:
            violations.append(Violation(
                guardrail="graph_integrity", line_index=index,
                message=f"SKU {line.sku_id} is discontinued; quote its live replacement {chain.live_end.sku_id} instead",
            ))

    # The request's SKUs were resolved by intake code, not written by the model, so they anchor what must be quoted.
    for requested in dict.fromkeys(request_sku_ids):
        chain = reader.sku_chain(requested)
        if chain is None:
            continue
        if chain.live_end is None:
            flag_unreplaceable(requested)
        elif chain.live_end.sku_id not in present:
            violations.append(Violation(
                guardrail="graph_integrity",
                message=f"the request asks for {requested}; the draft must quote {chain.live_end.sku_id}",
            ))

    # Parts the agent adds are lines too, so the next submission checks their requirements in turn.
    for sku_id in sorted(present):
        chain = reader.sku_chain(sku_id)
        if chain is None or chain.nodes[0].discontinued:
            continue
        for part in reader.required_parts(sku_id):
            part_chain = reader.sku_chain(part.sku_id)
            if part_chain is None:
                continue
            if part_chain.live_end is None:
                flag_unreplaceable(part.sku_id)
            elif part_chain.live_end.sku_id not in present:
                violations.append(Violation(
                    guardrail="graph_integrity",
                    message=f"{sku_id} requires {part.sku_id}; the draft must include {part_chain.live_end.sku_id}",
                ))

    return GraphCheck(violations=violations, unreplaceable=unreplaceable)
