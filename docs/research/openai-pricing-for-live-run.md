# OpenAI prices used by the live run

Used by `backend/scripts/live_run/meter.py` to turn token counts into dollars and to enforce the spend cap.

## Prices (searched 2026-09-30)

| Model | Input per 1M tokens | Output per 1M tokens |
|---|---|---|
| gpt-4o (2024-08-06) | $2.50 | $10.00 |
| text-embedding-3-small | $0.02 | none |

Source: third-party price aggregators surfaced by a web search (for example modelcompare.dev and computeprices.com). The official pricing page at openai.com/api/pricing returned HTTP 403 to `WebFetch`, so these numbers are not confirmed against OpenAI's own page. Treat the dollars in the live run report as an estimate from these prices, and check the OpenAI usage dashboard for the real charge.

## Rate limit observed

The organization used for the run has a gpt-4o limit of 30,000 tokens per minute. A run of many agent turns hit HTTP 429 on that limit. The live run script sets `max_retries=10` on the OpenAI client so the SDK backs off and retries instead of failing the case.
