from app.graph.reader import GraphReader
from app.graph.repository import node_key
from app.graph.service import rebuild_reference_graph
from app.reference_data.repository import set_sku_family, upsert_family, upsert_requirement, upsert_sku
from core.graph.client import GraphUnavailable


def build_reader(session, client, ns) -> GraphReader:
    """Rebuild the reference graph for the rows visible to this session (including uncommitted test rows) into the
    test namespace and return a reader over it. Call after seeding."""
    rebuild_reference_graph(session, client, ns)
    return GraphReader(client, ns)


class UnusedGraph:
    """Stands in for the graph in tests that must not touch it; any use fails loudly."""

    def __getattr__(self, name):
        raise AssertionError(f"graph.{name} was used by a test that declared the graph unused")


def graph_node(client, ns, node_id):
    rows = client.read(
        "MATCH (n {key: $key}) RETURN labels(n) AS labels, properties(n) AS props", key=node_key(ns, node_id)
    )
    return rows[0] if rows else None


def graph_edge_count(client, ns, source, edge_type, target) -> int:
    rows = client.read(
        "MATCH ({key: $source})-[r]->({key: $target}) WHERE type(r) = $type RETURN count(r) AS count",
        source=node_key(ns, source), target=node_key(ns, target), type=edge_type,
    )
    return rows[0]["count"]


def seed_clusters(session) -> None:
    """Two disconnected clusters of four SKUs, one family each, all in Cat-L. SKU-L-X4 is discontinued and
    SKU-L-X1 requires SKU-L-X2. Leiden must put each cluster in its own community."""
    upsert_family(session, family_id="FAM-L-X", name="Xylo Widget", category="Cat-L")
    upsert_family(session, family_id="FAM-L-Y", name="Yarrow Gadget", category="Cat-L")
    session.flush()
    for prefix in ("X", "Y"):
        for i in range(1, 5):
            upsert_sku(
                session, sku_id=f"SKU-L-{prefix}{i}", name=f"unit {prefix}{i}", category="Cat-L", list_price=1.0,
                discontinued=(prefix == "X" and i == 4), replaced_by=None, in_stock=True,
            )
    session.flush()
    for prefix in ("X", "Y"):
        for i in range(1, 5):
            set_sku_family(session, f"SKU-L-{prefix}{i}", f"FAM-L-{prefix}")
    upsert_requirement(session, sku_id="SKU-L-X1", required_sku_id="SKU-L-X2")
    session.flush()


class FailingGraphClient:
    """A graph client whose server is down."""

    def read(self, query, **params):
        raise GraphUnavailable("Neo4j is unavailable: test double")

    def write(self, query, **params):
        raise GraphUnavailable("Neo4j is unavailable: test double")


class FakeSummarizer:
    """Records every prompt and returns a distinct summary per call. Never touches the network."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def summarize(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return f"Fake summary number {len(self.prompts)}."
