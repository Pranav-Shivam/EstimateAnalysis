import copy

from core.llm.openai_agent_client import AgentTurn, ToolCall


class ScriptedLLM:
    """Plays back a fixed list of turns. A turn may be a callable taking the current messages, so a test can
    assert on what the agent was shown (for example, that violations were fed back) before answering."""

    def __init__(self, turns: list) -> None:
        self._turns = list(turns)
        self.calls: list[list[dict]] = []

    def next_turn(self, messages: list[dict], tools: list[dict]) -> AgentTurn:
        self.calls.append(copy.deepcopy(messages))
        if not self._turns:
            raise AssertionError("scripted LLM ran out of turns")
        turn = self._turns.pop(0)
        return turn(messages) if callable(turn) else turn


def call_turn(name: str, arguments: dict, call_id: str = "call-1") -> AgentTurn:
    return AgentTurn(content=None, tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)])


def submit_turn(draft: dict, call_id: str = "call-submit") -> AgentTurn:
    return call_turn("submit_draft", draft, call_id)


def text_turn(text: str = "thinking") -> AgentTurn:
    return AgentTurn(content=text, tool_calls=[])
