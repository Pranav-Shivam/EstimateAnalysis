import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from core.db.base import Base


class QuoteRequestRow(Base):
    __tablename__ = "quote_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[str | None] = mapped_column(Text)
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.customer_id"))
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.site_id"))
    contract_id: Mapped[str | None] = mapped_column(ForeignKey("contracts.contract_id"))
    raw_email_text: Mapped[str] = mapped_column(Text)
    parsed_json: Mapped[dict] = mapped_column(JSONB)
    content_fingerprint: Mapped[dict] = mapped_column(JSONB)
    style_fingerprint: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
