from fastapi.testclient import TestClient

from app.dedupe.repository import save_verdict
from app.estimate.repository import save_estimate_draft
from app.intake.repository import save_quote_request
from app.judge.repository import save_judge_verdict, save_review_item
from core.db.session import get_session
from main import app


def _counts(session):
    app.dependency_overrides[get_session] = lambda: session
    try:
        return TestClient(app).get("/v1/metrics").json()["counts"]
    finally:
        app.dependency_overrides.clear()


def _request(session):
    return save_quote_request(
        session, raw_email_text="need parts", parsed_json={"resolved_line_items": []},
        content_fingerprint={}, style_fingerprint={}, customer_id=None,
    )


def _estimate(session, request):
    return save_estimate_draft(
        session, quote_request_id=request.id, status="ready", draft={"lines": []}, violations=[],
        iterations=1, reason=None,
    )


def _verdict(session, estimate, trusted):
    return save_judge_verdict(
        session, estimate_id=estimate.id, model="test-judge", dimensions=[], overall_confidence=0.5,
        flagged_dimension="graph_completion", trusted=trusted,
    )


def test_metrics_counts_grow_by_exactly_the_rows_added(db_session):
    before = _counts(db_session)
    request = _request(db_session)
    estimate = _estimate(db_session, request)
    trusted = _verdict(db_session, estimate, True)
    untrusted = _verdict(db_session, estimate, False)
    approved = save_review_item(
        db_session, judge_verdict_id=untrusted.id, estimate_id=estimate.id, dimension="graph_completion",
        fact="x", evidence={}, line_index=None,
    )
    corrected = save_review_item(
        db_session, judge_verdict_id=untrusted.id, estimate_id=estimate.id, dimension="graph_completion",
        fact="y", evidence={}, line_index=None,
    )
    save_review_item(
        db_session, judge_verdict_id=untrusted.id, estimate_id=estimate.id, dimension="graph_completion",
        fact="still open", evidence={}, line_index=None,
    )
    approved.status, approved.outcome = "approved", "approved"
    corrected.status, corrected.outcome = "corrected", "corrected"
    other = _request(db_session)
    save_verdict(
        db_session, quote_request_id=other.id, candidate_quote_request_id=request.id, verdict="DUPLICATE_OF",
        content_jaccard=1.0, style_jaccard=1.0, signals_fired=[],
    )
    save_verdict(
        db_session, quote_request_id=request.id, candidate_quote_request_id=other.id, verdict="DISTINCT",
        content_jaccard=0.0, style_jaccard=0.1, signals_fired=[],
    )
    db_session.flush()
    assert trusted.trusted is True

    after = _counts(db_session)

    assert after["verdicts_total"] - before["verdicts_total"] == 2
    assert after["verdicts_trusted"] - before["verdicts_trusted"] == 1
    assert after["review_items_resolved"] - before["review_items_resolved"] == 2
    assert after["review_items_corrected"] - before["review_items_corrected"] == 1
    assert after["requests_compared"] - before["requests_compared"] == 2
    assert after["requests_duplicate"] - before["requests_duplicate"] == 1


def test_flags_by_dimension_counts_review_items_per_dimension(db_session):
    before = _counts(db_session)["flags_by_dimension"].get("graph_completion", 0)
    request = _request(db_session)
    estimate = _estimate(db_session, request)
    verdict = _verdict(db_session, estimate, False)
    save_review_item(
        db_session, judge_verdict_id=verdict.id, estimate_id=estimate.id, dimension="graph_completion",
        fact="x", evidence={}, line_index=None,
    )
    db_session.flush()

    assert _counts(db_session)["flags_by_dimension"]["graph_completion"] == before + 1
