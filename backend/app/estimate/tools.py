import inspect
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from rapidfuzz import fuzz, process
from sqlalchemy.orm import Session

from app.estimate.pricing import PEER_MIN, predict_price_for_sku
from app.estimate.schemas import EstimateDraft
from app.reference_data.models import Customer, Sku
from app.reference_data.repository import (
    all_customers, all_skus, contracts_for_customer, get_customer, get_sku, latest_realized_price, required_sku_ids,
)

# Looser than intake's 90: here the agent reads the candidate list and judges, it does not auto-resolve.
CUSTOMER_MATCH_THRESHOLD = 80
SKU_SEARCH_CUTOFF = 60
SKU_SEARCH_LIMIT = 5


@dataclass(frozen=True)
class ToolContext:
    session: Session
    as_of: date


def _sku_entry(session: Session, sku: Sku) -> dict:
    return {
        "sku_id": sku.sku_id, "name": sku.name, "category": sku.category, "list_price": sku.list_price,
        "last_realized_price": latest_realized_price(session, sku.sku_id),
        "discontinued": sku.discontinued, "in_stock": sku.in_stock,
    }


def _customer_entry(ctx: ToolContext, customer: Customer) -> dict:
    contracts = contracts_for_customer(ctx.session, customer.customer_id)
    return {
        "customer_id": customer.customer_id, "name": customer.name, "account_tier": customer.account_tier,
        "contracts": [
            {
                "contract_id": c.contract_id, "discount_pct": c.discount_pct,
                "covered_categories": list(c.covered_categories),
                "effective_from": c.effective_from.isoformat(), "effective_to": c.effective_to.isoformat(),
                "active_on_as_of": c.effective_from <= ctx.as_of <= c.effective_to,
            }
            for c in contracts
        ],
    }


def lookup_customer(ctx: ToolContext, *, query: str) -> dict:
    exact = get_customer(ctx.session, query)
    if exact is not None:
        customers = [exact]
    else:
        names = {c.customer_id: c.name for c in all_customers(ctx.session)}
        hits = process.extract(
            query, names, scorer=fuzz.token_sort_ratio, processor=str.lower, limit=3,
            score_cutoff=CUSTOMER_MATCH_THRESHOLD,
        )
        customers = [get_customer(ctx.session, key) for _, _, key in hits]
    return {"matches": [_customer_entry(ctx, c) for c in customers]}


def search_price_book(ctx: ToolContext, *, query: str) -> dict:
    exact = get_sku(ctx.session, query)
    if exact is not None:
        skus = [exact]
    else:
        names = {s.sku_id: s.name for s in all_skus(ctx.session)}
        hits = process.extract(
            query, names, scorer=fuzz.WRatio, processor=str.lower, limit=SKU_SEARCH_LIMIT,
            score_cutoff=SKU_SEARCH_CUTOFF,
        )
        skus = [get_sku(ctx.session, key) for _, _, key in hits]
    return {"results": [_sku_entry(ctx.session, s) for s in skus]}


def check_stock(ctx: ToolContext, *, sku_id: str) -> dict:
    sku = get_sku(ctx.session, sku_id)
    if sku is None:
        return {"error": f"unknown SKU {sku_id}"}
    return {"sku_id": sku.sku_id, "in_stock": sku.in_stock, "discontinued": sku.discontinued}


def get_related_parts(ctx: ToolContext, *, sku_id: str) -> dict:
    sku = get_sku(ctx.session, sku_id)
    if sku is None:
        return {"error": f"unknown SKU {sku_id}"}
    replacement = get_sku(ctx.session, sku.replaced_by) if sku.replaced_by else None
    required = [get_sku(ctx.session, required_id) for required_id in required_sku_ids(ctx.session, sku_id)]
    return {
        "sku_id": sku.sku_id,
        "replacement": _sku_entry(ctx.session, replacement) if replacement else None,
        "required_parts": [_sku_entry(ctx.session, part) for part in required],
    }


def predict_price(ctx: ToolContext, *, sku_id: str) -> dict:
    sku = get_sku(ctx.session, sku_id)
    if sku is None:
        return {"error": f"unknown SKU {sku_id}"}
    if sku.list_price is not None:
        return {"error": f"SKU {sku_id} has a list price; use search_price_book instead of predicting"}
    prediction = predict_price_for_sku(ctx.session, sku)
    if prediction is None:
        return {"error": f"fewer than {PEER_MIN} priced peers in category {sku.category}; cannot predict"}
    return {
        "sku_id": sku_id, "price_source": "predicted", "predicted_price": prediction.price,
        "low": prediction.low, "high": prediction.high, "peer_count": prediction.peer_count,
    }


TOOL_HANDLERS: dict[str, Callable[..., dict]] = {
    "lookup_customer": lookup_customer,
    "search_price_book": search_price_book,
    "check_stock": check_stock,
    "get_related_parts": get_related_parts,
    "predict_price": predict_price,
}


def handle_tool(ctx: ToolContext, name: str, arguments: dict) -> dict:
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return {"error": f"unknown tool {name}"}
    try:
        inspect.signature(handler).bind(ctx, **arguments)
    except TypeError as exc:
        return {"error": f"bad arguments for {name}: {exc}"}
    # Every tool parameter is a string. A wrong-typed value would reach a text column in Postgres, which aborts
    # the whole transaction and poisons the session for the rest of the run.
    for arg_name, value in arguments.items():
        if not isinstance(value, str):
            return {"error": f"bad arguments for {name}: {arg_name} must be a string"}
    return handler(ctx, **arguments)


def _function_spec(name: str, description: str, parameters: dict) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}


def _string_param(name: str, description: str) -> dict:
    return {"type": "object", "properties": {name: {"type": "string", "description": description}}, "required": [name]}


TOOL_SPECS: list[dict] = [
    _function_spec(
        "lookup_customer",
        "Find a customer by id or name. Returns matches with their contracts (discount_pct, covered_categories, "
        "effective dates, and whether the contract is active on the quote date).",
        _string_param("query", "customer id (CUST-....) or customer name"),
    ),
    _function_spec(
        "search_price_book",
        "Find SKUs by id or name. Returns list_price (null means unpriced), last realized price, discontinued and "
        "in_stock flags.",
        _string_param("query", "SKU id (SKU-....) or product name as written in the email"),
    ),
    _function_spec("check_stock", "Check whether a SKU is in stock and whether it is discontinued.",
                   _string_param("sku_id", "SKU id")),
    _function_spec(
        "get_related_parts",
        "For a SKU, return its replacement (if discontinued) and the parts it requires.",
        _string_param("sku_id", "SKU id"),
    ),
    _function_spec(
        "predict_price",
        "Estimate a price for a SKU that has no list price, from same-category peers. The result is a prediction, "
        "not a looked-up price; the draft line must use price_source 'predicted' and this exact predicted_price.",
        _string_param("sku_id", "SKU id of an unpriced SKU"),
    ),
    _function_spec(
        "submit_draft",
        "Submit the finished draft estimate for validation. Call this when the draft is ready, and again with a "
        "corrected draft if validation reports violations.",
        EstimateDraft.model_json_schema(),
    ),
]
