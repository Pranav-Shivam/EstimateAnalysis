from dataclasses import dataclass, field


@dataclass(frozen=True)
class RebuildSummary:
    namespace: str
    fingerprint: str
    node_counts: dict[str, int] = field(default_factory=dict)
    edge_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ChainNode:
    sku_id: str
    name: str
    discontinued: bool
    in_stock: bool


@dataclass(frozen=True)
class SkuChain:
    # The SKU asked about first, then one node per REPLACED_BY hop.
    nodes: tuple[ChainNode, ...]
    # The first node in the chain that is not discontinued, or None when the chain never reaches a live SKU.
    live_end: ChainNode | None

    @property
    def sku_id(self) -> str:
        return self.nodes[0].sku_id

    @property
    def evidence_path(self) -> list[str]:
        """Node ids and edge types from the asked SKU to its live end (or to the last node reached)."""
        end = self.nodes.index(self.live_end) if self.live_end is not None else len(self.nodes) - 1
        path: list[str] = []
        for node in self.nodes[: end + 1]:
            if path:
                path.append("REPLACED_BY")
            path.append(node.sku_id)
        return path


@dataclass(frozen=True)
class RequiredPart:
    sku_id: str
    name: str
    discontinued: bool
    in_stock: bool


@dataclass(frozen=True)
class ContractCoverage:
    contract_id: str
    discount_pct: float
    effective_from: str
    effective_to: str
    sku_category: str | None
    covered_categories: tuple[str, ...]
    covered: bool
    active_on_as_of: bool
