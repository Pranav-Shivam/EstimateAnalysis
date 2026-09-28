from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.reference_data.models import ProductFamily, Sku
from app.retrieval.models import CommunitySummary, SkuEmbedding


def get_summaries(session: Session, hashes: list[str]) -> dict[str, str]:
    if not hashes:
        return {}
    rows = session.execute(
        select(CommunitySummary.member_hash, CommunitySummary.summary).where(CommunitySummary.member_hash.in_(hashes))
    )
    return {member_hash: summary for member_hash, summary in rows}


def save_summary(session: Session, *, member_hash: str, summary: str, model: str) -> None:
    row = session.get(CommunitySummary, member_hash)
    if row is None:
        row = CommunitySummary(member_hash=member_hash)
        session.add(row)
    row.summary = summary
    row.model = model
    session.flush()


def skus_missing_embedding(session: Session, model: str) -> list[tuple[Sku, str | None]]:
    """SKUs with no embedding from this model, with their family name (None when they have no family)."""
    rows = session.execute(
        select(Sku, ProductFamily.name)
        .outerjoin(ProductFamily, Sku.family_id == ProductFamily.family_id)
        .outerjoin(SkuEmbedding, and_(SkuEmbedding.sku_id == Sku.sku_id, SkuEmbedding.model == model))
        .where(SkuEmbedding.sku_id.is_(None))
        .order_by(Sku.sku_id)
    )
    return [(sku, family_name) for sku, family_name in rows]


def save_embeddings(session: Session, model: str, items: list[tuple[str, list[float]]]) -> None:
    for sku_id, vector in items:
        row = session.get(SkuEmbedding, sku_id)
        if row is None:
            row = SkuEmbedding(sku_id=sku_id)
            session.add(row)
        row.embedding = vector
        row.model = model
    session.flush()


def has_embeddings(session: Session) -> bool:
    return session.scalar(select(SkuEmbedding.sku_id).limit(1)) is not None


def nearest_skus(
    session: Session, vector: list[float], k: int, exclude_sku_id: str | None = None,
) -> list[tuple[Sku, float]]:
    distance = SkuEmbedding.embedding.cosine_distance(vector)
    statement = select(Sku, distance).join(SkuEmbedding, SkuEmbedding.sku_id == Sku.sku_id)
    if exclude_sku_id is not None:
        statement = statement.where(Sku.sku_id != exclude_sku_id)
    rows = session.execute(statement.order_by(distance, Sku.sku_id).limit(k))
    return [(sku, float(value)) for sku, value in rows]


def sku_with_family(session: Session, sku_id: str) -> tuple[Sku, str | None] | None:
    row = session.execute(
        select(Sku, ProductFamily.name)
        .outerjoin(ProductFamily, Sku.family_id == ProductFamily.family_id)
        .where(Sku.sku_id == sku_id)
    ).first()
    return (row[0], row[1]) if row else None
