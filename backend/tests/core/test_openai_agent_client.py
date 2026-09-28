import json
from unittest.mock import MagicMock

import pytest

from core.llm.openai_agent_client import AGENT_MODEL, AgentError, OpenAIAgentClient


def _response(content=None, tool_calls=None):
    return MagicMock(choices=[MagicMock(message=MagicMock(content=content, tool_calls=tool_calls))])


def _tool_call(call_id, name, arguments):
    function = MagicMock(arguments=arguments)
    function.name = name
    return MagicMock(id=call_id, function=function)


def test_next_turn_parses_tool_calls():
    fake = MagicMock()
    fake.chat.completions.create.return_value = _response(
        tool_calls=[_tool_call("c1", "check_stock", json.dumps({"sku_id": "SKU-1"}))]
    )

    turn = OpenAIAgentClient(client=fake).next_turn([{"role": "user", "content": "hi"}], [{"type": "function"}])

    assert turn.tool_calls[0].id == "c1"
    assert turn.tool_calls[0].name == "check_stock"
    assert turn.tool_calls[0].arguments == {"sku_id": "SKU-1"}
    kwargs = fake.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == AGENT_MODEL
    assert kwargs["tools"] == [{"type": "function"}]


def test_next_turn_returns_text_only_turn():
    fake = MagicMock()
    fake.chat.completions.create.return_value = _response(content="thinking", tool_calls=None)

    turn = OpenAIAgentClient(client=fake).next_turn([], [])

    assert turn.content == "thinking"
    assert turn.tool_calls == []


def test_next_turn_raises_agent_error_on_api_failure():
    fake = MagicMock()
    fake.chat.completions.create.side_effect = RuntimeError("rate limited")

    with pytest.raises(AgentError) as excinfo:
        OpenAIAgentClient(client=fake).next_turn([], [])

    assert isinstance(excinfo.value.__cause__, RuntimeError)


def test_next_turn_raises_agent_error_on_malformed_tool_arguments():
    fake = MagicMock()
    fake.chat.completions.create.return_value = _response(tool_calls=[_tool_call("c1", "check_stock", "{not json")])

    with pytest.raises(AgentError):
        OpenAIAgentClient(client=fake).next_turn([], [])


def test_next_turn_raises_agent_error_when_response_has_no_choices():
    fake = MagicMock()
    fake.chat.completions.create.return_value = MagicMock(choices=[])

    with pytest.raises(AgentError):
        OpenAIAgentClient(client=fake).next_turn([], [])


@pytest.mark.parametrize("arguments", ["[]", '"x"', "null", "3", None])
def test_next_turn_raises_agent_error_when_tool_arguments_are_not_a_json_object(arguments):
    fake = MagicMock()
    fake.chat.completions.create.return_value = _response(tool_calls=[_tool_call("c1", "check_stock", arguments)])

    with pytest.raises(AgentError):
        OpenAIAgentClient(client=fake).next_turn([], [])
