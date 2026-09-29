import uuid

import pytest

from app.estimate.repository import save_estimate_draft
from app.intake.repository import save_quote_request
from app.judge.service import EstimateNotFound, run_judge
from tests.app.estimate.seed import AS_OF, seed_world
from tests.app.judge.fakes import ScriptedJudgeClient
from tests.graph_support import UnusedGraph


def _quote_request(session):
    return save_quote_request(
        session, raw_email_text="need parts", parsed_json={"resolved_line_items": []},
        content_fingerprint={}, style_fingerprint={}, customer_id="CUST-E1", contract_id="CTR-E1",
    )


def _ready_draft(sku_id="SKU-E-A1", discount_pct=0.0):
    return {"customer_id": "CUST-E1", "contract_id": "CTR-E1", "lines": [
        {"sku_id": sku_id, "quantity": 1, "unit_price": 100.0, "price_source": "list", "discount_pct": discount_pct},
    ]}


def test_needs_review_draft_short_circuits_without_calling_the_client(db_session):
    seed_world(db_session)
    request = _quote_request(db_session)
    row = save_estimate_draft(
        db_session, quote_request_id=request.id, status="needs_review", draft=None, violations=[],
        iterations=3, reason="guardrail violations persisted after 3 retries",
    )
    client = ScriptedJudgeClient([])

    run = run_judge(db_session, UnusedGraph(), AS_OF, row.id, client)

    assert client.calls == 0
    assert run.verdict.trusted is False
    assert run.verdict.flagged_dimension == "guardrail"
    assert run.review_item.fact == "guardrail violations persisted after 3 retries"


def test_ready_draft_above_threshold_creates_no_review_item(db_session, make_reader):
    seed_world(db_session)
    request = _quote_request(db_session)
    row = save_estimate_draft(
        db_session, quote_request_id=request.id, status="ready", draft=_ready_draft(),
        violations=[], iterations=1, reason=None,
    )
    client = ScriptedJudgeClient([
        {"name": "price_provenance", "score": 0.95, "rationale": "list price, fully supported"},
        {"name": "contract_discount", "score": 1.0, "rationale": "no discount claimed"},
        {"name": "graph_completion", "score": 0.9, "rationale": "live SKU, no required parts"},
    ])

    run = run_judge(db_session, make_reader(), AS_OF, row.id, client)

    assert client.calls == 1
    assert run.verdict.trusted is True
    assert run.review_item is None


def test_ready_draft_below_threshold_creates_a_review_item_naming_one_dimension(db_session, make_reader):
    seed_world(db_session)
    request = _quote_request(db_session)
    row = save_estimate_draft(
        db_session, quote_request_id=request.id, status="ready", draft=_ready_draft(),
        violations=[], iterations=1, reason=None,
    )
    client = ScriptedJudgeClient([
        {"name": "price_provenance", "score": 0.95, "rationale": "list price, fully supported"},
        {"name": "contract_discount", "score": 1.0, "rationale": "no discount claimed"},
        {"name": "graph_completion", "score": 0.3, "rationale": "evidence for this line is thin"},
    ])

    run = run_judge(db_session, make_reader(), AS_OF, row.id, client)

    assert run.verdict.trusted is False
    assert run.verdict.flagged_dimension == "graph_completion"
    assert run.review_item.dimension == "graph_completion"
    assert run.review_item.line_index == 0


def test_flagged_dimension_spanning_two_lines_leaves_line_index_none(db_session, make_reader):
    seed_world(db_session)
    request = _quote_request(db_session)
    draft = {"customer_id": "CUST-E1", "contract_id": "CTR-E1", "lines": [
        {"sku_id": "SKU-E-A1", "quantity": 1, "unit_price": 100.0, "price_source": "list", "discount_pct": 0.0},
        {"sku_id": "SKU-E-B1", "quantity": 1, "unit_price": 50.0, "price_source": "list", "discount_pct": 0.0},
    ]}
    row = save_estimate_draft(
        db_session, quote_request_id=request.id, status="ready", draft=draft, violations=[], iterations=1, reason=None,
    )
    client = ScriptedJudgeClient([
        {"name": "price_provenance", "score": 0.95, "rationale": "list price"},
        {"name": "contract_discount", "score": 1.0, "rationale": "no discount"},
        {"name": "graph_completion", "score": 0.2, "rationale": "SKU-E-B1 is missing its required part"},
    ])

    run = run_judge(db_session, make_reader(), AS_OF, row.id, client)

    assert run.review_item.line_index is None


def test_unknown_estimate_raises(db_session):
    with pytest.raises(EstimateNotFound):
        run_judge(db_session, UnusedGraph(), AS_OF, uuid.uuid4(), ScriptedJudgeClient([]))
