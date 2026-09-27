from unittest.mock import MagicMock

import pytest

from app.intake.schemas import LineItemExtraction, QuoteRequestExtraction
from app.intake.service import process_email
from app.reference_data.repository import upsert_customer, upsert_sku
from core.llm.openai_client import ExtractionError


def _seed(db_session):
    upsert_customer(db_session, customer_id="CUST-A", name="Bramblewick Contractors", account_tier="Standard")
    upsert_sku(db_session, sku_id="SKU-A", name="Quazzlebolt Sprayer Assembly", category="C",
               list_price=1.0, discontinued=False, replaced_by=None, in_stock=True)
    db_session.flush()


def test_process_email_stores_resolved_quote_request(db_session):
    _seed(db_session)
    extraction = QuoteRequestExtraction(
        customer_name_as_written="Bramblewick Contractors",
        line_items=[LineItemExtraction(sku_name_as_written="Quazzlebolt Sprayer Assembly", quantity="4")],
        raw_text="need 4",
    )
    fake_client = MagicMock()
    fake_client.extract_quote_request.return_value = extraction

    result = process_email(db_session, "need 4 sprayers", fake_client)

    assert result.row.customer_id == "CUST-A"
    assert result.row.content_fingerprint["sku_ids"] == ["SKU-A"]
    assert result.resolved_line_items[0].sku_id == "SKU-A"


def test_process_email_handles_zero_line_items(db_session):
    _seed(db_session)
    extraction = QuoteRequestExtraction(customer_name_as_written="Bramblewick Contractors", line_items=[], raw_text="just asking")
    fake_client = MagicMock()
    fake_client.extract_quote_request.return_value = extraction

    result = process_email(db_session, "just asking a question", fake_client)

    assert result.row.content_fingerprint["sku_ids"] == []
    assert result.resolved_line_items == []


def test_process_email_raises_and_stores_nothing_on_extraction_failure(db_session):
    _seed(db_session)
    fake_client = MagicMock()
    fake_client.extract_quote_request.side_effect = ExtractionError("boom")

    with pytest.raises(ExtractionError):
        process_email(db_session, "some email", fake_client)

    from sqlalchemy import select
    from app.intake.models import QuoteRequestRow
    assert db_session.scalars(select(QuoteRequestRow)).all() == []
