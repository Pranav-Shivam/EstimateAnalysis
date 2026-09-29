from types import SimpleNamespace

import pytest

from core.llm.anthropic_judge_client import AnthropicJudgeClient, JudgeError


class _FakeMessages:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._exc:
            raise self._exc
        return self._response


class _FakeAnthropic:
    def __init__(self, response=None, exc=None):
        self.messages = _FakeMessages(response, exc)


def _tool_use_response(input_payload):
    block = SimpleNamespace(type="tool_use", name="submit_scores", input=input_payload)
    return SimpleNamespace(content=[block])


def _good_payload():
    return {"dimensions": [
        {"name": "price_provenance", "score": 0.9, "rationale": "list price"},
        {"name": "contract_discount", "score": 1.0, "rationale": "no discount"},
        {"name": "graph_completion", "score": 0.8, "rationale": "complete"},
    ]}


def test_score_parses_a_well_formed_response():
    fake = _FakeAnthropic(response=_tool_use_response(_good_payload()))
    client = AnthropicJudgeClient(client=fake)

    result = client.score([{"line_index": 0}], "system prompt")

    names = {d.name for d in result.dimensions}
    assert names == {"price_provenance", "contract_discount", "graph_completion"}
    assert fake.messages.calls[0]["model"] == "claude-haiku-4-5-20251001"


def test_score_raises_on_api_exception():
    fake = _FakeAnthropic(exc=RuntimeError("network down"))
    client = AnthropicJudgeClient(client=fake)

    with pytest.raises(JudgeError, match="network down"):
        client.score([], "system prompt")


def test_score_raises_when_no_tool_use_block_is_returned():
    fake = _FakeAnthropic(response=SimpleNamespace(content=[SimpleNamespace(type="text", text="no")]))
    client = AnthropicJudgeClient(client=fake)

    with pytest.raises(JudgeError, match="no tool_use"):
        client.score([], "system prompt")


def test_score_raises_on_a_missing_dimension():
    payload = _good_payload()
    payload["dimensions"].pop()
    fake = _FakeAnthropic(response=_tool_use_response(payload))
    client = AnthropicJudgeClient(client=fake)

    with pytest.raises(JudgeError, match="expected 3 dimensions"):
        client.score([], "system prompt")


def test_score_raises_on_a_duplicate_dimension_name():
    payload = _good_payload()
    payload["dimensions"][2]["name"] = "price_provenance"
    fake = _FakeAnthropic(response=_tool_use_response(payload))
    client = AnthropicJudgeClient(client=fake)

    with pytest.raises(JudgeError, match="more than once"):
        client.score([], "system prompt")


def test_score_raises_on_an_out_of_range_score():
    payload = _good_payload()
    payload["dimensions"][0]["score"] = 1.5
    fake = _FakeAnthropic(response=_tool_use_response(payload))
    client = AnthropicJudgeClient(client=fake)

    with pytest.raises(JudgeError, match="not a number in"):
        client.score([], "system prompt")
