from openai import OpenAI

SUMMARY_MODEL = "gpt-4o-mini"

SUMMARY_SYSTEM = (
    "You summarize one cluster of products from a plumbing and HVAC supply catalog. State only what the statistics "
    "and member names you are given show. Do not infer purchase behavior, prices, customers, or anything that is "
    "not listed. Write two or three plain sentences."
)


class SummaryError(Exception):
    pass


class OpenAISummaryClient:
    def __init__(self, client: OpenAI | None = None) -> None:
        self._client = client or OpenAI()

    def summarize(self, prompt: str) -> str:
        try:
            response = self._client.chat.completions.create(
                model=SUMMARY_MODEL,
                messages=[{"role": "system", "content": SUMMARY_SYSTEM}, {"role": "user", "content": prompt}],
            )
        except Exception as exc:
            raise SummaryError(f"OpenAI summary call failed: {exc}") from exc

        if not response.choices:
            raise SummaryError("OpenAI returned no choices")
        content = response.choices[0].message.content
        if not content or not content.strip():
            raise SummaryError("OpenAI returned an empty summary")
        return content.strip()
