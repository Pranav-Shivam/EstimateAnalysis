from dataclasses import dataclass, field


@dataclass(frozen=True)
class RebuildSummary:
    namespace: str
    fingerprint: str
    node_counts: dict[str, int] = field(default_factory=dict)
    edge_counts: dict[str, int] = field(default_factory=dict)
