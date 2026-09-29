import uuid

import pytest
from sqlalchemy import select, text

from app.estimate.constant import MAX_AGENT_STEPS
from app.estimate.models import EstimateDraftRow
from app.estimate.repository import get_estimate_draft
from app.estimate.service import QuoteRequestNotFound, run_estimate
from app.intake.repository import save_quote_request
from core.llm.openai_agent_client import AgentError
from tests.app.estimate.fakes import ScriptedLLM, submit_turn, text_turn
from tests.app.estimate.seed import AS_OF, seed_chain_world, seed_world
from tests.graph_support import FakeEmbedder, UnusedGraph


def _run(db_session, make_reader, request_id, llm):
    return run_estimate(db_session, request_id, AS_OF, llm, make_reader(), FakeEmbedder())


def _quote_request(session, customer_id="CUST-E1", contract_id="CTR-E1", sku_id="SKU-E-A1"):
    return save_quote_request(
        session, raw_email_text="need 3 Zorpwidget Alpha 9000",
        parsed_json={"resolved_line_items": [{"sku_name_as_written": "Zorpwidget Alpha 9000",
                                              "sku_id": sku_id, "quantity": "3"}]},
        content_fingerprint={"sku_ids": [sku_id]}, style_fingerprint={"tokens": []},
        customer_id=customer_id, contract_id=contract_id,
    )


def _good_draft():
    return {
        "customer_id": "CUST-E1", "contract_id": "CTR-E1",
        "lines": [{"sku_id": "SKU-E-A1", "quantity": 3, "unit_price": 100.0, "price_source": "list",
                   "discount_pct": 10.0}],
    }


def test_run_estimate_computes_totals_and_persists_the_draft(db_session, make_reader):
    seed_world(db_session)
    request = _quote_request(db_session)
    llm = ScriptedLLM([submit_turn(_good_draft())])

    run = _run(db_session, make_reader, request.id, llm)

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


def test_run_estimate_persists_needs_review_with_violations(db_session, make_reader):
    seed_world(db_session)
    request = _quote_request(db_session)
    bad = _good_draft()
    bad["lines"] = [{"sku_id": "SKU-E-B1", "quantity": 1, "unit_price": 50.0, "price_source": "list",
                     "discount_pct": 10.0}]
    llm = ScriptedLLM([submit_turn(bad, call_id=f"c{i}") for i in range(4)])

    run = _run(db_session, make_reader, request.id, llm)

    assert run.result.status == "needs_review"
    assert run.result.iterations == 4
    assert run.result.violations[0].guardrail == "contract_discount"
    stored = get_estimate_draft(db_session, run.row.id)
    assert stored.violations[0]["guardrail"] == "contract_discount"
    assert stored.reason is not None


def test_run_estimate_persists_needs_review_when_agent_never_submits(db_session, make_reader):
    seed_world(db_session)
    request = _quote_request(db_session)
    llm = ScriptedLLM([text_turn() for _ in range(MAX_AGENT_STEPS)])

    run = _run(db_session, make_reader, request.id, llm)

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


def test_run_estimate_persists_needs_review_for_a_flagged_draft(db_session, make_reader):
    seed_world(db_session)
    request = _quote_request(db_session)
    flagged = _good_draft()
    flagged["flags"] = ["replacement SKU is out of stock"]
    llm = ScriptedLLM([submit_turn(flagged)])

    run = _run(db_session, make_reader, request.id, llm)

    assert run.result.status == "needs_review"
    assert run.result.violations == []
    stored = get_estimate_draft(db_session, run.row.id)
    assert stored.violations == []
    assert stored.reason is not None
    assert stored.draft["flags"] == ["replacement SKU is out of stock"]


def test_draft_for_another_customers_contract_never_ends_ready(db_session, make_reader):
    seed_world(db_session)
    request = _quote_request(db_session, customer_id="CUST-E2", contract_id=None)
    llm = ScriptedLLM([submit_turn(_good_draft(), call_id=f"c{i}") for i in range(4)])

    run = _run(db_session, make_reader, request.id, llm)

    assert run.result.status == "needs_review"
    assert run.result.totals.discount_total == 30.0
    assert [v.guardrail for v in run.result.violations] == ["customer_identity"]
    assert "does not match" in run.result.violations[0].message
    assert get_estimate_draft(db_session, run.row.id).status == "needs_review"


def test_draft_for_a_nonexistent_customer_never_ends_ready(db_session, make_reader):
    seed_world(db_session)
    request = _quote_request(db_session)
    invented = {**_good_draft(), "customer_id": "CUST-NOPE", "contract_id": None}
    invented["lines"] = [{**invented["lines"][0], "discount_pct": 0.0}]
    llm = ScriptedLLM([submit_turn(invented, call_id=f"c{i}") for i in range(4)])

    run = _run(db_session, make_reader, request.id, llm)

    assert run.result.status == "needs_review"
    assert "unknown customer" in run.result.violations[0].message


def test_discount_is_never_ready_when_the_request_has_no_resolved_customer(db_session, make_reader):
    seed_world(db_session)
    request = _quote_request(db_session, customer_id=None, contract_id=None)
    llm = ScriptedLLM([submit_turn(_good_draft(), call_id=f"c{i}") for i in range(4)])

    run = _run(db_session, make_reader, request.id, llm)

    assert run.result.status == "needs_review"
    assert any(v.guardrail == "contract_discount" and "did not resolve" in v.message for v in run.result.violations)


def test_run_estimate_rejects_unknown_quote_request(db_session):
    with pytest.raises(QuoteRequestNotFound):
        run_estimate(db_session, uuid.uuid4(), AS_OF, ScriptedLLM([]), UnusedGraph(), FakeEmbedder())


def test_run_estimate_propagates_agent_error_and_saves_nothing(db_session, make_reader):
    seed_world(db_session)
    request = _quote_request(db_session)

    class FailingLLM:
        def next_turn(self, messages, tools):
            raise AgentError("boom")

    with pytest.raises(AgentError):
        _run(db_session, make_reader, request.id, FailingLLM())

    saved = db_session.scalars(
        select(EstimateDraftRow).where(EstimateDraftRow.quote_request_id == request.id)
    ).all()
    assert saved == []


def test_the_guardrail_is_anchored_on_the_skus_intake_resolved(db_session, make_reader):
    seed_world(db_session)
    seed_chain_world(db_session)
    request = _quote_request(db_session, sku_id="SKU-E-OLD")
    swapped = _good_draft()
    dropped = {**_good_draft(), "lines": [
        {"sku_id": "SKU-E-P1", "quantity": 1, "unit_price": 10.0, "price_source": "list", "discount_pct": 0.0}]}

    ready = _run(db_session, make_reader, request.id, ScriptedLLM([submit_turn(swapped)]))
    blocked = _run(db_session, make_reader, request.id, ScriptedLLM([submit_turn(dropped, call_id=f"c{i}") for i in range(4)]))

    assert ready.result.status == "ready"
    assert blocked.result.status == "needs_review"
    assert any("the request asks for SKU-E-OLD" in v.message for v in blocked.result.violations)
    stored = get_estimate_draft(db_session, blocked.row.id)
    assert any("the request asks for SKU-E-OLD" in v["message"] for v in stored.violations)


def test_a_stale_graph_is_persisted_as_needs_review_without_a_draft(db_session, graph_client, graph_ns):
    from app.graph.reader import GraphReader

    seed_world(db_session)
    request = _quote_request(db_session)

    run = run_estimate(db_session, request.id, AS_OF, ScriptedLLM([]), GraphReader(graph_client, graph_ns), FakeEmbedder())

    assert run.result.status == "needs_review" and "out of date" in run.result.reason
    assert run.result.draft is None and run.result.iterations == 0
    assert get_estimate_draft(db_session, run.row.id).draft is None
