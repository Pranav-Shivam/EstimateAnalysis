from datetime import date

from app.graph import repository
from app.graph.schemas import ChainNode, ContractCoverage, RequiredPart, SkuChain
from core.graph.client import GraphClient


class GraphReader:
    """Read-only, namespace-scoped view of the graph for the agent tools and guardrails."""

    def __init__(self, client: GraphClient, ns: str) -> None:
        self.client = client
        self.ns = ns

    def sku_chain(self, sku_id: str) -> SkuChain | None:
        raw = repository.fetch_sku_chain(self.client, self.ns, sku_id)
        if raw is None:
            return None
        nodes = tuple(
            ChainNode(sku_id=n["id"], name=n["name"], discontinued=bool(n["discontinued"]), in_stock=bool(n["in_stock"]))
            for n in raw
        )
        live_end = next((node for node in nodes if not node.discontinued), None)
        return SkuChain(nodes=nodes, live_end=live_end)

    def required_parts(self, sku_id: str) -> list[RequiredPart]:
        return [
            RequiredPart(sku_id=r["id"], name=r["name"], discontinued=bool(r["discontinued"]), in_stock=bool(r["in_stock"]))
            for r in repository.fetch_required_parts(self.client, self.ns, sku_id)
        ]

    def contract_coverage(self, customer_id: str, sku_id: str, as_of: date) -> list[ContractCoverage]:
        today = as_of.isoformat()
        return [
            ContractCoverage(
                contract_id=r["contract_id"], discount_pct=r["discount_pct"], effective_from=r["effective_from"],
                effective_to=r["effective_to"], sku_category=r["sku_category"],
                covered_categories=tuple(r["covered_categories"]), covered=bool(r["covered"]),
                active_on_as_of=r["effective_from"] <= today <= r["effective_to"],
            )
            for r in repository.fetch_contract_coverage(self.client, self.ns, customer_id, sku_id)
        ]

    def stored_fingerprint(self) -> str | None:
        return repository.fetch_fingerprint(self.client, self.ns)
