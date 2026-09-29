import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from core.db.base import Base


class JudgeVerdictRow(Base):
    __tablename__ = "judge_verdicts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    estimate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("estimate_drafts.id"), index=True)
    model: Mapped[str] = mapped_column(Text)
    dimensions: Mapped[list] = mapped_column(JSONB)
    overall_confidence: Mapped[float]
    flagged_dimension: Mapped[str] = mapped_column(Text)
    trusted: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ReviewItemRow(Base):
    __tablename__ = "review_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    judge_verdict_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("judge_verdicts.id"), index=True)
    estimate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("estimate_drafts.id"), index=True)
    dimension: Mapped[str] = mapped_column(Text)
    fact: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONB)
    line_index: Mapped[int | None]
    status: Mapped[str] = mapped_column(Text, server_default=text("'open'"))
    outcome: Mapped[str | None] = mapped_column(Text)
    correction: Mapped[dict | None] = mapped_column(JSONB)
    resolved_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class EvalCaseRow(Base):
    __tablename__ = "eval_cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_review_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("review_items.id"))
    case_id: Mapped[str] = mapped_column(Text, unique=True)
    label: Mapped[str] = mapped_column(Text)
    estimate_status: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
