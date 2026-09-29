from fastapi.testclient import TestClient

from app.intake.repository import save_quote_request
from core.db.session import get_session
from core.graph.client import get_graph_client
from main import app
from tests.app.estimate.seed import seed_structure, seed_world
from tests.graph_support import FailingGraphClient, QueryFailingGraphClient, graph_node, rebuild_lock_held_elsewhere


def _rebuild(db_session, overrides=None):
    app.dependency_overrides[get_session] = lambda: db_session
    for dependency, factory in (overrides or {}).items():
        app.dependency_overrides[dependency] = factory
    try:
        return TestClient(app).post("/v1/graph/rebuild")
    finally:
        app.dependency_overrides.clear()


def test_rebuild_reloads_the_graph_and_reports_counts_and_communities(db_session, graph_client, graph_ns):
    seed_world(db_session)
    seed_structure(db_session)
    request = save_quote_request(
        db_session, raw_email_text="x", parsed_json={}, content_fingerprint={"sku_ids": []},
        style_fingerprint={"tokens": []}, customer_id="CUST-E1",
    )

    response = _rebuild(db_session)

    body = response.json()
    assert response.status_code == 200
    assert body["namespace"] == graph_ns
    assert len(body["fingerprint"]) == 32
    assert body["node_counts"]["SKU"] >= 8 and body["edge_counts"]["REQUIRES"] >= 1
    assert body["community_count"] >= 1 and body["largest_community_size"] >= 1
    assert graph_node(graph_client, graph_ns, "SKU-E-A1") is not None
    assert graph_node(graph_client, graph_ns, str(request.id)) is not None


def test_rebuild_is_a_503_when_the_graph_is_down(db_session):
    seed_world(db_session)

    response = _rebuild(db_session, overrides={get_graph_client: lambda: FailingGraphClient()})

    assert response.status_code == 503


def test_rebuild_is_a_502_when_a_graph_query_fails(db_session):
    seed_world(db_session)

    response = _rebuild(db_session, overrides={get_graph_client: lambda: QueryFailingGraphClient()})

    assert response.status_code == 502
    assert response.json()["detail"] == "graph query failed"


def test_rebuild_is_a_409_while_another_rebuild_of_the_namespace_runs(db_session, graph_ns):
    seed_world(db_session)

    with rebuild_lock_held_elsewhere(db_session, graph_ns):
        response = _rebuild(db_session)

    assert response.status_code == 409
    assert graph_ns in response.json()["detail"]
