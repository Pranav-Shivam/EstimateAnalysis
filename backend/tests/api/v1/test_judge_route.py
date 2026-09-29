import uuid

from fastapi.testclient import TestClient

from api.v1.judge.route import get_judge_client
from app.estimate.repository import save_estimate_draft
from app.intake.repository import save_quote_request
from core.db.session import get_session
from core.graph.client import get_graph_client
from main import app
from tests.app.estimate.seed import seed_world
from tests.app.judge.fakes import ScriptedJudgeClient
from tests.graph_support import FailingGraphClient


def _estimate_row(session, status="ready"):
    request = save_quote_request(
        session, raw_email_text="need parts", parsed_json={"resolved_line_items": []},
        content_fingerprint={}, style_fingerprint={}, customer_id="CUST-E1", contract_id="CTR-E1",
    )
    draft = None
    if status == "ready":
        draft = {"customer_id": "CUST-E1", "contract_id": "CTR-E1", "lines": [
            {"sku_id": "SKU-E-A1", "quantity": 1, "unit_price": 100.0, "price_source": "list", "discount_pct": 0.0},
        ]}
    return save_estimate_draft(
        session, quote_request_id=request.id, status=status, draft=draft, violations=[], iterations=1,
        reason=None if status == "ready" else "blocked",
    )


def _post(session, client, estimate_id):
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_judge_client] = lambda: client
    try:
        return TestClient(app).post(f"/v1/judge/{estimate_id}")
    finally:
        app.dependency_overrides.clear()


def _trusted_client():
    return ScriptedJudgeClient([
        {"name": "price_provenance", "score": 0.95, "rationale": "list price"},
        {"name": "contract_discount", "score": 1.0, "rationale": "no discount"},
        {"name": "graph_completion", "score": 0.9, "rationale": "complete"},
    ])


def test_judge_endpoint_returns_404_for_unknown_estimate(db_session):
    response = _post(db_session, ScriptedJudgeClient([]), uuid.uuid4())

    assert response.status_code == 404


def test_judge_endpoint_persists_a_trusted_verdict_with_no_review_item(db_session, make_reader):
    seed_world(db_session)
    make_reader()
    row = _estimate_row(db_session)

    response = _post(db_session, _trusted_client(), row.id)

    body = response.json()
    assert response.status_code == 200
    assert body["trusted"] is True
    assert body["review_item"] is None


def test_judge_endpoint_creates_a_review_item_below_threshold(db_session, make_reader):
    seed_world(db_session)
    make_reader()
    row = _estimate_row(db_session)
    client = ScriptedJudgeClient([
        {"name": "price_provenance", "score": 0.95, "rationale": "list price"},
        {"name": "contract_discount", "score": 1.0, "rationale": "no discount"},
        {"name": "graph_completion", "score": 0.2, "rationale": "evidence is thin"},
    ])

    response = _post(db_session, client, row.id)

    body = response.json()
    assert body["trusted"] is False
    assert body["review_item"]["dimension"] == "graph_completion"


def test_judge_endpoint_short_circuits_a_needs_review_draft(db_session):
    seed_world(db_session)
    row = _estimate_row(db_session, status="needs_review")

    response = _post(db_session, ScriptedJudgeClient([]), row.id)

    body = response.json()
    assert body["flagged_dimension"] == "guardrail"
    assert body["review_item"]["fact"] == "blocked"


def test_judge_endpoint_allows_scoring_the_same_estimate_twice(db_session, make_reader):
    seed_world(db_session)
    make_reader()
    row = _estimate_row(db_session)

    first = _post(db_session, _trusted_client(), row.id)
    second = _post(db_session, _trusted_client(), row.id)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["judge_verdict_id"] != second.json()["judge_verdict_id"]


def test_judge_endpoint_returns_503_when_the_graph_is_down(db_session):
    seed_world(db_session)
    row = _estimate_row(db_session)
    app.dependency_overrides[get_graph_client] = lambda: FailingGraphClient()
    try:
        response = _post(db_session, _trusted_client(), row.id)
    finally:
        app.dependency_overrides.pop(get_graph_client, None)

    assert response.status_code == 503
