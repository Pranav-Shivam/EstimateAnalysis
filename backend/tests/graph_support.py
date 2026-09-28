from app.graph.reader import GraphReader
from app.graph.repository import node_key
from app.graph.service import rebuild_reference_graph
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


class FailingGraphClient:
    """A graph client whose server is down."""

    def read(self, query, **params):
        raise GraphUnavailable("Neo4j is unavailable: test double")

    def write(self, query, **params):
        raise GraphUnavailable("Neo4j is unavailable: test double")
