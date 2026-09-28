from app.graph.reader import GraphReader
from app.graph.service import rebuild_reference_graph


def build_reader(session, client, ns) -> GraphReader:
    """Rebuild the reference graph for the rows visible to this session (including uncommitted test rows) into the
    test namespace and return a reader over it. Call after seeding."""
    rebuild_reference_graph(session, client, ns)
    return GraphReader(client, ns)


class UnusedGraph:
    """Stands in for the graph in tests that must not touch it; any use fails loudly."""

    def __getattr__(self, name):
        raise AssertionError(f"graph.{name} was used by a test that declared the graph unused")
