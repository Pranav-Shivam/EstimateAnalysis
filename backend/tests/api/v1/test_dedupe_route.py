import uuid

from fastapi.testclient import TestClient

from app.intake.repository import save_quote_request
from app.reference_data.repository import upsert_customer, upsert_site
from core.db.session import get_session
from main import app


def _seed_customer_and_site(db_session):
    # quote_requests.customer_id / site_id are foreign keys, so the referenced
    # rows must exist before a quote request can point at them.
    upsert_customer(db_session, customer_id="CUST-A", name="Test Customer", account_tier="Standard")
    upsert_site(db_session, site_id="SITE-A", customer_id="CUST-A", address="1 Test St", zip_code="00000")
    db_session.flush()


def test_dedupe_endpoint_returns_duplicate_verdict(db_session):
    _seed_customer_and_site(db_session)
    first = save_quote_request(
        db_session, raw_email_text="t1", parsed_json={}, content_fingerprint={"sku_ids": ["SKU-A"]},
        style_fingerprint={"tokens": []}, customer_id="CUST-A", site_id="SITE-A",
    )
    second = save_quote_request(
        db_session, raw_email_text="t2", parsed_json={}, content_fingerprint={"sku_ids": ["SKU-A"]},
        style_fingerprint={"tokens": []}, customer_id="CUST-A", site_id="SITE-A",
    )
    db_session.flush()

    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    try:
        response = client.post(f"/v1/dedupe/{second.id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["verdicts"][0]["candidate_quote_request_id"] == str(first.id)
    assert body["verdicts"][0]["verdict"] == "DUPLICATE_OF"


def test_dedupe_endpoint_returns_404_for_unknown_id(db_session):
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    try:
        response = client.post(f"/v1/dedupe/{uuid.uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
