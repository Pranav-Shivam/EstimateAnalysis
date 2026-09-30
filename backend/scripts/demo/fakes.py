"""Deterministic stand-ins for the three external LLM clients, used only by the demo seed script.

Everything downstream of them is production code: intake resolves names against the real reference data, the
guardrails and graph check the real drafts, and the judge scores evidence built by `build_evidence`. Only the
model calls are replaced, so no network is touched and no API key is needed."""
from datetime import date

from sqlalchemy.orm import Session

from app.estimate.pricing import predict_price_for_sku
from app.graph.reader import GraphReader
from app.intake.models import QuoteRequestRow
from app.intake.schemas import LineItemExtraction, QuoteRequestExtraction
from app.reference_data.models import Contract
from app.reference_data.repository import get_contract, get_sku
from core.llm.anthropic_judge_client import RawDimensionScore, RawJudgeScore
from core.llm.openai_agent_client import AgentTurn, ToolCall

DOUBT_SCORE = 0.2
PRICE_TRUST_SCORE = 0.95
CONTRACT_TRUST_SCORE = 0.95
GRAPH_TRUST_SCORE = 0.9


class DemoSetupError(Exception):
    """The reference data cannot support the scripted scenario."""


class ScriptedExtractionClient:
    """Reads the structured request from the scenario's ground truth instead of asking GPT-4o."""

    def __init__(self, scenarios: list[dict]) -> None:
        self._by_email = {scenario["email_text"]: scenario for scenario in scenarios}

    def extract_quote_request(self, email_text: str) -> QuoteRequestExtraction:
        scenario = self._by_email[email_text]
        entities = scenario["entities"]
        names = entities.get("sku_names") or [entities["sku_name"]]
        return QuoteRequestExtraction(
            customer_name_as_written=scenario["customer"]["name"],
            contact_name_as_written=scenario["customer"]["contact"],
            line_items=[LineItemExtraction(sku_name_as_written=name, quantity="1") for name in names],
            raw_text=email_text,
        )


def _contract_applies(contract: Contract | None, category: str, as_of: date) -> bool:
    return (
        contract is not None
        and category in contract.covered_categories
        and contract.effective_from <= as_of <= contract.effective_to
    )


def _line(session: Session, sku_id: str, contract: Contract | None, as_of: date) -> dict:
    sku = get_sku(session, sku_id)
    if sku.list_price is not None:
        price, source = sku.list_price, "list"
    else:
        prediction = predict_price_for_sku(session, sku)
        if prediction is None:
            raise DemoSetupError(f"{sku_id} has no list price and too few priced peers to predict one")
        price, source = prediction.price, "predicted"
    discount = contract.discount_pct if _contract_applies(contract, sku.category, as_of) else 0.0
    return {"sku_id": sku_id, "quantity": 1, "unit_price": price, "price_source": source, "discount_pct": discount}


def _live_sku_id(reader: GraphReader, sku_id: str) -> str:
    chain = reader.sku_chain(sku_id)
    return chain.live_end.sku_id if chain is not None and chain.live_end is not None else sku_id


def build_draft(session: Session, reader: GraphReader, quote_request: QuoteRequestRow, as_of: date) -> dict:
    """What a correct agent would submit: each requested SKU replaced by its live successor, every required part
    added, list prices where they exist and peer-median predictions where they do not, and the contract discount
    only where the contract covers the category."""
    contract = get_contract(session, quote_request.contract_id) if quote_request.contract_id else None
    requested = [item["sku_id"] for item in quote_request.parsed_json["resolved_line_items"] if item.get("sku_id")]
    pending = list(dict.fromkeys(requested))
    ordered: list[str] = []
    adjustments: list[dict] = []

    while pending:
        sku_id = pending.pop(0)
        live_id = _live_sku_id(reader, sku_id)
        if live_id != sku_id:
            adjustments.append({
                "kind": "substituted", "sku_id": live_id,
                "detail": f"{sku_id} is discontinued; quoted its live replacement {live_id}",
            })
        if live_id in ordered:
            continue
        ordered.append(live_id)
        for part in reader.required_parts(live_id):
            part_live_id = _live_sku_id(reader, part.sku_id)
            if part_live_id not in ordered and part_live_id not in pending:
                adjustments.append({
                    "kind": "added_required", "sku_id": part_live_id, "detail": f"{live_id} requires {part_live_id}",
                })
                pending.append(part_live_id)

    return {
        "customer_id": quote_request.customer_id,
        "contract_id": contract.contract_id if contract is not None else None,
        "lines": [_line(session, sku_id, contract, as_of) for sku_id in ordered],
        "adjustments": adjustments,
    }


def blocked_draft(draft: dict) -> dict:
    """A draft the guardrails reject on every submission (a zero quantity), so the run ends for review."""
    first, *rest = draft["lines"]
    return {**draft, "lines": [{**first, "quantity": 0}, *rest]}


class ScriptedAgentClient:
    """Submits one fixed draft on every turn, standing in for the GPT-4o agent."""

    def __init__(self, draft: dict) -> None:
        self._turn = AgentTurn(
            content=None, tool_calls=[ToolCall(id="call-submit", name="submit_draft", arguments=draft)],
        )

    def next_turn(self, messages: list[dict], tools: list[dict]) -> AgentTurn:
        return self._turn


class DemoJudgeClient:
    """Stands in for the Claude Haiku judge. It doubts price provenance whenever a price was predicted. It doubts
    the graph and contract dimensions only for the SKUs the scenario planted a knowledge gap on, and only while the
    evidence still shows the gap, which is exactly what a reviewer's correction removes."""

    def __init__(self, graph_watch: set[str], contract_watch: set[str]) -> None:
        self._graph_watch = graph_watch
        self._contract_watch = contract_watch

    def score(self, evidence: list[dict], system_prompt: str) -> RawJudgeScore:
        predicted = [line["sku_id"] for line in evidence if line["price"]["price_source"] == "predicted"]
        graph_gap = [
            line["sku_id"] for line in evidence
            if line["sku_id"] in self._graph_watch and not line["graph"]["required_part_ids"]
        ]
        contract_gap = [
            line["sku_id"] for line in evidence
            if line["sku_id"] in self._contract_watch
            and line["contract"]["contract_id"] is not None
            and line["contract"]["discount_pct"] == 0
        ]
        return RawJudgeScore(dimensions=[
            RawDimensionScore(
                name="price_provenance", score=DOUBT_SCORE if predicted else PRICE_TRUST_SCORE,
                rationale=(
                    f"{', '.join(predicted)}: the price is a peer-median prediction, not a reference list price"
                    if predicted else "every price is a reference list price"
                ),
            ),
            RawDimensionScore(
                name="contract_discount", score=DOUBT_SCORE if contract_gap else CONTRACT_TRUST_SCORE,
                rationale=(
                    f"{', '.join(contract_gap)}: a contract customer is quoted at full price; is this category "
                    "really outside the contract?"
                    if contract_gap else "discounts match a covering, active contract, or none were claimed"
                ),
            ),
            RawDimensionScore(
                name="graph_completion", score=DOUBT_SCORE if graph_gap else GRAPH_TRUST_SCORE,
                rationale=(
                    f"{', '.join(graph_gap)} is quoted with no required part recorded in the graph, but it "
                    "usually ships with one"
                    if graph_gap else "live SKUs, and every recorded required part is quoted"
                ),
            ),
        ])


class UnusedEmbedder:
    """The scripted agent never calls a search tool, so nothing should ask for an embedding."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise DemoSetupError("the scripted agent never searches, so nothing should be embedded")
