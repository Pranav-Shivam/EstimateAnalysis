import uuid

import pytest
from procrastinate import testing

from app.consolidation.tasks import app as consolidation_app
from app.estimate.repository import save_estimate_draft
from app.intake.repository import save_quote_request
from app.judge.repository import save_judge_verdict, save_review_item
from app.judge.schemas import InvalidCorrection
from app.judge.service import (
    EstimateNotFound, ReviewItemAlreadyResolved, ReviewItemNotFound, ReviewItemNotResolvable, resolve_review_item,
    run_judge,
)
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


PRICE_EVIDENCE = {"lines": [{"line_index": 0, "sku_id": "SKU-E-GAP", "price_source": "predicted"}]}


def _open_review_item(session, dimension="price_provenance", evidence=None, fact="thin evidence"):
    request = _quote_request(session)
    estimate = save_estimate_draft(
        session, quote_request_id=request.id, status="ready", draft=_ready_draft(), violations=[], iterations=1,
        reason=None,
    )
    verdict = save_judge_verdict(
        session, estimate_id=estimate.id, model="m", dimensions=[], overall_confidence=0.1,
        flagged_dimension=dimension, trusted=False,
    )
    return save_review_item(
        session, judge_verdict_id=verdict.id, estimate_id=verdict.estimate_id, dimension=dimension, fact=fact,
        evidence=evidence or PRICE_EVIDENCE, line_index=None,
    )


def test_resolve_review_item_returns_404_equivalent_for_an_unknown_id(db_session):
    with pytest.raises(ReviewItemNotFound):
        resolve_review_item(db_session, uuid.uuid4(), "approved", None)


def test_approving_records_the_outcome_and_a_trust_eval_case_with_no_task_enqueued(db_session):
    seed_world(db_session)
    row = _open_review_item(db_session)
    in_memory = testing.InMemoryConnector()
    with consolidation_app.replace_connector(in_memory):
        result = resolve_review_item(db_session, row.id, "approved", None)

    assert result.row.status == "approved"
    assert result.row.outcome == "approved"
    assert result.eval_case.label == "trust"
    assert result.consolidation_enqueued is False
    assert in_memory.jobs == {}


def test_correcting_records_the_outcome_and_an_escalate_eval_case_and_enqueues_consolidation(db_session):
    seed_world(db_session)
    row = _open_review_item(db_session)
    correction = {"sku_id": "SKU-E-GAP", "corrected_unit_price": 42.5}
    in_memory = testing.InMemoryConnector()
    with consolidation_app.replace_connector(in_memory):
        result = resolve_review_item(db_session, row.id, "corrected", correction)

    assert result.row.status == "corrected"
    assert result.row.correction == correction
    assert result.eval_case.label == "escalate"
    assert result.consolidation_enqueued is True
    assert len(in_memory.jobs) == 1
    assert str(row.id) in str(list(in_memory.jobs.values())[0])


def test_resolving_an_already_resolved_item_is_rejected(db_session):
    seed_world(db_session)
    row = _open_review_item(db_session)
    in_memory = testing.InMemoryConnector()
    with consolidation_app.replace_connector(in_memory):
        resolve_review_item(db_session, row.id, "approved", None)
        with pytest.raises(ReviewItemAlreadyResolved):
            resolve_review_item(db_session, row.id, "approved", None)


def test_correcting_with_a_sku_the_review_item_never_named_is_rejected(db_session):
    seed_world(db_session)
    row = _open_review_item(db_session)
    with pytest.raises(InvalidCorrection):
        resolve_review_item(db_session, row.id, "corrected", {"sku_id": "SKU-E-A1", "corrected_unit_price": 1.0})


def test_a_guardrail_fast_path_review_item_is_not_resolvable(db_session):
    seed_world(db_session)
    row = _open_review_item(db_session, dimension="guardrail", evidence={"violations": ["blocked"]}, fact="blocked")
    with pytest.raises(ReviewItemNotResolvable):
        resolve_review_item(db_session, row.id, "approved", None)
