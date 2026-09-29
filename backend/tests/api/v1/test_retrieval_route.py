import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from api.v1.retrieval.route import get_embedding_client
from app.retrieval.models import SkuEmbedding
from app.retrieval.vector import embed_pending_skus
from core.db.session import get_session
from core.graph.client import get_graph_client
from core.llm.openai_embedding_client import EmbeddingError
from main import app
from tests.app.estimate.seed import seed_structure, seed_world
from tests.graph_support import FailingGraphClient, FakeEmbedder, QueryFailingGraphClient


def _ask(db_session, question, embedder=None, overrides=None):
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_embedding_client] = lambda: embedder or FakeEmbedder()
    for dependency, factory in (overrides or {}).items():
        app.dependency_overrides[dependency] = factory
    try:
        return TestClient(app).post("/v1/retrieval/ask", json={"question": question})
    finally:
        app.dependency_overrides.clear()


def _world(db_session, make_reader):
    seed_world(db_session)
    seed_structure(db_session)
    make_reader()


def test_ask_answers_an_id_question_from_sql(db_session, make_reader):
    _world(db_session, make_reader)

    response = _ask(db_session, "price of SKU-E-A1")

    body = response.json()
    assert response.status_code == 200
    assert (body["route"], body["rule"]) == ("sql", "id_lookup")
    assert body["evidence"]["skus"][0]["sku_id"] == "SKU-E-A1"


def test_ask_answers_a_relationship_question_from_the_graph(db_session, make_reader):
    _world(db_session, make_reader)

    body = _ask(db_session, "what does SKU-E-B1 require").json()

    assert body["route"] == "graph_local"
    assert "SKU-E-A1" in {n["id"] for n in body["evidence"]["nodes"]}


def test_ask_answers_a_similarity_question_from_vectors(db_session, make_reader):
    _world(db_session, make_reader)
    embedder = FakeEmbedder()
    embed_pending_skus(db_session, embedder, on_batch_saved=lambda: None)

    body = _ask(db_session, "similar to SKU-E-A1", embedder=embedder).json()

    assert body["route"] == "vector"
    assert "SKU-E-A1" not in [m["sku_id"] for m in body["evidence"]["matches"]]


def test_a_vector_question_before_embeddings_exist_is_a_409(db_session, make_reader):
    _world(db_session, make_reader)
    db_session.execute(delete(SkuEmbedding))
    db_session.flush()

    response = _ask(db_session, "something like a zorpwidget")

    assert response.status_code == 409
    assert "embed_skus" in response.json()["detail"]


def test_an_embedding_failure_is_a_502(db_session, make_reader):
    _world(db_session, make_reader)
    embed_pending_skus(db_session, FakeEmbedder(), on_batch_saved=lambda: None)

    class FailingEmbedder:
        def embed(self, texts):
            raise EmbeddingError("boom")

    response = _ask(db_session, "something like a zorpwidget", embedder=FailingEmbedder())

    assert response.status_code == 502


def test_a_graph_question_with_the_graph_down_is_a_503(db_session):
    seed_world(db_session)

    response = _ask(
        db_session, "what does SKU-E-B1 require", overrides={get_graph_client: lambda: FailingGraphClient()},
    )

    assert response.status_code == 503


def test_a_graph_question_whose_query_fails_is_a_502(db_session):
    seed_world(db_session)

    response = _ask(
        db_session, "what does SKU-E-B1 require", overrides={get_graph_client: lambda: QueryFailingGraphClient()},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "graph query failed"


def test_a_sql_question_still_works_with_the_graph_down(db_session):
    seed_world(db_session)

    response = _ask(db_session, "price of SKU-E-A1", overrides={get_graph_client: lambda: FailingGraphClient()})

    assert response.status_code == 200


@pytest.mark.parametrize("question", ["", "   ", "x" * 1001])
def test_empty_or_oversized_questions_are_rejected(db_session, question):
    """(Review Focus) Whitespace-only text is stripped to empty and rejected."""
    assert _ask(db_session, question).status_code == 422


def test_get_embedding_client_builds_openai_client_with_settings_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-from-settings")

    assert get_embedding_client()._client.api_key == "sk-test-from-settings"
