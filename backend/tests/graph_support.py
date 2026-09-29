import math
import re
import zlib
from contextlib import contextmanager

from sqlalchemy.orm import Session

from app.estimate.tools import ToolContext
from app.graph.lock import try_lock_rebuild, unlock_rebuild
from app.graph.reader import GraphReader
from app.graph.repository import node_key
from app.graph.service import rebuild_reference_graph
from app.reference_data.repository import set_sku_family, upsert_family, upsert_requirement, upsert_sku
from app.retrieval.service import KnowledgeService
from core.graph.client import GraphQueryFailed, GraphUnavailable
from core.llm.openai_embedding_client import EMBEDDING_DIMENSIONS
from tests.app.estimate.seed import AS_OF


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


class QueryFailingGraphClient:
    """A graph client whose server is up but rejects every query (a Cypher error, a GDS error, a timeout)."""

    def read(self, query, **params):
        raise GraphQueryFailed("Neo4j query failed: test double")

    def write(self, query, **params):
        raise GraphQueryFailed("Neo4j query failed: test double")


def lock_is_free(db_session, ns) -> bool:
    """Whether another Postgres session could take the rebuild lock for `ns` right now. Releases it again."""
    with _other_session(db_session) as other:
        taken = try_lock_rebuild(other, ns)
        if taken:
            unlock_rebuild(other, ns)
        return taken


@contextmanager
def rebuild_lock_held_elsewhere(db_session, ns):
    """Hold the rebuild lock for `ns` from a second Postgres session, as a concurrent rebuild would."""
    with _other_session(db_session) as other:
        assert try_lock_rebuild(other, ns)
        try:
            yield
        finally:
            unlock_rebuild(other, ns)


@contextmanager
def _other_session(db_session):
    connection = db_session.get_bind().engine.connect()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        connection.close()


class FakeSummarizer:
    """Records every prompt and returns a distinct summary per call. Never touches the network."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def summarize(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return f"Fake summary number {len(self.prompts)}."


class FakeEmbedder:
    """Deterministic bag-of-words vectors: texts sharing words are close under cosine distance. Records every
    batch it was asked to embed. Never touches the network."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self._vector(text) for text in texts]

    @staticmethod
    def _vector(text: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIMENSIONS
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            vector[zlib.crc32(token.encode("utf-8")) % EMBEDDING_DIMENSIONS] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


def make_ctx(session, graph, *, as_of=AS_OF, customer_id=None, sku_ids=(), embedder=None, trace=None) -> ToolContext:
    knowledge = KnowledgeService(session=session, graph=graph, embedder=embedder or FakeEmbedder())
    kwargs = {
        "session": session, "as_of": as_of, "graph": graph, "knowledge": knowledge, "request_customer_id": customer_id,
        "request_sku_ids": tuple(sku_ids),
    }
    if trace is not None:
        kwargs["trace"] = trace
    return ToolContext(**kwargs)


class FailingGraphReader:
    """A reader whose graph is down. `client` is a `FailingGraphClient` (not None) so a caller that reaches past
    the reader's own methods straight to `.client.read`, as the knowledge service's graph_local route does, still
    sees a graph outage rather than an AttributeError."""

    client = FailingGraphClient()
    ns = "down"

    def sku_chain(self, sku_id):
        raise GraphUnavailable("Neo4j is unavailable: test double")

    def required_parts(self, sku_id):
        raise GraphUnavailable("Neo4j is unavailable: test double")

    def contract_coverage(self, customer_id, sku_id, as_of):
        raise GraphUnavailable("Neo4j is unavailable: test double")

    def stored_fingerprint(self):
        raise GraphUnavailable("Neo4j is unavailable: test double")


class TogglableReader:
    """Delegates to a real reader until `down` is set, then behaves like a graph outage. Lets a test take the graph
    away in the middle of an agent run."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.down = False

    @property
    def client(self):
        return self._inner.client

    @property
    def ns(self):
        return self._inner.ns

    def _check(self) -> None:
        if self.down:
            raise GraphUnavailable("Neo4j went away mid-run: test double")

    def sku_chain(self, sku_id):
        self._check()
        return self._inner.sku_chain(sku_id)

    def required_parts(self, sku_id):
        self._check()
        return self._inner.required_parts(sku_id)

    def contract_coverage(self, customer_id, sku_id, as_of):
        self._check()
        return self._inner.contract_coverage(customer_id, sku_id, as_of)

    def stored_fingerprint(self):
        self._check()
        return self._inner.stored_fingerprint()
