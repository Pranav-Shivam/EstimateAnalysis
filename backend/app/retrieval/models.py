from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from core.db.base import Base
from core.llm.openai_embedding_client import EMBEDDING_DIMENSIONS


class SkuEmbedding(Base):
    __tablename__ = "sku_embeddings"

    sku_id: Mapped[str] = mapped_column(ForeignKey("skus.sku_id"), primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    model: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class CommunitySummary(Base):
    __tablename__ = "community_summaries"

    member_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    summary: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
