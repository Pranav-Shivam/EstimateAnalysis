from app.graph.helper import member_hash
from app.graph.service import run_communities
from app.retrieval.repository import save_summary
from app.retrieval.router import Route
from app.retrieval.service import KnowledgeService
from app.retrieval.vector import embed_pending_skus
from core.llm.openai_summary_client import SUMMARY_MODEL
from tests.app.estimate.seed import seed_structure, seed_world
from tests.graph_support import FakeEmbedder, seed_clusters


def _service(db_session, make_reader, embedder=None):
    reader = make_reader()
    return KnowledgeService(session=db_session, graph=reader, embedder=embedder or FakeEmbedder())


def _world(db_session):
    seed_world(db_session)
    seed_structure(db_session)


def test_an_id_question_is_answered_from_sql(db_session, make_reader):
    _world(db_session)
    service = _service(db_session, make_reader)

    sku = service.ask("price of SKU-E-A1")
    customer = service.ask("CUST-E1 details")
    contract = service.ask("show CTR-E1")

    assert sku.route is Route.SQL and sku.rule == "id_lookup"
    assert sku.evidence["skus"][0]["sku_id"] == "SKU-E-A1" and sku.evidence["skus"][0]["list_price"] == 100.0
    assert customer.evidence["customers"][0]["customer_id"] == "CUST-E1"
    assert contract.evidence["contracts"][0]["discount_pct"] == 10.0
    assert contract.evidence["contracts"][0]["covered_categories"] == ["Cat-E-A"]


def test_an_unknown_sql_id_returns_empty_evidence_not_an_error(db_session, make_reader):
    _world(db_session)

    result = _service(db_session, make_reader).ask("price of SKU-NOPE")

    assert result.evidence == {"skus": []}


def test_a_name_question_searches_skus_and_customers(db_session, make_reader):
    _world(db_session)

    result = _service(db_session, make_reader).ask("Zorpwidget Alpha 9000")

    assert result.rule == "name_search"
    assert result.evidence["skus"][0]["sku_id"] == "SKU-E-A1"
    assert result.evidence["customers"] == []


def test_an_empty_question_falls_back_to_an_empty_name_search(db_session, make_reader):
    _world(db_session)

    result = _service(db_session, make_reader).ask("")

    assert result.route is Route.SQL
    assert result.evidence["customers"] == []


def test_a_relationship_question_is_answered_from_the_graph_neighbourhood(db_session, make_reader):
    _world(db_session)

    result = _service(db_session, make_reader).ask("what does SKU-E-B1 require")

    assert result.route is Route.GRAPH_LOCAL
    assert result.evidence["center"] == "SKU-E-B1"
    assert "SKU-E-A1" in {n["id"] for n in result.evidence["nodes"]}
    assert result.evidence["truncated"] is False


def test_a_graph_question_about_an_unknown_id_reports_an_error(db_session, make_reader):
    _world(db_session)

    result = _service(db_session, make_reader).ask("what requires SKU-NOPE")

    assert result.route is Route.GRAPH_LOCAL
    assert "SKU-NOPE" in result.evidence["error"]


def test_a_portfolio_question_says_so_before_communities_exist(db_session, make_reader):
    _world(db_session)

    result = _service(db_session, make_reader).ask("which product groups are most exposed")

    assert result.route is Route.GRAPH_GLOBAL
    assert result.evidence["communities"] == []
    assert "rebuild" in result.evidence["note"]


def test_a_portfolio_question_returns_community_statistics_with_cached_summaries(db_session, graph_client, graph_ns, make_reader):
    seed_clusters(db_session)
    service = _service(db_session, make_reader)
    run_communities(graph_client, graph_ns)
    ids = [f"SKU-L-X{i}" for i in range(1, 5)]
    save_summary(db_session, member_hash=member_hash(ids), summary="The Xylo cluster.", model=SUMMARY_MODEL)

    result = service.ask("which product groups are most exposed")

    x = next(c for c in result.evidence["communities"] if "SKU-L-X1" in c["example_sku_ids"])
    y = next(c for c in result.evidence["communities"] if "SKU-L-Y1" in c["example_sku_ids"])
    assert x["summary"] == "The Xylo cluster." and x["size"] == 4 and x["discontinued_count"] == 1
    assert y["summary"] is None


def test_a_similarity_question_uses_the_vector_arm(db_session, make_reader):
    _world(db_session)
    embedder = FakeEmbedder()
    embed_pending_skus(db_session, embedder, on_batch_saved=lambda: None)
    service = _service(db_session, make_reader, embedder)

    result = service.ask("something like zorpwidget alpha 9000")

    assert result.route is Route.VECTOR and result.rule == "similarity_phrasing"
    assert result.evidence["matches"][0]["sku_id"] == "SKU-E-A1"


def test_similar_to_a_sku_embeds_that_skus_text_and_excludes_it(db_session, make_reader):
    _world(db_session)
    embedder = FakeEmbedder()
    embed_pending_skus(db_session, embedder, on_batch_saved=lambda: None)
    embedder.calls.clear()
    service = _service(db_session, make_reader, embedder)

    result = service.ask("similar to SKU-E-A1")

    assert embedder.calls == [["Zorpwidget Alpha 9000 | Cat-E-A | Zorpwidget Alpha"]]
    assert "SKU-E-A1" not in [m["sku_id"] for m in result.evidence["matches"]]
