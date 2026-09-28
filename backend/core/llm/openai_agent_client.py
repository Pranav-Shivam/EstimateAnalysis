import json
from dataclasses import dataclass, field

from openai import OpenAI

AGENT_MODEL = "gpt-4o"


class AgentError(Exception):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class AgentTurn:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


class OpenAIAgentClient:
    def __init__(self, client: OpenAI | None = None) -> None:
        self._client = client or OpenAI()

    def next_turn(self, messages: list[dict], tools: list[dict]) -> AgentTurn:
        try:
            response = self._client.chat.completions.create(model=AGENT_MODEL, messages=messages, tools=tools)
        except Exception as exc:
            raise AgentError(f"OpenAI agent call failed: {exc}") from exc

        message = response.choices[0].message
        try:
            tool_calls = [
                ToolCall(id=call.id, name=call.function.name, arguments=json.loads(call.function.arguments))
                for call in (message.tool_calls or [])
            ]
        except json.JSONDecodeError as exc:
            raise AgentError(f"OpenAI returned malformed tool arguments: {exc}") from exc
        return AgentTurn(content=message.content, tool_calls=tool_calls)
