import pytest

from app.estimate.constant import MAX_AGENT_STEPS
from app.estimate.graph import run_agent
from tests.app.estimate.fakes import ScriptedLLM, call_turn, submit_turn, text_turn
from tests.app.estimate.seed import seed_chain_world, seed_world
from tests.graph_support import make_ctx


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
        return submit_turn(_draft([_line(sku_id="SKU-E-B1", unit_price=50.0)]), call_id="call-2")

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

    state, _ = run([call_turn("predict_price", {"sku_id": "SKU-E-GAP"}), after_prediction])

    assert state["status"] == "ready"
    assert state["last_draft"].lines[0].price_source == "predicted"


def test_made_up_predicted_price_is_blocked_and_ends_needs_review(run):
    made_up = _draft([_line(sku_id="SKU-E-GAP", unit_price=99.0, price_source="predicted")])
    turns = [submit_turn(made_up, call_id=f"call-{i}") for i in range(4)]

    state, _ = run(turns)

    assert state["status"] == "needs_review"
    assert state["violations"][0].guardrail == "price_provenance"
    assert "predicted price" in state["violations"][0].message
