import uuid

from fastapi.testclient import TestClient
from procrastinate import testing

from app.consolidation.tasks import app as consolidation_app
from app.estimate.repository import save_estimate_draft
from app.intake.repository import save_quote_request
from app.judge.repository import save_judge_verdict, save_review_item
from core.db.session import get_session
from main import app
from tests.app.estimate.seed import seed_world

PRICE_EVIDENCE = {"lines": [{"line_index": 0, "sku_id": "SKU-E-GAP", "price_source": "predicted"}]}


def _open_review_item(session):
    seed_world(session)
    request = save_quote_request(
        session, raw_email_text="need parts", parsed_json={"resolved_line_items": []},
        content_fingerprint={}, style_fingerprint={}, customer_id="CUST-E1", contract_id="CTR-E1",
    )
    estimate = save_estimate_draft(
        session, quote_request_id=request.id, status="ready", draft={"lines": []}, violations=[],
        iterations=1, reason=None,
    )
    verdict = save_judge_verdict(
        session, estimate_id=estimate.id, model="m", dimensions=[], overall_confidence=0.1,
        flagged_dimension="price_provenance", trusted=False,
    )
    return save_review_item(
        session, judge_verdict_id=verdict.id, estimate_id=estimate.id, dimension="price_provenance",
        fact="thin evidence", evidence=PRICE_EVIDENCE, line_index=None,
    )


def _post(session, review_item_id, body):
    app.dependency_overrides[get_session] = lambda: session
    in_memory = testing.InMemoryConnector()
    try:
        with consolidation_app.replace_connector(in_memory):
            return TestClient(app).post(f"/v1/review/{review_item_id}/resolve", json=body)
    finally:
        app.dependency_overrides.clear()


def test_resolve_returns_404_for_an_unknown_review_item(db_session):
    response = _post(db_session, uuid.uuid4(), {"outcome": "approved"})
    assert response.status_code == 404


def test_resolve_approve_returns_200_with_no_consolidation(db_session):
    row = _open_review_item(db_session)

    response = _post(db_session, row.id, {"outcome": "approved"})

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "approved"
    assert body["consolidation_enqueued"] is False


def test_resolve_corrected_returns_200_and_enqueues_consolidation(db_session):
    row = _open_review_item(db_session)

    response = _post(db_session, row.id, {
        "outcome": "corrected", "correction": {"sku_id": "SKU-E-GAP", "corrected_unit_price": 42.5},
    })

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "corrected"
    assert body["consolidation_enqueued"] is True


def test_resolve_rejects_an_invalid_correction_with_422(db_session):
    row = _open_review_item(db_session)

    response = _post(db_session, row.id, {
        "outcome": "corrected", "correction": {"sku_id": "SKU-E-A1", "corrected_unit_price": 1.0},
    })

    assert response.status_code == 422


def test_resolve_rejects_an_unknown_outcome_with_422(db_session):
    row = _open_review_item(db_session)

    response = _post(db_session, row.id, {"outcome": "open"})

    assert response.status_code == 422


def test_resolve_rejects_an_already_resolved_item_with_409(db_session):
    row = _open_review_item(db_session)
    _post(db_session, row.id, {"outcome": "approved"})

    response = _post(db_session, row.id, {"outcome": "approved"})

    assert response.status_code == 409
