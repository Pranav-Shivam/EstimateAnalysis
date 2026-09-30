from pydantic import BaseModel


class RebuildResponse(BaseModel):
    namespace: str
    fingerprint: str
    node_counts: dict[str, int]
    edge_counts: dict[str, int]
    community_count: int
    largest_community_size: int


class GraphNode(BaseModel):
    id: str
    label: str
    name: str
    community: int | None


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str


class NeighborhoodResponse(BaseModel):
    center: GraphNode
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool


class GraphStatsResponse(BaseModel):
    node_counts: dict[str, int]
    edge_counts: dict[str, int]


class SchemaEdge(BaseModel):
    source: str
    target: str
    type: str
    count: int


class SchemaOverviewResponse(BaseModel):
    node_counts: dict[str, int]
    edges: list[SchemaEdge]


class LabelNodesResponse(BaseModel):
    nodes: list[GraphNode]
    truncated: bool


class FullGraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
