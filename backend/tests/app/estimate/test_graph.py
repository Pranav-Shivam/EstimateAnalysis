import threading

import pytest

from app.estimate.constant import MAX_AGENT_STEPS
from app.estimate.graph import run_agent
from app.graph import service as graph_service
from app.reference_data.models import Sku
from app.reference_data.repository import upsert_requirement, upsert_sku
from tests.app.estimate.fakes import ScriptedLLM, call_turn, submit_turn, text_turn
from tests.app.estimate.seed import seed_chain_world, seed_world
from tests.graph_support import FailingGraphReader, TogglableReader, make_ctx


def _line(sku_id="SKU-E-A1", quantity=1, unit_price=100.0, price_source="list", discount_pct=0.0):
    return {"sku_id": sku_id, "quantity": quantity, "unit_price": unit_price, "price_source": price_source,
            "discount_pct": discount_pct}


def _draft(lines, **extra):
    return {"customer_id": "CUST-E1", "contract_id": "CTR-E1", "lines": lines, **extra}


def _bad_discount_draft():
    return _draft([_line(sku_id="SKU-E-B1", unit_price=50.0, discount_pct=10.0)])


@pytest.fixture
def run(db_session, make_reader):
    def _run(turns, *, sku_ids=("SKU-E-A1",), wrap_reader=None):
        seed_world(db_session)
        seed_chain_world(db_session)
        reader = make_reader()
        if wrap_reader is not None:
            reader = wrap_reader(reader)
        llm = ScriptedLLM(turns)
        ctx = make_ctx(db_session, reader, customer_id="CUST-E1", sku_ids=sku_ids)
        state = run_agent(llm, ctx, "please quote 1 SKU-E-A1")
        return state, llm

    return _run


def test_clean_draft_passes_on_first_submission(run):
    state, llm = run([submit_turn(_draft([_line(discount_pct=10.0)]))])

    assert state["status"] == "ready"
    assert state["violations"] == []
    assert state["submissions"] == 1
    assert state["last_draft"].lines[0].sku_id == "SKU-E-A1"
    assert len(llm.calls) == 1


def test_tool_results_are_fed_back_to_the_agent(run):
    def second(messages):
        assert messages[-1]["role"] == "tool"
        assert messages[-1]["tool_call_id"] == "call-1"
        assert "SKU-E-A1" in messages[-1]["content"] and "100.0" in messages[-1]["content"]
        return submit_turn(_draft([_line()]))

    state, _ = run([call_turn("search_price_book", {"query": "SKU-E-A1"}), second])

    assert state["status"] == "ready"


def test_several_tool_calls_in_one_turn_are_all_answered(run):
    from core.llm.openai_agent_client import AgentTurn, ToolCall
    both = AgentTurn(content=None, tool_calls=[
        ToolCall(id="c1", name="check_stock", arguments={"sku_id": "SKU-E-A1"}),
        ToolCall(id="c2", name="check_stock", arguments={"sku_id": "SKU-E-OLD"}),
    ])

    def second(messages):
        tool_messages = [m for m in messages if m["role"] == "tool"]
        assert [m["tool_call_id"] for m in tool_messages] == ["c1", "c2"]
        return submit_turn(_draft([_line()]))

    state, _ = run([both, second])

    assert state["status"] == "ready"


def test_planted_bad_discount_is_blocked_then_corrected(run):
    def corrected(messages):
        assert messages[-1]["role"] == "user"
        assert "not covered" in messages[-1]["content"]
        return submit_turn(_draft([_line(sku_id="SKU-E-B1", unit_price=50.0), _line()]), call_id="call-2")

    state, _ = run([submit_turn(_bad_discount_draft()), corrected])

    assert state["status"] == "ready"
    assert state["submissions"] == 2
    assert state["violations"] == []


def test_bad_discount_that_persists_ends_needs_review_after_four_submissions(run):
    turns = [submit_turn(_bad_discount_draft(), call_id=f"call-{i}") for i in range(4)]

    state, llm = run(turns)

    assert state["status"] == "needs_review"
    assert state["submissions"] == 4
    assert state["violations"][0].guardrail == "contract_discount"
    assert "guardrail" in state["reason"]
    assert len(llm.calls) == 4


def test_flagged_draft_ends_needs_review_even_when_guardrails_pass(run):
    draft = _draft([_line()], flags=["replacement SKU is out of stock"])

    state, _ = run([submit_turn(draft)])

    assert state["status"] == "needs_review"
    assert state["violations"] == []
    assert state["last_draft"].flags == ["replacement SKU is out of stock"]


def test_agent_that_never_submits_stops_at_the_step_cap(run):
    state, llm = run([text_turn()] * MAX_AGENT_STEPS)

    assert state["status"] == "needs_review"
    assert state["last_draft"] is None
    assert len(llm.calls) == MAX_AGENT_STEPS
    assert "steps" in state["reason"]


def test_text_only_turn_is_nudged_to_submit(run):
    def after_nudge(messages):
        assert "submit_draft" in messages[-1]["content"]
        return submit_turn(_draft([_line()]))

    state, _ = run([text_turn(), after_nudge])

    assert state["status"] == "ready"


def test_empty_completion_is_sent_back_with_string_content(run):
    from core.llm.openai_agent_client import AgentTurn

    def after_nudge(messages):
        assistant = [m for m in messages if m["role"] == "assistant"]
        assert assistant[0]["content"] == ""
        assert "tool_calls" not in assistant[0]
        assert "submit_draft" in messages[-1]["content"]
        return submit_turn(_draft([_line()]))

    state, _ = run([AgentTurn(content=None, tool_calls=[]), after_nudge])

    assert state["status"] == "ready"


def test_malformed_submit_draft_arguments_get_an_error_and_do_not_count(run):
    def second(messages):
        assert messages[-1]["role"] == "tool"
        assert "invalid" in messages[-1]["content"]
        return submit_turn(_draft([_line()]), call_id="call-2")

    state, _ = run([submit_turn({"lines": "oops"}), second])

    assert state["status"] == "ready"
    assert state["submissions"] == 1


def test_absurd_quantity_gets_an_invalid_draft_error_and_does_not_count(run):
    def second(messages):
        assert messages[-1]["role"] == "tool"
        assert "invalid draft" in messages[-1]["content"]
        return submit_turn(_draft([_line()]), call_id="call-2")

    state, llm = run([submit_turn(_draft([_line(quantity=10**20)])), second])

    assert state["status"] == "ready"
    assert state["submissions"] == 1
    assert len(llm.calls) == 2


def test_unknown_tool_gets_an_error_and_the_loop_continues(run):
    def second(messages):
        assert "unknown tool" in messages[-1]["content"]
        return submit_turn(_draft([_line()]), call_id="call-2")

    state, _ = run([call_turn("delete_everything", {}), second])

    assert state["status"] == "ready"


def test_wrong_typed_tool_argument_is_rejected_before_it_reaches_the_database(run):
    def second(messages):
        assert messages[-1]["role"] == "tool"
        assert "must be a string" in messages[-1]["content"]
        assert "query" in messages[-1]["content"]
        return submit_turn(_draft([_line()]), call_id="call-2")

    state, _ = run([call_turn("search_price_book", {"query": 123}), second])

    assert state["status"] == "ready"


def test_discontinued_swap_is_submitted_with_its_adjustment_and_ends_ready(run):
    def after_lookup(messages):
        assert messages[-1]["role"] == "tool"
        assert "SKU-E-A1" in messages[-1]["content"]
        adjustment = {"kind": "substituted", "sku_id": "SKU-E-A1", "detail": "replaced discontinued SKU-E-OLD"}
        return submit_turn(_draft([_line()], adjustments=[adjustment]), call_id="call-2")

    state, _ = run([call_turn("get_related_parts", {"sku_id": "SKU-E-OLD"}), after_lookup])

    assert state["status"] == "ready"
    assert state["last_draft"].lines[0].sku_id == "SKU-E-A1"
    assert [(a.kind, a.sku_id, a.detail) for a in state["last_draft"].adjustments] == [
        ("substituted", "SKU-E-A1", "replaced discontinued SKU-E-OLD"),
    ]


def test_missing_required_part_is_added_with_its_adjustment_and_ends_ready(run):
    def after_lookup(messages):
        assert "required_parts" in messages[-1]["content"] and "SKU-E-A1" in messages[-1]["content"]
        lines = [_line(sku_id="SKU-E-B1", unit_price=50.0), _line()]
        adjustment = {"kind": "added_required", "sku_id": "SKU-E-A1", "detail": "SKU-E-B1 requires SKU-E-A1"}
        return submit_turn(_draft(lines, adjustments=[adjustment]), call_id="call-2")

    state, _ = run([call_turn("get_related_parts", {"sku_id": "SKU-E-B1"}), after_lookup])

    assert state["status"] == "ready"
    assert [line.sku_id for line in state["last_draft"].lines] == ["SKU-E-B1", "SKU-E-A1"]
    assert state["last_draft"].adjustments[0].kind == "added_required"


def test_predicted_price_from_the_tool_is_accepted_when_used_verbatim(run):
    def after_prediction(messages):
        assert '"predicted_price": 20.0' in messages[-1]["content"]
        line = _line(sku_id="SKU-E-GAP", unit_price=20.0, price_source="predicted")
        return submit_turn(_draft([line]), call_id="call-2")

    state, _ = run([call_turn("predict_price", {"sku_id": "SKU-E-GAP"}), after_prediction], sku_ids=())

    assert state["status"] == "ready"
    assert state["last_draft"].lines[0].price_source == "predicted"


def test_made_up_predicted_price_is_blocked_and_ends_needs_review(run):
    made_up = _draft([_line(sku_id="SKU-E-GAP", unit_price=99.0, price_source="predicted")])
    turns = [submit_turn(made_up, call_id=f"call-{i}") for i in range(4)]

    state, _ = run(turns, sku_ids=())

    assert state["status"] == "needs_review"
    assert state["violations"][0].guardrail == "price_provenance"
    assert "predicted price" in state["violations"][0].message


def test_a_discontinued_sku_left_in_the_draft_is_blocked_then_swapped(run):
    def corrected(messages):
        feedback = messages[-1]["content"]
        assert "SKU-E-OLD is discontinued" in feedback and "SKU-E-A1" in feedback
        return submit_turn(_draft([_line()]), call_id="call-2")

    stale = _draft([_line(sku_id="SKU-E-OLD", unit_price=80.0)])

    state, _ = run([submit_turn(stale), corrected], sku_ids=("SKU-E-OLD",))

    assert state["status"] == "ready"
    assert state["submissions"] == 2
    assert [line.sku_id for line in state["last_draft"].lines] == ["SKU-E-A1"]


def test_a_missing_required_part_is_blocked_then_added(run):
    def corrected(messages):
        assert "SKU-E-B1 requires SKU-E-A1" in messages[-1]["content"]
        return submit_turn(_draft([_line(sku_id="SKU-E-B1", unit_price=50.0), _line()]), call_id="call-2")

    without_part = _draft([_line(sku_id="SKU-E-B1", unit_price=50.0)])

    state, _ = run([submit_turn(without_part), corrected], sku_ids=("SKU-E-B1",))

    assert state["status"] == "ready"
    assert [line.sku_id for line in state["last_draft"].lines] == ["SKU-E-B1", "SKU-E-A1"]


def test_an_unreplaceable_sku_ends_needs_review_at_once_without_retries(run):
    """(Review Focus) No live replacement exists, so a retry cannot help."""
    dead = _draft([_line(sku_id="SKU-E-DEAD", unit_price=5.0)])

    state, llm = run([submit_turn(dead)], sku_ids=("SKU-E-DEAD",))

    assert state["status"] == "needs_review"
    assert state["submissions"] == 1 and state["retries"] == 0
    assert len(llm.calls) == 1
    assert "SKU-E-DEAD" in state["reason"] and "no live replacement" in state["reason"]


def test_a_graph_that_is_down_ends_the_run_before_any_model_call(db_session):
    """(Review Focus) Fail closed, and do not spend model calls on a run that cannot be verified."""
    seed_world(db_session)
    llm = ScriptedLLM([])
    ctx = make_ctx(db_session, FailingGraphReader(), customer_id="CUST-E1", sku_ids=("SKU-E-A1",))

    state = run_agent(llm, ctx, "please quote 1 SKU-E-A1")

    assert state["status"] == "needs_review"
    assert "knowledge graph unavailable" in state["reason"]
    assert llm.calls == [] and state["last_draft"] is None and state["submissions"] == 0


def test_a_stale_graph_ends_the_run_before_any_model_call(db_session, make_reader):
    """(Review Focus) The graph was built before Postgres changed."""
    seed_world(db_session)
    reader = make_reader()
    db_session.get(Sku, "SKU-E-A1").discontinued = True
    db_session.flush()
    llm = ScriptedLLM([])

    state = run_agent(llm, make_ctx(db_session, reader, customer_id="CUST-E1", sku_ids=("SKU-E-A1",)), "quote")

    assert state["status"] == "needs_review"
    assert "out of date" in state["reason"]
    assert llm.calls == [] and state["last_draft"] is None


def test_a_graph_that_goes_down_mid_run_ends_needs_review_and_keeps_the_draft(run):
    """(Review Focus) The freshness check passed, then Neo4j went away before the guardrails ran."""
    holder = {}

    def take_the_graph_away(messages):
        holder["reader"].down = True
        return submit_turn(_draft([_line()]))

    state, _ = run([take_the_graph_away], wrap_reader=lambda reader: holder.setdefault("reader", TogglableReader(reader)))

    assert state["status"] == "needs_review"
    assert "knowledge graph unavailable" in state["reason"]
    assert state["last_draft"] is not None and state["submissions"] == 1


def test_a_required_parts_chain_deeper_than_the_retry_budget_ends_needs_review(db_session, make_reader):
    """(Review Focus) check_graph_integrity surfaces one new layer of missing required parts per pass. A chain
    that fits inside the retry budget must still reach ready; one hop deeper must exhaust it and end needs_review
    with the violation still present, never silently pass because retries ran out."""
    seed_world(db_session)
    for n in range(1, 6):
        upsert_sku(db_session, sku_id=f"SKU-L-R{n}", name=f"r{n}", category="Cat-L", list_price=1.0,
                   discontinued=False, replaced_by=None, in_stock=True)
    for n in range(1, 5):
        upsert_sku(db_session, sku_id=f"SKU-L-S{n}", name=f"s{n}", category="Cat-L", list_price=1.0,
                   discontinued=False, replaced_by=None, in_stock=True)
    db_session.flush()
    for n in range(1, 5):
        upsert_requirement(db_session, sku_id=f"SKU-L-R{n}", required_sku_id=f"SKU-L-R{n + 1}")
    for n in range(1, 4):
        upsert_requirement(db_session, sku_id=f"SKU-L-S{n}", required_sku_id=f"SKU-L-S{n + 1}")
    db_session.flush()
    reader = make_reader()

    def draft(*sku_ids):
        lines = [{"sku_id": s, "quantity": 1, "unit_price": 1.0, "price_source": "list", "discount_pct": 0.0}
                 for s in sku_ids]
        return {"customer_id": "CUST-E1", "contract_id": None, "lines": lines}

    within_budget = ScriptedLLM([
        submit_turn(draft("SKU-L-S1"), call_id="s0"),
        submit_turn(draft("SKU-L-S1", "SKU-L-S2"), call_id="s1"),
        submit_turn(draft("SKU-L-S1", "SKU-L-S2", "SKU-L-S3"), call_id="s2"),
        submit_turn(draft("SKU-L-S1", "SKU-L-S2", "SKU-L-S3", "SKU-L-S4"), call_id="s3"),
    ])
    exceeds_budget = ScriptedLLM([
        submit_turn(draft("SKU-L-R1"), call_id="r0"),
        submit_turn(draft("SKU-L-R1", "SKU-L-R2"), call_id="r1"),
        submit_turn(draft("SKU-L-R1", "SKU-L-R2", "SKU-L-R3"), call_id="r2"),
        submit_turn(draft("SKU-L-R1", "SKU-L-R2", "SKU-L-R3", "SKU-L-R4"), call_id="r3"),
    ])

    within = run_agent(
        within_budget, make_ctx(db_session, reader, customer_id="CUST-E1", sku_ids=("SKU-L-S1",)),
        "please quote 1 SKU-L-S1",
    )
    exceeds = run_agent(
        exceeds_budget, make_ctx(db_session, reader, customer_id="CUST-E1", sku_ids=("SKU-L-R1",)),
        "please quote 1 SKU-L-R1",
    )

    assert within["status"] == "ready" and within["submissions"] == 4
    assert exceeds["status"] == "needs_review" and exceeds["submissions"] == 4
    assert any(v.guardrail == "graph_integrity" for v in exceeds["violations"])
    assert "SKU-L-R4 requires SKU-L-R5" in exceeds["violations"][-1].message


def test_a_graph_that_becomes_stale_mid_run_ends_needs_review_before_reaching_ready(run, db_session):
    """(Review Focus) Freshness is checked on every submission, not once before the loop: reference data can
    change between two submissions inside a single multi-turn run, and the later one must not slip through
    against a reader built from the old data."""
    def go_stale_then_correct(messages):
        assert "SKU-E-B1 requires SKU-E-A1" in messages[-1]["content"]
        db_session.get(Sku, "SKU-E-A1").discontinued = True
        db_session.flush()
        return submit_turn(_draft([_line(sku_id="SKU-E-B1", unit_price=50.0), _line()]), call_id="call-2")

    without_part = _draft([_line(sku_id="SKU-E-B1", unit_price=50.0)])

    state, llm = run([submit_turn(without_part), go_stale_then_correct], sku_ids=("SKU-E-B1",))

    assert state["status"] == "needs_review"
    assert "out of date" in state["reason"]
    assert state["last_draft"] is not None and state["submissions"] == 2
    assert len(llm.calls) == 2


class RebuildDuringGuardrailReads:
    """Wraps the real reader. On the first chain or required-parts read after the guardrail pass's own freshness
    check (the second stored_fingerprint call; the first is run_agent's pre-check), it starts a real
    rebuild_reference_graph of the same namespace in a thread and holds it at its first call to `pause_at`, so the
    guardrail's reads see the namespace mid-rebuild. Every read still goes to the real Neo4j."""

    def __init__(self, inner, session, client, ns, monkeypatch, pause_at):
        self._inner, self.client, self.ns = inner, inner.client, inner.ns
        self._fingerprint_reads = 0
        self._started = False
        self._paused, self._release = threading.Event(), threading.Event()
        real = getattr(graph_service, pause_at)
        first = [True]

        def held(*args, **kwargs):
            if first[0]:
                first[0] = False
                self._paused.set()
                self._release.wait(30)
            return real(*args, **kwargs)

        monkeypatch.setattr(graph_service, pause_at, held)
        self._thread = threading.Thread(target=graph_service.rebuild_reference_graph, args=(session, client, ns))

    def _start_rebuild_once(self):
        if self._fingerprint_reads >= 2 and not self._started:
            self._started = True
            self._thread.start()
            assert self._paused.wait(30), "the rebuild never reached its pause point"

    def stored_fingerprint(self):
        self._fingerprint_reads += 1
        return self._inner.stored_fingerprint()

    def sku_chain(self, sku_id):
        self._start_rebuild_once()
        return self._inner.sku_chain(sku_id)

    def required_parts(self, sku_id):
        self._start_rebuild_once()
        return self._inner.required_parts(sku_id)

    def finish(self):
        self._release.set()
        if self._started:
            self._thread.join(60)


@pytest.mark.parametrize("pause_at", ["merge_nodes", "merge_edges"])
@pytest.mark.parametrize("requested, line", [
    ("SKU-E-OLD", _line(sku_id="SKU-E-OLD", unit_price=80.0)),
    ("SKU-E-B1", _line(sku_id="SKU-E-B1", unit_price=50.0)),
], ids=["discontinued_left_in", "required_part_missing"])
def test_a_rebuild_running_during_the_guardrail_reads_never_ends_ready(
    db_session, graph_client, graph_ns, make_reader, monkeypatch, pause_at, requested, line,
):
    """(Final review, Critical) The freshness check passed, then a rebuild of the same namespace wiped it (paused at
    merge_nodes) or reloaded only its nodes (paused at merge_edges) while the integrity rules were reading. An empty
    or edgeless graph makes those rules find nothing wrong, so the pass must re-check freshness afterwards."""
    seed_world(db_session)
    seed_chain_world(db_session)
    reader = RebuildDuringGuardrailReads(make_reader(), db_session, graph_client, graph_ns, monkeypatch, pause_at)
    ctx = make_ctx(db_session, reader, customer_id="CUST-E1", sku_ids=(requested,))
    try:
        state = run_agent(ScriptedLLM([submit_turn(_draft([line]))]), ctx, f"please quote 1 {requested}")
    finally:
        reader.finish()

    assert reader._started, "the rebuild was never started, so the race was not exercised"
    assert state["status"] == "needs_review"
    assert "changed while this draft was being checked" in state["reason"]
