import uuid

from app.estimate.repository import save_estimate_draft
from app.intake.repository import save_quote_request
from app.judge.models import EvalCaseRow
from app.judge.repository import get_judge_verdict, list_open_review_items, save_judge_verdict, save_review_item
from tests.app.estimate.seed import seed_world


def _estimate_draft_id(session) -> uuid.UUID:
    seed_world(session)
    request = save_quote_request(
        session, raw_email_text="need parts", parsed_json={"resolved_line_items": []},
        content_fingerprint={}, style_fingerprint={}, customer_id="CUST-E1", contract_id="CTR-E1",
    )
    row = save_estimate_draft(
        session, quote_request_id=request.id, status="ready", draft={"customer_id": "CUST-E1", "lines": []},
        violations=[], iterations=1, reason=None,
    )
    return row.id


def test_save_and_get_judge_verdict_round_trips(db_session):
    estimate_id = _estimate_draft_id(db_session)

    row = save_judge_verdict(
        db_session, estimate_id=estimate_id, model="claude-haiku-4-5-20251001",
        dimensions=[{"name": "price_provenance", "score": 0.9, "rationale": "fine", "evidence": []}],
        overall_confidence=0.9, flagged_dimension="price_provenance", trusted=True,
    )

    fetched = get_judge_verdict(db_session, row.id)
    assert fetched.estimate_id == estimate_id
    assert fetched.trusted is True
    assert fetched.dimensions[0]["name"] == "price_provenance"


def test_review_item_appears_in_open_list(db_session):
    estimate_id = _estimate_draft_id(db_session)
    verdict = save_judge_verdict(
        db_session, estimate_id=estimate_id, model="claude-haiku-4-5-20251001",
        dimensions=[], overall_confidence=0.4, flagged_dimension="graph_completion", trusted=False,
    )

    item = save_review_item(
        db_session, judge_verdict_id=verdict.id, estimate_id=estimate_id, dimension="graph_completion",
        fact="missing required part", evidence={"missing": ["SKU-X"]}, line_index=0,
    )

    open_ids = [row.id for row in list_open_review_items(db_session)]
    assert item.id in open_ids


def test_review_item_row_has_resolution_columns(db_session):
    estimate_id = _estimate_draft_id(db_session)
    verdict = save_judge_verdict(
        db_session, estimate_id=estimate_id, model="m", dimensions=[], overall_confidence=0.1,
        flagged_dimension="price_provenance", trusted=False,
    )
    row = save_review_item(
        db_session, judge_verdict_id=verdict.id, estimate_id=verdict.estimate_id, dimension="price_provenance",
        fact="thin evidence", evidence={"lines": []}, line_index=None,
    )

    assert row.outcome is None
    assert row.correction is None
    assert row.resolved_at is None


def test_eval_case_row_round_trips(db_session):
    row = EvalCaseRow(
        id=uuid.uuid4(), source_review_item_id=None, case_id="rc-0001", label="escalate",
        estimate_status="ready", evidence=[{"line_index": 0, "sku_id": "SKU-X"}],
    )
    db_session.add(row)
    db_session.flush()

    fetched = db_session.get(EvalCaseRow, row.id)
    assert fetched.case_id == "rc-0001"
    assert fetched.label == "escalate"
    assert fetched.evidence == [{"line_index": 0, "sku_id": "SKU-X"}]
