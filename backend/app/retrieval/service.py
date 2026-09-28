from dataclasses import asdict, dataclass

from sqlalchemy.orm import Session

from app.graph.reader import GraphReader
from app.graph.service import NodeNotFound, global_stats, local_query
from app.reference_data.repository import get_contract, get_customer, get_sku
from app.reference_data.search import find_customers, find_skus
from app.retrieval.repository import get_summaries
from app.retrieval.router import Route, RouteDecision, route_question
from app.retrieval.vector import Embedder, embedding_text_for_sku, vector_search


@dataclass(frozen=True)
class RetrievalResult:
    route: Route
    rule: str
    evidence: dict


def _sku_evidence(sku) -> dict:
    return {
        "sku_id": sku.sku_id, "name": sku.name, "category": sku.category, "list_price": sku.list_price,
        "discontinued": sku.discontinued, "in_stock": sku.in_stock,
    }


def _customer_evidence(customer) -> dict:
    return {"customer_id": customer.customer_id, "name": customer.name, "account_tier": customer.account_tier}


def _contract_evidence(contract) -> dict:
    return {
        "contract_id": contract.contract_id, "customer_id": contract.customer_id,
        "discount_pct": contract.discount_pct, "covered_categories": list(contract.covered_categories),
        "effective_from": contract.effective_from.isoformat(), "effective_to": contract.effective_to.isoformat(),
    }


@dataclass(frozen=True)
class KnowledgeService:
    """Answers open-ended questions with evidence from the source that fits: Postgres, the graph, or vectors."""

    session: Session
    graph: GraphReader
    embedder: Embedder

    def ask(self, question: str) -> RetrievalResult:
        decision = route_question(question)
        if decision.route is Route.GRAPH_GLOBAL:
            evidence = self._global()
        elif decision.route is Route.GRAPH_LOCAL:
            evidence = self._local(decision)
        elif decision.route is Route.VECTOR:
            evidence = self._vector(decision, question)
        else:
            evidence = self._sql(decision, question)
        return RetrievalResult(route=decision.route, rule=decision.rule, evidence=evidence)

    def _sql(self, decision: RouteDecision, question: str) -> dict:
        if decision.entity_id is None:
            return {
                "skus": [_sku_evidence(s) for s in find_skus(self.session, question)],
                "customers": [_customer_evidence(c) for c in find_customers(self.session, question)],
            }
        prefix = decision.entity_id.split("-")[0]
        if prefix == "SKU":
            sku = get_sku(self.session, decision.entity_id)
            return {"skus": [_sku_evidence(sku)] if sku else []}
        if prefix == "CUST":
            customer = get_customer(self.session, decision.entity_id)
            return {"customers": [_customer_evidence(customer)] if customer else []}
        contract = get_contract(self.session, decision.entity_id)
        return {"contracts": [_contract_evidence(contract)] if contract else []}

    def _local(self, decision: RouteDecision) -> dict:
        try:
            return asdict(local_query(self.graph.client, self.graph.ns, decision.entity_id))
        except NodeNotFound as exc:
            return {"error": str(exc)}

    def _global(self) -> dict:
        stats = global_stats(self.graph.client, self.graph.ns)
        if not stats:
            return {"communities": [], "note": "no communities computed yet; run POST /v1/graph/rebuild"}
        summaries = get_summaries(self.session, [s.member_hash for s in stats])
        return {"communities": [{**asdict(s), "summary": summaries.get(s.member_hash)} for s in stats]}

    def _vector(self, decision: RouteDecision, question: str) -> dict:
        text, exclude = question, None
        if decision.entity_id and decision.entity_id.startswith("SKU-"):
            sku_text = embedding_text_for_sku(self.session, decision.entity_id)
            if sku_text is not None:
                text, exclude = sku_text, decision.entity_id
        return {"matches": vector_search(self.session, self.embedder, text, exclude_sku_id=exclude)}
