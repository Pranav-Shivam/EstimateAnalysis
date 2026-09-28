import os
import uuid

import pytest

from core.db.session import make_engine, make_session_factory
from core.graph.client import GraphUnavailable, get_graph_client
from tests.graph_support import build_reader

TEST_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5433/estimate_analysis"
)


@pytest.fixture
def db_session():
    engine = make_engine(TEST_DATABASE_URL)
    connection = engine.connect()
    transaction = connection.begin()
    session_factory = make_session_factory(engine)
    session = session_factory(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


@pytest.fixture(autouse=True)
def graph_ns(monkeypatch):
    """A unique namespace per test. Setting the env var makes any code path that reads the configured namespace
    (the app's routes, for example) write into this test's namespace, never into `main`."""
    ns = f"test-{uuid.uuid4().hex[:12]}"
    monkeypatch.setenv("GRAPH_NAMESPACE", ns)
    yield ns
    if get_graph_client.cache_info().currsize:
        get_graph_client().write("MATCH (n {ns: $ns}) DETACH DELETE n", ns=ns)


@pytest.fixture
def graph_client():
    client = get_graph_client()
    try:
        client.read("RETURN 1 AS ok")
    except GraphUnavailable as exc:
        pytest.fail(f"Neo4j is not reachable ({exc}). Start it with: docker start neo4j-estimate", pytrace=False)
    return client


@pytest.fixture
def make_reader(db_session, graph_client, graph_ns):
    def _make():
        return build_reader(db_session, graph_client, graph_ns)

    return _make
