import json
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from app.estimate.constant import MAX_AGENT_STEPS, MAX_GUARDRAIL_RETRIES, RECURSION_LIMIT
from app.estimate.guardrails import check_graph_integrity, graph_is_current, run_guardrails
from app.estimate.prompts import SYSTEM_PROMPT
from app.estimate.schemas import EstimateDraft, Violation
from app.estimate.tools import TOOL_SPECS, ToolContext, handle_tool
from core.graph.client import GraphError
from core.llm.openai_agent_client import ToolCall

SUBMIT_TOOL = "submit_draft"


class AgentState(TypedDict):
    messages: list[dict]
    tool_calls: list[ToolCall]
    pending_draft: EstimateDraft | None
    last_draft: EstimateDraft | None
    violations: list[Violation]
    retries: int
    submissions: int
    steps: int
    status: str | None
    reason: str | None


def _assistant_message(turn) -> dict:
    # The API allows null content only alongside tool_calls; an empty completion must be sent back as "".
    message: dict = {"role": "assistant", "content": turn.content if turn.tool_calls else turn.content or ""}
    if turn.tool_calls:
        message["tool_calls"] = [
            {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
            for c in turn.tool_calls
        ]
    return message


def _violation_message(violations: list[Violation]) -> str:
    lines = [
        f"- {'line ' + str(v.line_index) if v.line_index is not None else 'draft'}: {v.message}" for v in violations
    ]
    return "The draft failed validation. Fix these and call submit_draft again:\n" + "\n".join(lines)


def build_graph(llm, ctx: ToolContext):
    def agent_node(state: AgentState) -> dict:
        if state["steps"] >= MAX_AGENT_STEPS:
            return {"status": "needs_review", "reason": f"agent used all {MAX_AGENT_STEPS} steps without a passing draft"}
        turn = llm.next_turn(state["messages"], TOOL_SPECS)
        messages = state["messages"] + [_assistant_message(turn)]
        if not turn.tool_calls:
            messages.append({"role": "user", "content": "Call submit_draft with your draft when it is ready."})
        return {"messages": messages, "tool_calls": turn.tool_calls, "steps": state["steps"] + 1}

    def route_after_agent(state: AgentState) -> str:
        if state["status"] is not None:
            return "end"
        return "tools" if state["tool_calls"] else "agent"

    def tools_node(state: AgentState) -> dict:
        messages = list(state["messages"])
        pending = None
        for call in state["tool_calls"]:
            if call.name == SUBMIT_TOOL:
                try:
                    pending = EstimateDraft.model_validate(call.arguments)
                    content = "draft received; running validation"
                except ValidationError as exc:
                    content = json.dumps({"error": f"invalid draft: {exc.errors(include_url=False)}"}, default=str)
            else:
                content = json.dumps(handle_tool(ctx, call.name, call.arguments), default=str)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
        return {"messages": messages, "tool_calls": [], "pending_draft": pending}

    def route_after_tools(state: AgentState) -> str:
        return "guardrails" if state["pending_draft"] is not None else "agent"

    def guardrails_node(state: AgentState) -> dict:
        draft = state["pending_draft"]
        update: dict = {"pending_draft": None, "last_draft": draft, "submissions": state["submissions"] + 1}
        try:
            # Checked on every pass, not just once before the loop starts: reference data can change between
            # two submissions inside a single multi-turn run, and a stale graph must never approve a later one.
            if not graph_is_current(ctx.session, ctx.graph):
                return {
                    **update, "violations": [], "status": "needs_review",
                    "reason": "knowledge graph is out of date with the reference data; rebuild it",
                }
            with ctx.trace.span("graph_integrity_check") as span:
                graph_check = check_graph_integrity(ctx.graph, draft, ctx.request_sku_ids)
                span.update(output={
                    "violation_count": len(graph_check.violations), "unreplaceable": graph_check.unreplaceable,
                })
            # A rebuild drops GraphMeta first and writes it back last, so if it started during the reads above,
            # the graph is no longer current now. Nothing those reads concluded can be trusted in that case.
            if not graph_is_current(ctx.session, ctx.graph):
                return {
                    **update, "violations": [], "status": "needs_review",
                    "reason": "knowledge graph changed while this draft was being checked; a rebuild ran mid-check",
                }
        except GraphError as exc:
            return {**update, "violations": [], "status": "needs_review", "reason": f"knowledge graph unavailable: {exc}"}

        violations = run_guardrails(ctx.session, draft, ctx.as_of, ctx.request_customer_id) + graph_check.violations
        update["violations"] = violations
        if graph_check.unreplaceable:
            return {
                **update, "status": "needs_review",
                "reason": "no live replacement exists for " + ", ".join(graph_check.unreplaceable),
            }
        if not violations:
            if draft.flags:
                return {**update, "status": "needs_review", "reason": "draft carries flags for the reviewer"}
            return {**update, "status": "ready"}
        if state["retries"] >= MAX_GUARDRAIL_RETRIES:
            return {
                **update, "status": "needs_review",
                "reason": f"guardrail violations persisted after {MAX_GUARDRAIL_RETRIES} retries",
            }
        messages = state["messages"] + [{"role": "user", "content": _violation_message(violations)}]
        return {**update, "retries": state["retries"] + 1, "messages": messages}

    def route_after_guardrails(state: AgentState) -> str:
        return "end" if state["status"] is not None else "agent"

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_node("guardrails", guardrails_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_after_agent, {"tools": "tools", "agent": "agent", "end": END})
    graph.add_conditional_edges("tools", route_after_tools, {"guardrails": "guardrails", "agent": "agent"})
    graph.add_conditional_edges("guardrails", route_after_guardrails, {"agent": "agent", "end": END})
    return graph.compile()


def _initial_state(request_message: str) -> AgentState:
    return {
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": request_message}],
        "tool_calls": [], "pending_draft": None, "last_draft": None, "violations": [],
        "retries": 0, "submissions": 0, "steps": 0, "status": None, "reason": None,
    }


def run_agent(llm, ctx: ToolContext, request_message: str) -> AgentState:
    initial = _initial_state(request_message)
    # Verify the graph before spending any model call: a run the guardrails cannot check must not start.
    try:
        current = graph_is_current(ctx.session, ctx.graph)
    except GraphError as exc:
        return {**initial, "status": "needs_review", "reason": f"knowledge graph unavailable: {exc}"}
    if not current:
        return {
            **initial, "status": "needs_review",
            "reason": "knowledge graph is out of date with the reference data; rebuild it",
        }
    return build_graph(llm, ctx).invoke(initial, config={"recursion_limit": RECURSION_LIMIT})
