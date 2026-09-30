from fastapi.testclient import TestClient

from app.estimate.repository import save_estimate_draft
from app.intake.repository import save_quote_request
from app.judge.repository import save_judge_verdict, save_review_item
from core.db.session import get_session
from main import app
from tests.app.estimate.seed import seed_world


def _open_review_item(session):
    seed_world(session)
    request = save_quote_request(
        session, raw_email_text="need parts", parsed_json={"resolved_line_items": []},
        content_fingerprint={}, style_fingerprint={}, customer_id="CUST-E1", contract_id="CTR-E1",
    )
    draft_row = save_estimate_draft(
        session, quote_request_id=request.id, status="ready", draft={"lines": []}, violations=[],
        iterations=1, reason=None,
    )
    verdict = save_judge_verdict(
        session, estimate_id=draft_row.id, model="claude-haiku-4-5-20251001", dimensions=[],
        overall_confidence=0.2, flagged_dimension="graph_completion", trusted=False,
    )
    return save_review_item(
        session, judge_verdict_id=verdict.id, estimate_id=draft_row.id, dimension="graph_completion",
        fact="check this", evidence={}, line_index=0,
    )


def test_review_endpoint_lists_open_items(db_session):
    item = _open_review_item(db_session)
    app.dependency_overrides[get_session] = lambda: db_session
    try:
        response = TestClient(app).get("/v1/review")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    ids = [row["id"] for row in response.json()]
    assert str(item.id) in ids


def _get(session, query=""):
    app.dependency_overrides[get_session] = lambda: session
    try:
        return TestClient(app).get(f"/v1/review{query}")
    finally:
        app.dependency_overrides.clear()


def _resolve(item):
    item.status = "corrected"
    item.outcome = "corrected"
    item.correction = {"sku_id": "SKU-E-A1", "required_sku_id": "SKU-E-B1"}


def test_review_endpoint_default_excludes_resolved_items(db_session):
    open_item = _open_review_item(db_session)
    resolved_item = _open_review_item(db_session)
    _resolve(resolved_item)
    db_session.flush()

    ids = [row["id"] for row in _get(db_session).json()]

    assert str(open_item.id) in ids
    assert str(resolved_item.id) not in ids


def test_review_endpoint_resolved_filter_returns_outcome_and_correction(db_session):
    open_item = _open_review_item(db_session)
    resolved_item = _open_review_item(db_session)
    _resolve(resolved_item)
    db_session.flush()

    rows = {row["id"]: row for row in _get(db_session, "?status=resolved").json()}

    assert str(open_item.id) not in rows
    assert rows[str(resolved_item.id)]["outcome"] == "corrected"
    assert rows[str(resolved_item.id)]["correction"] == {"sku_id": "SKU-E-A1", "required_sku_id": "SKU-E-B1"}


def test_review_endpoint_all_filter_returns_both(db_session):
    open_item = _open_review_item(db_session)
    resolved_item = _open_review_item(db_session)
    _resolve(resolved_item)
    db_session.flush()

    ids = [row["id"] for row in _get(db_session, "?status=all").json()]

    assert str(open_item.id) in ids
    assert str(resolved_item.id) in ids


def test_review_endpoint_includes_the_quote_request_id(db_session):
    item = _open_review_item(db_session)
    db_session.flush()

    row = next(r for r in _get(db_session).json() if r["id"] == str(item.id))

    assert row["quote_request_id"] is not None


def test_review_endpoint_rejects_an_unknown_status(db_session):
    assert _get(db_session, "?status=bogus").status_code == 422
