import json
from pathlib import Path

from app.estimate.constant import DATASET_AS_OF
from app.estimate.service import run_estimate
from app.intake.repository import save_quote_request
from app.reference_data.repository import contracts_for_customer, get_sku, required_sku_ids
from core.llm.openai_agent_client import AgentTurn, ToolCall
from core.tracing.langfuse_client import TracingClient
from load_data import load_catalog, load_customers, load_pricing, load_structure
from tests.graph_support import FakeEmbedder

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
FEEDBACK_PREFIX = "The draft failed validation"


def _load_world(session):
    load_catalog(session, json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8")))
    load_customers(session, json.loads((DATA_DIR / "customers.json").read_text(encoding="utf-8")))
    session.flush()
    load_pricing(session, json.loads((DATA_DIR / "pricing.json").read_text(encoding="utf-8")))
    load_structure(session, json.loads((DATA_DIR / "structure.json").read_text(encoding="utf-8")))
    session.flush()


def _cases(scenario_type):
    scenarios = json.loads((DATA_DIR / "scenarios.json").read_text(encoding="utf-8"))
    return [s for s in scenarios if s["scenario_type"] == scenario_type]


def _closure(session, sku_id):
    """The SKU and every part it needs, transitively, straight from Postgres (the test's own reference)."""
    ordered, queue = [], [sku_id]
    while queue:
        current = queue.pop(0)
        if current not in ordered:
            ordered.append(current)
            queue.extend(required_sku_ids(session, current))
    return ordered


def _line(sku, discount_pct=0.0):
    return {"sku_id": sku.sku_id, "quantity": 1, "unit_price": sku.list_price, "price_source": "list",
            "discount_pct": discount_pct}


def _submit(draft, call_id):
    return AgentTurn(content=None, tool_calls=[ToolCall(id=call_id, name="submit_draft", arguments=draft)])


class WalkingAgent:
    """A deterministic stand-in for the model that does what the system prompt says: ask the graph about the
    requested SKU and every required part, ask whether the customer's contract covers the SKU, then submit what the
    tools returned. With `naive_first` it submits the planted mistake first, so the test can see the guardrail
    block it. With `only_naive` it never learns, so the test can see the mistake never ends `ready`."""

    def __init__(self, session, case, *, naive_first=False, only_naive=False):
        entities = case["entities"]
        self._session = session
        self._scenario_type = case["scenario_type"]
        self._customer_id = entities["customer_id"]
        self._requested = entities["sku_id"]
        self._naive_first = naive_first
        self._only_naive = only_naive
        self._naive_sent = False
        self._ids = 0
        self.violation_feedback = None
        self.tool_names = []

    def next_turn(self, messages, tools):
        feedback = [m["content"] for m in messages if m["role"] == "user" and m["content"].startswith(FEEDBACK_PREFIX)]
        if feedback:
            self.violation_feedback = feedback[-1]
        if self._only_naive or (self._naive_first and not self._naive_sent):
            self._naive_sent = True
            return _submit(self._naive_draft(), self._next_id())

        related, coverage = self._tool_results(messages)
        calls, quoted = self._plan(related)
        if not calls and quoted[0] not in coverage:
            calls = [("check_contract_coverage", {"customer_id": self._customer_id, "sku_id": quoted[0]})]
        if calls:
            self.tool_names.extend(name for name, _ in calls)
            return AgentTurn(content=None, tool_calls=[
                ToolCall(id=self._next_id(), name=name, arguments=arguments) for name, arguments in calls
            ])
        return _submit(self._final_draft(quoted, coverage[quoted[0]]), self._next_id())

    def _next_id(self):
        self._ids += 1
        return f"walk-{self._ids}"

    @staticmethod
    def _tool_results(messages):
        related, coverage = {}, {}
        for message in messages:
            if message["role"] != "tool":
                continue
            try:
                payload = json.loads(message["content"])
            except json.JSONDecodeError:
                # submit_draft's tool response for a syntactically valid draft is the plain string
                # "draft received; running validation", not JSON: nothing for this method to collect.
                continue
            assert "error" not in payload, payload
            if "live_sku_id" in payload:
                related[payload["sku_id"]] = payload
            elif "contracts" in payload:
                coverage[payload["sku_id"]] = payload
        return related, coverage

    def _plan(self, related):
        """The tool calls still needed and, once none are, the SKUs to quote (requested SKU's live end first)."""
        calls, quoted, queue, seen = [], [], [self._requested], set()
        while queue:
            sku_id = queue.pop(0)
            if sku_id in seen:
                continue
            seen.add(sku_id)
            result = related.get(sku_id)
            if result is None:
                calls.append(("get_related_parts", {"sku_id": sku_id}))
                continue
            assert result["live_sku_id"] is not None, f"{sku_id} has no live replacement"
            if result["live_sku_id"] not in quoted:
                quoted.append(result["live_sku_id"])
            queue.extend(part["sku_id"] for part in result["required_parts"])
        return calls, quoted

    def _naive_draft(self):
        requested = get_sku(self._session, self._requested)
        if self._scenario_type == "discount_category_mismatch":
            contract = contracts_for_customer(self._session, self._customer_id)[0]
            return {"customer_id": self._customer_id, "contract_id": contract.contract_id,
                    "lines": [_line(requested, contract.discount_pct)]}
        return {"customer_id": self._customer_id, "contract_id": None, "lines": [_line(requested)]}

    def _final_draft(self, quoted, coverage):
        applying = next((c for c in coverage["contracts"] if c["discount_applies"]), None)
        lines = [
            _line(get_sku(self._session, sku_id), applying["discount_pct"] if applying and index == 0 else 0.0)
            for index, sku_id in enumerate(quoted)
        ]
        return {"customer_id": self._customer_id, "contract_id": applying["contract_id"] if applying else None,
                "lines": lines}


def _request(session, case):
    entities = case["entities"]
    return save_quote_request(
        session, raw_email_text=case["email_text"],
        parsed_json={"resolved_line_items": [
            {"sku_name_as_written": entities["sku_name"], "sku_id": entities["sku_id"], "quantity": "1"}]},
        content_fingerprint={"sku_ids": [entities["sku_id"]]}, style_fingerprint={"tokens": []},
        customer_id=entities["customer_id"], case_id=case["case_id"],
    )


def _run(session, graph, case, agent):
    return run_estimate(
        session, _request(session, case).id, DATASET_AS_OF, agent, graph, FakeEmbedder(), TracingClient(None),
    )


def _quoted_ids(run):
    return [line.sku_id for line in run.result.draft.lines]


def test_every_discontinued_swap_is_blocked_then_fixed_by_walking_the_graph(db_session, make_reader):
    _load_world(db_session)
    graph = make_reader()
    cases = _cases("discontinued_swap")
    assert len(cases) == 10

    for case in cases:
        agent = WalkingAgent(db_session, case, naive_first=True)

        run = _run(db_session, graph, case, agent)

        requested = case["entities"]["sku_id"]
        replacement = get_sku(db_session, requested).replaced_by
        assert run.result.status == "ready", case["case_id"]
        assert run.result.iterations == 2, case["case_id"]
        assert "discontinued" in agent.violation_feedback and requested in agent.violation_feedback, case["case_id"]
        assert requested not in _quoted_ids(run) and replacement in _quoted_ids(run), case["case_id"]
        assert "get_related_parts" in agent.tool_names, case["case_id"]


def test_every_missing_required_part_is_blocked_then_added_from_the_graph(db_session, make_reader):
    _load_world(db_session)
    graph = make_reader()
    cases = _cases("missing_required_part")
    assert len(cases) == 10

    for case in cases:
        agent = WalkingAgent(db_session, case, naive_first=True)

        run = _run(db_session, graph, case, agent)

        needed = _closure(db_session, case["entities"]["sku_id"])
        assert len(needed) >= 2, case["case_id"]
        assert run.result.status == "ready", case["case_id"]
        assert run.result.iterations == 2, case["case_id"]
        assert "requires" in agent.violation_feedback, case["case_id"]
        assert set(needed) <= set(_quoted_ids(run)), case["case_id"]
        assert "get_related_parts" in agent.tool_names, case["case_id"]


def test_every_wrong_category_discount_is_blocked_then_dropped_after_asking_the_graph(db_session, make_reader):
    _load_world(db_session)
    graph = make_reader()
    cases = _cases("discount_category_mismatch")
    assert len(cases) == 10

    for case in cases:
        agent = WalkingAgent(db_session, case, naive_first=True)

        run = _run(db_session, graph, case, agent)

        requested_line = run.result.draft.lines[0]
        assert run.result.status == "ready", case["case_id"]
        assert run.result.iterations == 2, case["case_id"]
        assert "not covered" in agent.violation_feedback, case["case_id"]
        assert requested_line.sku_id == case["entities"]["sku_id"] and requested_line.discount_pct == 0.0, case["case_id"]
        assert "check_contract_coverage" in agent.tool_names, case["case_id"]


def test_the_planted_mistakes_never_end_ready_even_if_the_agent_never_learns(db_session, make_reader):
    _load_world(db_session)
    graph = make_reader()

    for scenario_type in ("discontinued_swap", "missing_required_part", "discount_category_mismatch"):
        for case in _cases(scenario_type):
            run = _run(db_session, graph, case, WalkingAgent(db_session, case, only_naive=True))

            assert run.result.status == "needs_review", case["case_id"]
            assert run.result.violations, case["case_id"]
            assert run.result.iterations == 4, case["case_id"]
