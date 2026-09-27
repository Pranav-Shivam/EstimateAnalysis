from openai import OpenAI

from app.intake.schemas import QuoteRequestExtraction

EXTRACTION_MODEL = "gpt-4o"

EXTRACTION_INSTRUCTIONS = (
    "Extract a structured quote request from this customer email. "
    "Use only facts present in the email text; never invent a customer name, "
    "SKU name, or quantity that is not written there."
)


class ExtractionError(Exception):
    pass


class OpenAIExtractionClient:
    def __init__(self, client: OpenAI | None = None) -> None:
        self._client = client or OpenAI()

    def extract_quote_request(self, email_text: str) -> QuoteRequestExtraction:
        try:
            response = self._client.responses.parse(
                model=EXTRACTION_MODEL,
                input=[
                    {"role": "system", "content": EXTRACTION_INSTRUCTIONS},
                    {"role": "user", "content": email_text},
                ],
                text_format=QuoteRequestExtraction,
            )
        except Exception as exc:
            raise ExtractionError(f"OpenAI extraction call failed: {exc}") from exc

        parsed = response.output_parsed
        if parsed is None:
            raise ExtractionError("OpenAI response did not contain parsed output")
        return parsed
