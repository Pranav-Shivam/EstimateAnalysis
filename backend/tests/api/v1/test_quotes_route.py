import uuid
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import event

from app.dedupe.repository import save_verdict
from app.estimate.repository import save_estimate_draft
from app.intake.repository import save_quote_request
from app.judge.repository import save_judge_verdict, save_review_item
from core.db.session import get_session
from main import app
from tests.app.estimate.seed import seed_world

# Far in the future so these rows sort ahead of any committed demo data, and stamped explicitly because one
# transaction gives every row the same server-side created_at.
BASE = datetime(2030, 1, 1, 12, 0)
LINE = {"sku_id": "SKU-E-A1", "quantity": 2, "unit_price": 100.0, "price_source": "list", "discount_pct": 0.0}


def _stamp(session, row, minutes):
    row.created_at = BASE + timedelta(minutes=minutes)
    session.flush()


def _request(session, minutes=0, case_id=None):
    row = save_quote_request(
        session, raw_email_text="need parts", parsed_json={"resolved_line_items": []},
        content_fingerprint={}, style_fingerprint={}, customer_id=None, case_id=case_id,
    )
    _stamp(session, row, minutes)
    return row


def _estimate(session, request, minutes, status="ready"):
    draft = None if status == "needs_review" else {"customer_id": None, "contract_id": None, "lines": [LINE]}
    row = save_estimate_draft(
        session, quote_request_id=request.id, status=status, draft=draft, violations=[], iterations=1,
        reason="blocked" if status == "needs_review" else None,
    )
    _stamp(session, row, minutes)
    return row


def _verdict(session, estimate, minutes, trusted):
    row = save_judge_verdict(
        session, estimate_id=estimate.id, model="test-judge",
        dimensions=[{"name": "graph_completion", "score": 0.2, "rationale": "thin", "evidence": []}],
        overall_confidence=0.95 if trusted else 0.2, flagged_dimension="graph_completion", trusted=trusted,
    )
    _stamp(session, row, minutes)
    return row


def _item(session, estimate, verdict, evidence=None, status="open"):
    row = save_review_item(
        session, judge_verdict_id=verdict.id, estimate_id=estimate.id, dimension="graph_completion",
        fact="check this", evidence=evidence or {"lines": []}, line_index=0,
    )
    row.status = status
    session.flush()
    return row


def _get(session, path):
    app.dependency_overrides[get_session] = lambda: session
    try:
        return TestClient(app).get(path)
    finally:
        app.dependency_overrides.clear()


def _summary(session, request):
    rows = _get(session, "/v1/quotes").json()
    return next(row for row in rows if row["quote_request_id"] == str(request.id))


def test_list_returns_a_request_with_no_estimate_and_null_verdict_fields(db_session):
    request = _request(db_session)

    row = _summary(db_session, request)

    assert row["estimate_count"] == 0
    assert row["latest_estimate_status"] is None
    assert row["latest_trusted"] is None
    assert row["open_review_items"] == 0
    assert row["is_duplicate"] is False


def test_list_reports_the_latest_estimate_and_its_latest_verdict(db_session):
    seed_world(db_session)
    request = _request(db_session)
    first = _estimate(db_session, request, 1)
    _item(db_session, first, _verdict(db_session, first, 2, trusted=False))
    second = _estimate(db_session, request, 10)
    _verdict(db_session, second, 11, trusted=True)

    row = _summary(db_session, request)

    assert row["estimate_count"] == 2
    assert row["latest_estimate_status"] == "ready"
    assert row["latest_trusted"] is True
    assert row["open_review_items"] == 1


def test_list_handles_an_estimate_that_was_never_judged(db_session):
    request = _request(db_session)
    _estimate(db_session, request, 1)

    row = _summary(db_session, request)

    assert row["latest_estimate_status"] == "ready"
    assert row["latest_trusted"] is None


def test_list_flags_a_request_with_a_duplicate_verdict(db_session):
    original = _request(db_session, 0)
    copy = _request(db_session, 5)
    save_verdict(
        db_session, quote_request_id=copy.id, candidate_quote_request_id=original.id, verdict="DUPLICATE_OF",
        content_jaccard=1.0, style_jaccard=0.9, signals_fired=["identical_sku_set"],
    )

    assert _summary(db_session, copy)["is_duplicate"] is True
    assert _summary(db_session, original)["is_duplicate"] is False


def test_list_uses_a_fixed_number_of_queries(db_session):
    def statements_for_list():
        count = []
        connection = db_session.get_bind()
        listener = lambda *args: count.append(1)
        event.listen(connection, "before_cursor_execute", listener)
        try:
            _get(db_session, "/v1/quotes")
        finally:
            event.remove(connection, "before_cursor_execute", listener)
        return len(count)

    _estimate(db_session, _request(db_session, 0), 0)
    baseline = statements_for_list()
    for minutes in range(1, 6):
        request = _request(db_session, minutes)
        _estimate(db_session, request, minutes)

    assert statements_for_list() == baseline


def test_detail_returns_404_for_an_unknown_request(db_session):
    response = _get(db_session, f"/v1/quotes/{uuid.uuid4()}")

    assert response.status_code == 404


def test_detail_orders_estimates_newest_first_with_their_own_verdicts_and_items(db_session):
    seed_world(db_session)
    request = _request(db_session, case_id="sc-detail")
    first = _estimate(db_session, request, 1)
    first_item = _item(db_session, first, _verdict(db_session, first, 2, trusted=False))
    second = _estimate(db_session, request, 10)
    _verdict(db_session, second, 11, trusted=True)

    body = _get(db_session, f"/v1/quotes/{request.id}").json()

    assert body["case_id"] == "sc-detail"
    assert [e["estimate_id"] for e in body["estimates"]] == [str(second.id), str(first.id)]
    assert body["estimates"][0]["judge_verdict"]["trusted"] is True
    assert body["estimates"][0]["review_items"] == []
    assert body["estimates"][1]["judge_verdict"]["trusted"] is False
    assert [i["id"] for i in body["estimates"][1]["review_items"]] == [str(first_item.id)]
    assert body["estimates"][0]["totals"]["net_total"] == 200.0


def test_detail_handles_a_needs_review_estimate_with_no_draft(db_session):
    request = _request(db_session)
    _estimate(db_session, request, 1, status="needs_review")

    estimate = _get(db_session, f"/v1/quotes/{request.id}").json()["estimates"][0]

    assert estimate["draft"] is None
    assert estimate["totals"] is None
    assert estimate["reason"] == "blocked"
    assert estimate["judge_verdict"] is None


def test_detail_includes_sku_info_for_draft_lines_and_evidence(db_session):
    seed_world(db_session)
    request = _request(db_session)
    estimate = _estimate(db_session, request, 1)
    verdict = _verdict(db_session, estimate, 2, trusted=False)
    _item(db_session, estimate, verdict, evidence={"lines": [
        {"line_index": 0, "sku_id": "SKU-E-A1", "live_sku_id": "SKU-E-A1", "required_part_ids": ["SKU-E-B1"],
         "missing_required_part_ids": ["SKU-E-B1"]},
    ]})

    skus = _get(db_session, f"/v1/quotes/{request.id}").json()["skus"]

    assert skus["SKU-E-A1"] == {"name": "Zorpwidget Alpha 9000", "category": "Cat-E-A", "discontinued": False}
    assert skus["SKU-E-B1"]["category"] == "Cat-E-B"


def test_detail_includes_dedupe_verdicts(db_session):
    original = _request(db_session, 0)
    copy = _request(db_session, 5)
    save_verdict(
        db_session, quote_request_id=copy.id, candidate_quote_request_id=original.id, verdict="DUPLICATE_OF",
        content_jaccard=1.0, style_jaccard=0.9, signals_fired=["identical_sku_set"],
    )

    verdicts = _get(db_session, f"/v1/quotes/{copy.id}").json()["dedupe_verdicts"]

    assert verdicts[0]["verdict"] == "DUPLICATE_OF"
    assert verdicts[0]["candidate_quote_request_id"] == str(original.id)
    assert verdicts[0]["signals_fired"] == ["identical_sku_set"]
