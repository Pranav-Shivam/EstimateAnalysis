import pytest

from core.config.settings import Settings
from core.graph.client import GraphClient, GraphQueryFailed, GraphUnavailable


def test_read_returns_rows_as_dicts(graph_client):
    assert graph_client.read("RETURN $n AS n", n=7) == [{"n": 7}]


def test_write_then_read_round_trips_inside_the_test_namespace(graph_client, graph_ns):
    graph_client.write("CREATE (:Probe {ns: $ns, id: 'p1'})", ns=graph_ns)

    rows = graph_client.read("MATCH (p:Probe {ns: $ns}) RETURN p.id AS id", ns=graph_ns)

    assert rows == [{"id": "p1"}]


def test_a_cypher_error_raises_graph_query_failed(graph_client):
    with pytest.raises(GraphQueryFailed):
        graph_client.read("THIS IS NOT CYPHER")


def test_an_unreachable_server_raises_graph_unavailable():
    client = GraphClient("bolt://localhost:1", "neo4j", "x")
    try:
        with pytest.raises(GraphUnavailable):
            client.read("RETURN 1")
    finally:
        client.close()


def test_a_wrong_password_raises_graph_unavailable(graph_client, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5433/db")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    settings = Settings(_env_file=None)
    client = GraphClient(settings.neo4j_uri, settings.neo4j_user, "definitely-wrong")
    try:
        with pytest.raises(GraphUnavailable):
            client.read("RETURN 1")
    finally:
        client.close()
