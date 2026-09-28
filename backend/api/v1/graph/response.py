from pydantic import BaseModel


class RebuildResponse(BaseModel):
    namespace: str
    fingerprint: str
    node_counts: dict[str, int]
    edge_counts: dict[str, int]
    community_count: int
    largest_community_size: int
