import uuid

import pytest
from sqlalchemy import select, text

from app.estimate.constant import MAX_AGENT_STEPS
from app.estimate.models import EstimateDraftRow
from app.estimate.repository import get_estimate_draft
from app.estimate.service import run_estimate
from app.intake.repository import save_quote_request
from core.llm.openai_agent_client import AgentError
from tests.app.estimate.fakes import ScriptedLLM, submit_turn, text_turn
from tests.app.estimate.seed import AS_OF, seed_world


def _quote_request(session):
    return save_quote_request(
        session, raw_email_text="need 3 Zorpwidget Alpha 9000",
        parsed_json={"resolved_line_items": [{"sku_name_as_written": "Zorpwidget Alpha 9000",
                                              "sku_id": "SKU-E-A1", "quantity": "3"}]},
        content_fingerprint={"sku_ids": ["SKU-E-A1"]}, style_fingerprint={"tokens": []},
        customer_id="CUST-E1", contract_id="CTR-E1",
    )


def _good_draft():
    return {
        "customer_id": "CUST-E1", "contract_id": "CTR-E1",
        "lines": [{"sku_id": "SKU-E-A1", "quantity": 3, "unit_price": 100.0, "price_source": "list",
                   "discount_pct": 10.0}],
    }


def test_run_estimate_computes_totals_and_persists_the_draft(db_session):
    seed_world(db_session)
    request = _quote_request(db_session)
    llm = ScriptedLLM([submit_turn(_good_draft())])

    run = run_estimate(db_session, request.id, AS_OF, llm)

    assert run.result.status == "ready"
    assert run.result.totals.list_total == 300.0
    assert run.result.totals.discount_total == 30.0
    assert run.result.totals.net_total == 270.0
    assert run.result.iterations == 1
    stored = get_estimate_draft(db_session, run.row.id)
    assert stored.status == "ready"
    assert stored.quote_request_id == request.id
    assert stored.draft["lines"][0]["sku_id"] == "SKU-E-A1"
    assert stored.violations == []


def test_run_estimate_persists_needs_review_with_violations(db_session):
    seed_world(db_session)
    request = _quote_request(db_session)
    bad = _good_draft()
    bad["lines"] = [{"sku_id": "SKU-E-B1", "quantity": 1, "unit_price": 50.0, "price_source": "list",
                     "discount_pct": 10.0}]
    llm = ScriptedLLM([submit_turn(bad, call_id=f"c{i}") for i in range(4)])

    run = run_estimate(db_session, request.id, AS_OF, llm)

    assert run.result.status == "needs_review"
    assert run.result.iterations == 4
    assert run.result.violations[0].guardrail == "contract_discount"
    stored = get_estimate_draft(db_session, run.row.id)
    assert stored.violations[0]["guardrail"] == "contract_discount"
    assert stored.reason is not None


def test_run_estimate_persists_needs_review_when_agent_never_submits(db_session):
    seed_world(db_session)
    request = _quote_request(db_session)
    llm = ScriptedLLM([text_turn() for _ in range(MAX_AGENT_STEPS)])

    run = run_estimate(db_session, request.id, AS_OF, llm)

    assert run.result.status == "needs_review"
    assert run.result.draft is None
    assert run.result.totals is None
    assert run.result.iterations == 0
    assert run.result.reason is not None
    stored = get_estimate_draft(db_session, run.row.id)
    assert stored.draft is None
    draft_is_sql_null = db_session.execute(
        text("select draft is null from estimate_drafts where id = :id"), {"id": run.row.id}
    ).scalar()
    assert draft_is_sql_null is True


def test_run_estimate_persists_needs_review_for_a_flagged_draft(db_session):
    seed_world(db_session)
    request = _quote_request(db_session)
    flagged = _good_draft()
    flagged["flags"] = ["replacement SKU is out of stock"]
    llm = ScriptedLLM([submit_turn(flagged)])

    run = run_estimate(db_session, request.id, AS_OF, llm)

    assert run.result.status == "needs_review"
    assert run.result.violations == []
    stored = get_estimate_draft(db_session, run.row.id)
    assert stored.violations == []
    assert stored.reason is not None
    assert stored.draft["flags"] == ["replacement SKU is out of stock"]


def test_run_estimate_rejects_unknown_quote_request(db_session):
    with pytest.raises(ValueError):
        run_estimate(db_session, uuid.uuid4(), AS_OF, ScriptedLLM([]))


def test_run_estimate_propagates_agent_error_and_saves_nothing(db_session):
    seed_world(db_session)
    request = _quote_request(db_session)

    class FailingLLM:
        def next_turn(self, messages, tools):
            raise AgentError("boom")

    with pytest.raises(AgentError):
        run_estimate(db_session, request.id, AS_OF, FailingLLM())

    saved = db_session.scalars(
        select(EstimateDraftRow).where(EstimateDraftRow.quote_request_id == request.id)
    ).all()
    assert saved == []
