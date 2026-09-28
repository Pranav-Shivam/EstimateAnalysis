import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from api.v1.estimate import route as route_module
from api.v1.estimate.route import get_agent_client
from app.intake.repository import save_quote_request
from core.db.session import get_session
from core.llm.openai_agent_client import AgentError
from main import app
from tests.app.estimate.fakes import ScriptedLLM, submit_turn
from tests.app.estimate.seed import seed_world


def _request_row(session):
    return save_quote_request(
        session, raw_email_text="need 2", parsed_json={"resolved_line_items": []},
        content_fingerprint={"sku_ids": []}, style_fingerprint={"tokens": []},
        customer_id="CUST-E1", contract_id="CTR-E1",
    )


def _post(session, llm, body):
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_agent_client] = lambda: llm
    try:
        return TestClient(app).post("/v1/estimate", json=body)
    finally:
        app.dependency_overrides.clear()


def test_estimate_endpoint_returns_a_ready_draft(db_session):
    seed_world(db_session)
    row = _request_row(db_session)
    draft = {"customer_id": "CUST-E1", "contract_id": "CTR-E1", "lines": [
        {"sku_id": "SKU-E-A1", "quantity": 2, "unit_price": 100.0, "price_source": "list", "discount_pct": 10.0}]}

    response = _post(db_session, ScriptedLLM([submit_turn(draft)]), {"quote_request_id": str(row.id)})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["as_of"] == "2024-09-01"
    assert body["totals"]["net_total"] == 180.0
    assert body["draft"]["lines"][0]["sku_id"] == "SKU-E-A1"
    assert body["estimate_id"]


def test_estimate_endpoint_reports_blocked_draft_as_needs_review(db_session):
    seed_world(db_session)
    row = _request_row(db_session)
    bad = {"customer_id": "CUST-E1", "contract_id": "CTR-E1", "lines": [
        {"sku_id": "SKU-E-B1", "quantity": 1, "unit_price": 50.0, "price_source": "list", "discount_pct": 10.0}]}

    response = _post(db_session, ScriptedLLM([submit_turn(bad, call_id=f"c{i}") for i in range(4)]),
                     {"quote_request_id": str(row.id)})

    body = response.json()
    assert body["status"] == "needs_review"
    assert body["violations"][0]["guardrail"] == "contract_discount"


def test_estimate_endpoint_accepts_an_explicit_as_of(db_session):
    seed_world(db_session)
    row = _request_row(db_session)
    draft = {"customer_id": "CUST-E1", "contract_id": "CTR-E1", "lines": [
        {"sku_id": "SKU-E-A1", "quantity": 1, "unit_price": 100.0, "price_source": "list", "discount_pct": 10.0}]}

    response = _post(db_session, ScriptedLLM([submit_turn(draft, call_id=f"c{i}") for i in range(4)]),
                     {"quote_request_id": str(row.id), "as_of": "2026-01-01"})

    body = response.json()
    assert body["as_of"] == "2026-01-01"
    assert body["status"] == "needs_review"
    assert "not active" in body["violations"][0]["message"]


def test_estimate_endpoint_returns_404_for_unknown_quote_request(db_session):
    response = _post(db_session, ScriptedLLM([]), {"quote_request_id": str(uuid.uuid4())})

    assert response.status_code == 404


def test_estimate_endpoint_returns_502_when_the_agent_call_fails(db_session):
    seed_world(db_session)
    row = _request_row(db_session)

    class FailingLLM:
        def next_turn(self, messages, tools):
            raise AgentError("boom")

    response = _post(db_session, FailingLLM(), {"quote_request_id": str(row.id)})

    assert response.status_code == 502


def test_get_agent_client_builds_openai_client_with_settings_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-from-settings")
    client = get_agent_client()
    assert client._client.api_key == "sk-test-from-settings"


def test_get_agent_client_passes_the_key_from_settings_not_the_process_environment(monkeypatch):
    # OpenAI() falls back to the OPENAI_API_KEY env var on its own, which hides a dropped key when the
    # key is only exported. Settings also reads .env, which never reaches os.environ, so pin the key
    # to Settings alone.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(route_module, "Settings", lambda: SimpleNamespace(openai_api_key="sk-only-in-settings"))

    client = route_module.get_agent_client()

    assert client._client.api_key == "sk-only-in-settings"
