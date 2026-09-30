from fastapi.testclient import TestClient

from app.graph.constant import LABEL_LIST_LIMIT
from app.graph.service import rebuild_reference_graph
from core.db.session import get_session
from core.graph.client import get_graph_client
from main import app
from tests.app.estimate.seed import seed_structure, seed_world
from tests.graph_support import FailingGraphClient


def _client(db_session, graph_ns):
    seed_world(db_session)
    seed_structure(db_session)
    rebuild_reference_graph(db_session, get_graph_client(), graph_ns)
    app.dependency_overrides[get_session] = lambda: db_session
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def test_search_finds_a_node_by_id_fragment(db_session, graph_client, graph_ns):
    body = _client(db_session, graph_ns).get("/v1/graph/search", params={"q": "SKU-E-A1"}).json()
    assert any(n["id"] == "SKU-E-A1" and n["label"] == "SKU" for n in body)


def test_search_rejects_a_blank_query(db_session, graph_client, graph_ns):
    assert _client(db_session, graph_ns).get("/v1/graph/search", params={"q": "  "}).status_code == 422


def test_neighbors_return_center_nodes_and_edges(db_session, graph_client, graph_ns):
    body = _client(db_session, graph_ns).get("/v1/graph/nodes/SKU-E-A1/neighbors").json()
    assert body["center"]["id"] == "SKU-E-A1"
    known = {n["id"] for n in body["nodes"]} | {"SKU-E-A1"}
    assert body["edges"] and all(e["source"] in known and e["target"] in known for e in body["edges"])
    assert body["truncated"] is False


def test_neighbors_of_an_unknown_node_is_404(db_session, graph_client, graph_ns):
    assert _client(db_session, graph_ns).get("/v1/graph/nodes/NOPE/neighbors").status_code == 404


def test_stats_reports_counts_by_label_and_type(db_session, graph_client, graph_ns):
    body = _client(db_session, graph_ns).get("/v1/graph/stats").json()
    assert body["node_counts"]["SKU"] >= 8 and body["edge_counts"]["REQUIRES"] >= 1


def test_graph_down_is_503(db_session, graph_ns):
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_graph_client] = lambda: FailingGraphClient()
    assert TestClient(app).get("/v1/graph/stats").status_code == 503


def test_schema_reports_counts_and_typed_edges_between_labels(db_session, graph_client, graph_ns):
    body = _client(db_session, graph_ns).get("/v1/graph/schema").json()
    assert body["node_counts"]["SKU"] >= 8 and "GraphMeta" not in body["node_counts"]
    assert {"source": "SKU", "target": "SKU", "type": "REQUIRES"}.items() <= next(
        e for e in body["edges"] if e["type"] == "REQUIRES"
    ).items()


def test_nodes_of_a_label_are_capped_and_flagged_when_there_are_more(db_session, graph_client, graph_ns):
    body = _client(db_session, graph_ns).get("/v1/graph/nodes", params={"label": "SKU"}).json()
    assert all(n["label"] == "SKU" for n in body["nodes"])
    assert len(body["nodes"]) == LABEL_LIST_LIMIT and body["truncated"] is True


def test_a_small_label_is_listed_whole_and_not_flagged(db_session, graph_client, graph_ns):
    body = _client(db_session, graph_ns).get("/v1/graph/nodes", params={"label": "PricingCategory"}).json()
    assert 0 < len(body["nodes"]) < LABEL_LIST_LIMIT and body["truncated"] is False


def test_an_unknown_label_is_422(db_session, graph_client, graph_ns):
    assert _client(db_session, graph_ns).get("/v1/graph/nodes", params={"label": "Bogus) DETACH DELETE n //"}).status_code == 422


def test_full_graph_edges_only_join_returned_nodes(db_session, graph_client, graph_ns):
    body = _client(db_session, graph_ns).get("/v1/graph/full").json()
    ids = {n["id"] for n in body["nodes"]}
    assert body["edges"] and all(e["source"] in ids and e["target"] in ids for e in body["edges"])
