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

        if not response.choices:
            raise AgentError("OpenAI returned no choices")
        message = response.choices[0].message
        tool_calls = [_parse_tool_call(call) for call in (message.tool_calls or [])]
        return AgentTurn(content=message.content, tool_calls=tool_calls)


def _parse_tool_call(call) -> ToolCall:
    name = call.function.name
    try:
        arguments = json.loads(call.function.arguments)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AgentError(f"OpenAI returned malformed arguments for tool {name}: {exc}") from exc
    if not isinstance(arguments, dict):
        raise AgentError(f"OpenAI returned non-object arguments for tool {name}: got {type(arguments).__name__}")
    return ToolCall(id=call.id, name=name, arguments=arguments)
