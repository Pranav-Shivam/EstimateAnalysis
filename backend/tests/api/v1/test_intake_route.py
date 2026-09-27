from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from api.v1.intake.route import get_llm_client
from app.intake.schemas import LineItemExtraction, QuoteRequestExtraction
from app.reference_data.repository import upsert_customer, upsert_sku
from core.db.session import get_session
from core.llm.openai_client import ExtractionError
from main import app


def test_submit_email_returns_resolved_quote_request(db_session):
    upsert_customer(db_session, customer_id="CUST-A", name="Bramblewick Contractors", account_tier="Standard")
    upsert_sku(db_session, sku_id="SKU-A", name="Quazzlebolt Sprayer Assembly", category="C",
               list_price=1.0, discontinued=False, replaced_by=None, in_stock=True)
    db_session.flush()

    fake_llm_client = MagicMock()
    fake_llm_client.extract_quote_request.return_value = QuoteRequestExtraction(
        customer_name_as_written="Bramblewick Contractors",
        line_items=[LineItemExtraction(sku_name_as_written="Quazzlebolt Sprayer Assembly", quantity="4")],
        raw_text="need 4",
    )

    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_llm_client] = lambda: fake_llm_client
    client = TestClient(app)
    try:
        response = client.post("/v1/intake", json={"email_text": "need 4 sprayers"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["customer_id"] == "CUST-A"
    assert body["line_items"][0]["sku_id"] == "SKU-A"


def test_get_llm_client_builds_openai_client_with_settings_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-from-settings")
    client = get_llm_client()
    assert client._client.api_key == "sk-test-from-settings"


def test_submit_email_returns_502_on_extraction_failure(db_session):
    fake_llm_client = MagicMock()
    fake_llm_client.extract_quote_request.side_effect = ExtractionError("boom")

    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_llm_client] = lambda: fake_llm_client
    client = TestClient(app)
    try:
        response = client.post("/v1/intake", json={"email_text": "some email"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
