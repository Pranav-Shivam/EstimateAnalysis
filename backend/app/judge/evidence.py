from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.estimate.pricing import predict_price_for_sku
from app.estimate.schemas import DraftLine, EstimateDraft
from app.graph.reader import GraphReader
from app.reference_data.repository import get_sku


@dataclass(frozen=True)
class PriceEvidence:
    price_source: str
    list_price: float | None
    predicted_price: float | None
    peer_count: int | None
    low: float | None
    high: float | None


@dataclass(frozen=True)
class ContractEvidence:
    discount_pct: float
    contract_id: str | None
    covered: bool | None
    active_on_as_of: bool | None
    days_to_expiry: int | None


@dataclass(frozen=True)
class GraphEvidence:
    discontinued: bool
    live_sku_id: str | None
    required_part_ids: list[str] = field(default_factory=list)
    missing_required_part_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LineEvidence:
    line_index: int
    sku_id: str
    unit_price: float
    price: PriceEvidence
    contract: ContractEvidence
    graph: GraphEvidence


def _price_evidence(session: Session, line: DraftLine) -> PriceEvidence:
    sku = get_sku(session, line.sku_id) if line.sku_id else None
    if line.price_source != "predicted":
        return PriceEvidence(
            price_source="list", list_price=sku.list_price if sku else None,
            predicted_price=None, peer_count=None, low=None, high=None,
        )
    prediction = predict_price_for_sku(session, sku) if sku else None
    return PriceEvidence(
        price_source="predicted", list_price=None,
        predicted_price=prediction.price if prediction else None,
        peer_count=prediction.peer_count if prediction else None,
        low=prediction.low if prediction else None, high=prediction.high if prediction else None,
    )


def _contract_evidence(graph: GraphReader, draft: EstimateDraft, line: DraftLine, as_of: date) -> ContractEvidence:
    if line.discount_pct == 0 or draft.customer_id is None or draft.contract_id is None or line.sku_id is None:
        return ContractEvidence(
            discount_pct=line.discount_pct, contract_id=draft.contract_id,
            covered=None, active_on_as_of=None, days_to_expiry=None,
        )
    matches = [
        c for c in graph.contract_coverage(draft.customer_id, line.sku_id, as_of) if c.contract_id == draft.contract_id
    ]
    if not matches:
        return ContractEvidence(
            discount_pct=line.discount_pct, contract_id=draft.contract_id,
            covered=False, active_on_as_of=None, days_to_expiry=None,
        )
    match = matches[0]
    days_to_expiry = (date.fromisoformat(match.effective_to) - as_of).days
    return ContractEvidence(
        discount_pct=line.discount_pct, contract_id=draft.contract_id,
        covered=match.covered, active_on_as_of=match.active_on_as_of, days_to_expiry=days_to_expiry,
    )


def _graph_evidence(graph: GraphReader, draft: EstimateDraft, line: DraftLine) -> GraphEvidence:
    present = {l.sku_id for l in draft.lines if l.sku_id is not None}
    chain = graph.sku_chain(line.sku_id)
    if chain is None:
        return GraphEvidence(discontinued=False, live_sku_id=None)
    live = chain.live_end
    required = graph.required_parts(live.sku_id) if live is not None else []
    return GraphEvidence(
        discontinued=chain.nodes[0].discontinued,
        live_sku_id=live.sku_id if live is not None else None,
        required_part_ids=[p.sku_id for p in required],
        missing_required_part_ids=[p.sku_id for p in required if p.sku_id not in present],
    )


def build_evidence(session: Session, graph: GraphReader, draft: EstimateDraft, as_of: date) -> list[LineEvidence]:
    return [
        LineEvidence(
            line_index=index, sku_id=line.sku_id, unit_price=line.unit_price,
            price=_price_evidence(session, line), contract=_contract_evidence(graph, draft, line, as_of),
            graph=_graph_evidence(graph, draft, line),
        )
        for index, line in enumerate(draft.lines)
        if line.sku_id is not None
    ]
