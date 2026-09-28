from collections.abc import Callable
from typing import Protocol

from sqlalchemy.orm import Session

from app.reference_data.models import Sku
from app.retrieval.repository import (
    has_embeddings, nearest_skus, save_embeddings, sku_with_family, skus_missing_embedding,
)
from core.llm.openai_embedding_client import EMBEDDING_MODEL

EMBED_BATCH_SIZE = 100
DEFAULT_K = 5
CHARS_PER_TOKEN = 4


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class EmbeddingsNotBuilt(Exception):
    pass


def sku_embedding_text(name: str, category: str, family_name: str | None) -> str:
    return f"{name} | {category} | {family_name or 'no family'}"


def estimate_embedding_tokens(pending: list[tuple[Sku, str | None]]) -> int:
    return sum(len(sku_embedding_text(sku.name, sku.category, family)) // CHARS_PER_TOKEN + 1 for sku, family in pending)


def embed_pending_skus(session: Session, embedder: Embedder, on_batch_saved: Callable[[], None]) -> int:
    """Embed every SKU that has no embedding from the current model. `on_batch_saved` runs after each batch so the
    caller can commit; a failure part-way keeps the batches already paid for."""
    pending = skus_missing_embedding(session, EMBEDDING_MODEL)
    for start in range(0, len(pending), EMBED_BATCH_SIZE):
        batch = pending[start:start + EMBED_BATCH_SIZE]
        vectors = embedder.embed([sku_embedding_text(sku.name, sku.category, family) for sku, family in batch])
        save_embeddings(session, EMBEDDING_MODEL, [(sku.sku_id, vector) for (sku, _), vector in zip(batch, vectors)])
        on_batch_saved()
    return len(pending)


def embedding_text_for_sku(session: Session, sku_id: str) -> str | None:
    found = sku_with_family(session, sku_id)
    if found is None:
        return None
    sku, family_name = found
    return sku_embedding_text(sku.name, sku.category, family_name)


def vector_search(
    session: Session, embedder: Embedder, text: str, k: int = DEFAULT_K, exclude_sku_id: str | None = None,
) -> list[dict]:
    if not has_embeddings(session):
        raise EmbeddingsNotBuilt("SKU embeddings are not built; run scripts/embed_skus.py")
    [vector] = embedder.embed([text])
    return [
        {
            "sku_id": sku.sku_id, "name": sku.name, "category": sku.category, "list_price": sku.list_price,
            "discontinued": sku.discontinued, "in_stock": sku.in_stock, "distance": round(distance, 4),
        }
        for sku, distance in nearest_skus(session, vector, k, exclude_sku_id)
    ]


def run_embedding_job(
    session: Session, embedder_factory: Callable[[], Embedder], *, yes: bool, out: Callable[[str], None],
    on_batch_saved: Callable[[], None],
) -> int | None:
    """A dry run unless `yes`: report the plan and cost estimate, and only then build the paid client."""
    pending = skus_missing_embedding(session, EMBEDDING_MODEL)
    out(f"{len(pending)} SKUs need an embedding; estimated {estimate_embedding_tokens(pending)} tokens with model {EMBEDDING_MODEL}")
    if not yes:
        out("dry run: pass --yes to call the API")
        return None
    if not pending:
        return 0
    count = embed_pending_skus(session, embedder_factory(), on_batch_saved)
    out(f"embedded {count} SKUs")
    return count
