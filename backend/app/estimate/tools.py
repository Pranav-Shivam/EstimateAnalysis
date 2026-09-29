import inspect
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.estimate.pricing import PEER_MIN, predict_price_for_sku
from app.estimate.schemas import EstimateDraft
from app.graph.reader import GraphReader
from app.graph.schemas import ChainNode, ContractCoverage, RequiredPart
from app.reference_data.models import Customer, Sku
from app.reference_data.repository import contracts_for_customer, get_sku, latest_realized_price
from app.reference_data.search import find_customers, find_skus
from app.retrieval.service import KnowledgeService
from app.retrieval.vector import EmbeddingsNotBuilt
from core.graph.client import GraphError
from core.llm.openai_embedding_client import EmbeddingError


@dataclass(frozen=True)
class ToolContext:
    session: Session
    as_of: date
    graph: GraphReader
    knowledge: KnowledgeService
    # The customer intake resolved for the quote request. Guardrails anchor on it because the draft's own
    # customer_id is written by the model and cannot vouch for itself.
    request_customer_id: str | None
    # The SKUs intake resolved from the request lines by code. The graph guardrail anchors on them for the same
    # reason: the draft's own lines are model output, so dropping a requested line must not pass unnoticed.
    request_sku_ids: tuple[str, ...]


def _sku_entry(session: Session, sku: Sku) -> dict:
    return {
        "sku_id": sku.sku_id, "name": sku.name, "category": sku.category, "list_price": sku.list_price,
        "last_realized_price": latest_realized_price(session, sku.sku_id),
        "discontinued": sku.discontinued, "in_stock": sku.in_stock,
    }


def _part_entry(part: ChainNode | RequiredPart) -> dict:
    return {"sku_id": part.sku_id, "name": part.name, "discontinued": part.discontinued, "in_stock": part.in_stock}


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
    return {"matches": [_customer_entry(ctx, c) for c in find_customers(ctx.session, query)]}


def search_price_book(ctx: ToolContext, *, query: str) -> dict:
    return {"results": [_sku_entry(ctx.session, s) for s in find_skus(ctx.session, query)]}


def check_stock(ctx: ToolContext, *, sku_id: str) -> dict:
    sku = get_sku(ctx.session, sku_id)
    if sku is None:
        return {"error": f"unknown SKU {sku_id}"}
    return {"sku_id": sku.sku_id, "in_stock": sku.in_stock, "discontinued": sku.discontinued}


def get_related_parts(ctx: ToolContext, *, sku_id: str) -> dict:
    try:
        chain = ctx.graph.sku_chain(sku_id)
        if chain is None:
            return {"error": f"unknown SKU {sku_id}"}
        live = chain.live_end
        required = ctx.graph.required_parts(live.sku_id) if live is not None else []
    except GraphError as exc:
        return {"error": f"knowledge graph unavailable: {exc}"}
    return {
        "sku_id": sku_id,
        "discontinued": chain.nodes[0].discontinued,
        "replacement_chain": [node.sku_id for node in chain.nodes[1:]],
        "replacement": _part_entry(live) if live is not None and live.sku_id != sku_id else None,
        "live_sku_id": live.sku_id if live is not None else None,
        "required_parts": [_part_entry(part) for part in required],
        "evidence_path": chain.evidence_path,
    }


def _coverage_reason(coverage: ContractCoverage, as_of: date) -> str:
    category, contract = coverage.sku_category, coverage.contract_id
    if not coverage.covered:
        covered = ", ".join(coverage.covered_categories) or "no categories"
        return f"category {category} is not covered by contract {contract}; it covers {covered}"
    if not coverage.active_on_as_of:
        return f"category {category} is covered by contract {contract} but the contract is not active on {as_of.isoformat()}"
    return f"category {category} is covered by contract {contract} and the contract is active on {as_of.isoformat()}"


def check_contract_coverage(ctx: ToolContext, *, customer_id: str, sku_id: str) -> dict:
    try:
        coverage = ctx.graph.contract_coverage(customer_id, sku_id, ctx.as_of)
    except GraphError as exc:
        return {"error": f"knowledge graph unavailable: {exc}"}
    if coverage and coverage[0].sku_category is None:
        return {"error": f"unknown SKU {sku_id}"}
    return {
        "customer_id": customer_id,
        "sku_id": sku_id,
        "sku_category": coverage[0].sku_category if coverage else None,
        "contracts": [
            {
                "contract_id": c.contract_id, "discount_pct": c.discount_pct, "covered": c.covered,
                "active_on_as_of": c.active_on_as_of, "discount_applies": c.covered and c.active_on_as_of,
                "reason": _coverage_reason(c, ctx.as_of),
                "evidence_path": (
                    [customer_id, "HOLDS", c.contract_id, "COVERS", c.sku_category, "PRICED_IN", sku_id]
                    if c.covered else [customer_id, "HOLDS", c.contract_id]
                ),
            }
            for c in coverage
        ],
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


def ask_knowledge(ctx: ToolContext, *, question: str) -> dict:
    try:
        result = ctx.knowledge.ask(question)
    except (GraphError, EmbeddingsNotBuilt, EmbeddingError) as exc:
        return {"error": str(exc)}
    return {"route": result.route.value, "rule": result.rule, "evidence": result.evidence}


TOOL_HANDLERS: dict[str, Callable[..., dict]] = {
    "lookup_customer": lookup_customer,
    "search_price_book": search_price_book,
    "check_stock": check_stock,
    "get_related_parts": get_related_parts,
    "check_contract_coverage": check_contract_coverage,
    "predict_price": predict_price,
    "ask_knowledge": ask_knowledge,
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


def _string_params(descriptions: dict[str, str]) -> dict:
    return {
        "type": "object",
        "properties": {name: {"type": "string", "description": text} for name, text in descriptions.items()},
        "required": list(descriptions),
    }


TOOL_SPECS: list[dict] = [
    _function_spec(
        "lookup_customer",
        "Find a customer by id or name. Returns matches with their contracts (discount_pct, covered_categories, "
        "effective dates, and whether the contract is active on the quote date).",
        _string_params({"query": "customer id (CUST-....) or customer name"}),
    ),
    _function_spec(
        "search_price_book",
        "Find SKUs by id or name. Returns list_price (null means unpriced), last realized price, discontinued and "
        "in_stock flags.",
        _string_params({"query": "SKU id (SKU-....) or product name as written in the email"}),
    ),
    _function_spec(
        "check_stock", "Check whether a SKU is in stock and whether it is discontinued.",
        _string_params({"sku_id": "SKU id"}),
    ),
    _function_spec(
        "get_related_parts",
        "Walk the knowledge graph from a SKU. Follows the full replacement chain of a discontinued SKU and returns "
        "live_sku_id (the SKU to quote; null when no live replacement exists), plus the required_parts of that live "
        "SKU. Call it again on any required part that is discontinued.",
        _string_params({"sku_id": "SKU id"}),
    ),
    _function_spec(
        "check_contract_coverage",
        "Ask the knowledge graph whether a customer's contract covers a SKU's pricing category. Returns, per "
        "contract, discount_applies (covered and active on the quote date), the contract's discount_pct, and why.",
        _string_params({"customer_id": "customer id", "sku_id": "SKU id"}),
    ),
    _function_spec(
        "predict_price",
        "Estimate a price for a SKU that has no list price, from same-category peers. The result is a prediction, "
        "not a looked-up price; the draft line must use price_source 'predicted' and this exact predicted_price.",
        _string_params({"sku_id": "SKU id of an unpriced SKU"}),
    ),
    _function_spec(
        "ask_knowledge",
        "Answer an open-ended question that the other tools do not cover: products similar to something, or "
        "catalog-level questions about product groups. Not for price, stock, customer or contract lookups.",
        _string_params({"question": "the question in plain language"}),
    ),
    _function_spec(
        "submit_draft",
        "Submit the finished draft estimate for validation. Call this when the draft is ready, and again with a "
        "corrected draft if validation reports violations.",
        EstimateDraft.model_json_schema(),
    ),
]
