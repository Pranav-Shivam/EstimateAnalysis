import pytest
from sqlalchemy import delete, select

from app.reference_data.models import Sku
from app.retrieval.models import SkuEmbedding
from app.retrieval.repository import has_embeddings, skus_missing_embedding
from app.retrieval.vector import (
    EMBED_BATCH_SIZE, EmbeddingsNotBuilt, embed_pending_skus, embedding_text_for_sku, estimate_embedding_tokens,
    run_embedding_job, sku_embedding_text, vector_search,
)
from core.llm.openai_embedding_client import EMBEDDING_MODEL
from tests.app.estimate.seed import seed_structure, seed_world
from tests.graph_support import FakeEmbedder


def _world(db_session):
    seed_world(db_session)
    seed_structure(db_session)


def test_embedding_text_joins_name_category_and_family():
    assert sku_embedding_text("Zorpwidget 9000", "Cat-E-A", "Zorpwidget Alpha") == "Zorpwidget 9000 | Cat-E-A | Zorpwidget Alpha"
    assert sku_embedding_text("Loose Part", "Cat-X", None) == "Loose Part | Cat-X | no family"


def test_a_sku_without_an_embedding_is_pending(db_session):
    _world(db_session)

    pending = {sku.sku_id: family for sku, family in skus_missing_embedding(db_session, EMBEDDING_MODEL)}

    assert pending["SKU-E-A1"] == "Zorpwidget Alpha"
    assert pending["SKU-E-B1"] is None


def test_embedding_pending_skus_saves_vectors_in_batches_and_is_idempotent(db_session):
    _world(db_session)
    embedder, saved = FakeEmbedder(), []

    first = embed_pending_skus(db_session, embedder, on_batch_saved=lambda: saved.append(1))
    second = embed_pending_skus(db_session, embedder, on_batch_saved=lambda: saved.append(1))

    assert first >= 8 and second == 0
    assert all(len(batch) <= EMBED_BATCH_SIZE for batch in embedder.calls)
    assert len(saved) == len(embedder.calls)
    row = db_session.get(SkuEmbedding, "SKU-E-A1")
    assert row.model == EMBEDDING_MODEL and len(row.embedding) == 1536
    assert not [sku for sku, _ in skus_missing_embedding(db_session, EMBEDDING_MODEL)]


def test_a_sku_embedded_with_another_model_is_pending_again_and_replaced(db_session):
    _world(db_session)
    embed_pending_skus(db_session, FakeEmbedder(), on_batch_saved=lambda: None)
    db_session.get(SkuEmbedding, "SKU-E-A1").model = "older-model"
    db_session.flush()

    assert "SKU-E-A1" in {sku.sku_id for sku, _ in skus_missing_embedding(db_session, EMBEDDING_MODEL)}
    embed_pending_skus(db_session, FakeEmbedder(), on_batch_saved=lambda: None)

    assert db_session.get(SkuEmbedding, "SKU-E-A1").model == EMBEDDING_MODEL


def test_search_returns_the_closest_skus_first(db_session):
    _world(db_session)
    embedder = FakeEmbedder()
    embed_pending_skus(db_session, embedder, on_batch_saved=lambda: None)

    matches = vector_search(db_session, embedder, "zorpwidget alpha 9000")

    assert matches[0]["sku_id"] == "SKU-E-A1"
    assert matches[0]["distance"] < 0.5
    assert set(matches[0]) == {"sku_id", "name", "category", "list_price", "discontinued", "in_stock", "distance"}
    assert [m["distance"] for m in matches] == sorted(m["distance"] for m in matches)
    assert len(matches) <= 5


def test_search_can_exclude_the_sku_it_started_from(db_session):
    _world(db_session)
    embedder = FakeEmbedder()
    embed_pending_skus(db_session, embedder, on_batch_saved=lambda: None)

    matches = vector_search(db_session, embedder, "zorpwidget alpha 9000", exclude_sku_id="SKU-E-A1")

    assert "SKU-E-A1" not in [m["sku_id"] for m in matches]


def test_search_with_no_embeddings_raises_a_clear_error(db_session):
    db_session.execute(delete(SkuEmbedding))
    db_session.flush()

    assert has_embeddings(db_session) is False
    with pytest.raises(EmbeddingsNotBuilt, match="embed_skus"):
        vector_search(db_session, FakeEmbedder(), "anything")


def test_embedding_text_for_a_known_sku_uses_its_family(db_session):
    _world(db_session)

    assert embedding_text_for_sku(db_session, "SKU-E-A1") == "Zorpwidget Alpha 9000 | Cat-E-A | Zorpwidget Alpha"
    assert embedding_text_for_sku(db_session, "SKU-NOPE") is None


def test_token_estimate_grows_with_the_pending_list(db_session):
    _world(db_session)
    pending = skus_missing_embedding(db_session, EMBEDDING_MODEL)

    assert 0 < estimate_embedding_tokens(pending[:1]) < estimate_embedding_tokens(pending[:5])
    assert estimate_embedding_tokens([]) == 0


def test_a_dry_run_reports_the_plan_and_never_builds_the_client(db_session):
    _world(db_session)
    lines, built = [], []

    result = run_embedding_job(
        db_session, lambda: built.append(1) or FakeEmbedder(), yes=False, out=lines.append, on_batch_saved=lambda: None,
    )

    assert result is None and built == []
    text = "\n".join(lines)
    assert "SKUs need an embedding" in text and EMBEDDING_MODEL in text
    assert "dry run" in text and "--yes" in text
    assert db_session.get(SkuEmbedding, "SKU-E-A1") is None


def test_the_job_with_yes_builds_the_client_and_embeds(db_session):
    _world(db_session)
    embedder = FakeEmbedder()

    result = run_embedding_job(db_session, lambda: embedder, yes=True, out=lambda line: None, on_batch_saved=lambda: None)

    assert result >= 8 and embedder.calls
    assert db_session.get(SkuEmbedding, "SKU-E-A1") is not None
