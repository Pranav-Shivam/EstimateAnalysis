from unittest.mock import MagicMock

import pytest

from app.intake.schemas import LineItemExtraction, QuoteRequestExtraction
from core.llm.openai_client import ExtractionError, OpenAIExtractionClient


def test_extract_quote_request_returns_parsed_model():
    fake_parsed = QuoteRequestExtraction(
        customer_name_as_written="Zenith Contractors",
        line_items=[LineItemExtraction(sku_name_as_written="Widget", quantity="4")],
        raw_text="need 4 widgets",
    )
    fake_response = MagicMock(output_parsed=fake_parsed)
    fake_openai_client = MagicMock()
    fake_openai_client.responses.parse.return_value = fake_response

    client = OpenAIExtractionClient(client=fake_openai_client)
    result = client.extract_quote_request("need 4 widgets")

    assert result.customer_name_as_written == "Zenith Contractors"
    assert result.line_items[0].sku_name_as_written == "Widget"


def test_extract_quote_request_raises_extraction_error_on_api_failure():
    fake_openai_client = MagicMock()
    fake_openai_client.responses.parse.side_effect = RuntimeError("rate limited")

    client = OpenAIExtractionClient(client=fake_openai_client)
    with pytest.raises(ExtractionError):
        client.extract_quote_request("some email")


def test_extract_quote_request_raises_when_response_has_no_parsed_output():
    fake_response = MagicMock(output_parsed=None)
    fake_openai_client = MagicMock()
    fake_openai_client.responses.parse.return_value = fake_response

    client = OpenAIExtractionClient(client=fake_openai_client)
    with pytest.raises(ExtractionError):
        client.extract_quote_request("some email")
