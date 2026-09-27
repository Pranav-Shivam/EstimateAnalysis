import uuid
from datetime import datetime

from sqlalchemy import Float, ForeignKey, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from core.db.base import Base


class DedupeVerdictRow(Base):
    __tablename__ = "dedupe_verdicts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quote_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quote_requests.id"))
    candidate_quote_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quote_requests.id"))
    verdict: Mapped[str] = mapped_column(Text)
    content_jaccard: Mapped[float] = mapped_column(Float)
    style_jaccard: Mapped[float] = mapped_column(Float)
    signals_fired: Mapped[list[str]] = mapped_column(ARRAY(Text))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
