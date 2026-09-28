from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.llm.openai_summary_client import SUMMARY_MODEL, SUMMARY_SYSTEM, OpenAISummaryClient, SummaryError


def _openai(content="  A tidy cluster.  ", choices=True):
    message = SimpleNamespace(content=content)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)] if choices else [])
    create = MagicMock(return_value=response)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), create


def test_summarize_returns_stripped_text_and_sends_the_system_prompt_and_model():
    openai, create = _openai()

    text = OpenAISummaryClient(client=openai).summarize("stats here")

    assert text == "A tidy cluster."
    kwargs = create.call_args.kwargs
    assert kwargs["model"] == SUMMARY_MODEL
    assert kwargs["messages"] == [
        {"role": "system", "content": SUMMARY_SYSTEM}, {"role": "user", "content": "stats here"},
    ]


def test_no_choices_is_a_summary_error():
    openai, _ = _openai(choices=False)

    with pytest.raises(SummaryError):
        OpenAISummaryClient(client=openai).summarize("x")


@pytest.mark.parametrize("content", [None, "", "   "])
def test_empty_content_is_a_summary_error(content):
    openai, _ = _openai(content=content)

    with pytest.raises(SummaryError):
        OpenAISummaryClient(client=openai).summarize("x")


def test_an_api_failure_is_wrapped():
    openai, create = _openai()
    create.side_effect = RuntimeError("boom")

    with pytest.raises(SummaryError, match="boom"):
        OpenAISummaryClient(client=openai).summarize("x")
