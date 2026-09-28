import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from core.db.base import Base


class EstimateDraftRow(Base):
    __tablename__ = "estimate_drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quote_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("quote_requests.id"), index=True
    )
    status: Mapped[str] = mapped_column(Text)
    draft: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    violations: Mapped[list] = mapped_column(JSONB)
    iterations: Mapped[int]
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
