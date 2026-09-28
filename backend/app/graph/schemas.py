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


@dataclass(frozen=True)
class CommunityStats:
    community_id: int
    size: int
    families: tuple[str, ...]
    dominant_category: str
    dominant_category_share: float
    discontinued_count: int
    requirement_count: int
    example_sku_ids: tuple[str, ...]
    member_names: tuple[str, ...]
    member_hash: str


@dataclass(frozen=True)
class CommunityRunSummary:
    community_count: int
    largest_community_size: int


@dataclass(frozen=True)
class LocalResult:
    center: str
    nodes: list[dict]
    edges: list[dict]
    truncated: bool
