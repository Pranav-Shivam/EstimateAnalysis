import pytest
from sqlalchemy import delete, func, select

from app.retrieval.models import CommunitySummary, SkuEmbedding
from app.retrieval.repository import save_embeddings, save_summary
from app.retrieval.snapshot import (
    SnapshotMismatch, export_snapshot, read_snapshot, restore_snapshot, write_snapshot,
)
from core.llm.openai_embedding_client import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL
from tests.app.estimate.seed import seed_structure, seed_world


def _vector(seed: float) -> list[float]:
    return [seed] * EMBEDDING_DIMENSIONS


def _seeded(db_session):
    seed_world(db_session)
    seed_structure(db_session)
    db_session.execute(delete(SkuEmbedding))
    db_session.execute(delete(CommunitySummary))
    save_embeddings(db_session, EMBEDDING_MODEL, [("SKU-E-A1", _vector(0.5)), ("SKU-E-B1", _vector(-0.25))])
    save_summary(db_session, member_hash="h1", summary="Fittings and their adapters", model="gpt-test")


def test_a_snapshot_written_to_disk_restores_the_same_rows_after_the_tables_are_emptied(db_session, tmp_path):
    _seeded(db_session)
    write_snapshot(export_snapshot(db_session), tmp_path / "snapshot.json.gz")
    db_session.execute(delete(SkuEmbedding))
    db_session.execute(delete(CommunitySummary))

    result = restore_snapshot(db_session, read_snapshot(tmp_path / "snapshot.json.gz"))

    assert (result.embeddings, result.summaries) == (2, 1)
    restored = db_session.get(SkuEmbedding, "SKU-E-A1")
    assert restored.model == EMBEDDING_MODEL and list(restored.embedding) == pytest.approx(_vector(0.5))
    assert db_session.get(CommunitySummary, "h1").summary == "Fittings and their adapters"


def test_restoring_twice_does_not_duplicate_rows(db_session):
    _seeded(db_session)
    snapshot = export_snapshot(db_session)

    restore_snapshot(db_session, snapshot)
    restore_snapshot(db_session, snapshot)

    assert db_session.scalar(select(func.count()).select_from(SkuEmbedding)) == 2
    assert db_session.scalar(select(func.count()).select_from(CommunitySummary)) == 1


def test_a_snapshot_for_skus_that_are_not_loaded_is_refused_and_writes_nothing(db_session):
    _seeded(db_session)
    snapshot = export_snapshot(db_session)
    snapshot["embeddings"].append({"sku_id": "SKU-NOT-LOADED", "model": EMBEDDING_MODEL, "embedding": _vector(1.0)})
    db_session.execute(delete(SkuEmbedding))

    with pytest.raises(SnapshotMismatch, match="SKU-NOT-LOADED"):
        restore_snapshot(db_session, snapshot)

    assert db_session.scalar(select(func.count()).select_from(SkuEmbedding)) == 0
