# Pricing Model, Price Prediction, and Agent Guardrails

Research for Phase 3 (agent loop, pricing tools, guardrails). Searched 2026-09-28.

## Verified by fetching the source

### Contracted pricing in CPQ (Salesforce Trailhead)
Source: https://trailhead.salesforce.com/content/learn/modules/pricing-methods-for-salesforce-cpq/create-account-based-contracted-pricing

- A contract price record carries either a fixed price (single product) or a discount (multi-product, e.g. 5% off).
- Scope is either one product, or a filter (field, operator, value) matching many products. This is the category-scoped discount pattern.
- Effective date and expiration date bound when the price applies.
- Contracted pricing overrides the price book list price when a matching product is added.
- Pricing is a snapshot: later edits to the contract do not change existing quote lines.
- Cost-plus-markup takes precedence over contracted pricing when both could apply.

Takeaway: list price plus a contract discount scoped by product filter and effective dates is the industry-standard shape. Matches this repo's `covered_categories` and `effective_from/to`; the missing piece is the discount value itself.

### Agent guardrails (Anthropic, "Building effective agents")
Source: https://www.anthropic.com/research/building-effective-agents

- Programmatic checks ("gates") can be added on intermediate steps to confirm the process is on track.
- Stopping conditions such as a maximum iteration count are common, to keep control of an agent loop.
- Guardrails run as a separate model instance from the one producing the answer (already our ADR-0004 for the judge).
- Stresses simplicity in agent design and effort on tool interfaces.

Takeaway: deterministic gate code plus an iteration cap is endorsed practice. Supports code-level guardrails as a gate, not a prompt instruction.

## From search summaries only (secondary, not fetched)

- CPQ data model splits configure / price (list prices, price books, discount schedules) / quote (lines with applied discounts). Sources: thinkbeyond.cloud, cincom.com, dealhub.io in the search results.
- CPQ "price waterfall": ordered sequence of adjustments from list price to net. Source: pandadoc.com/blog/cpq-price-waterfall (fetch blocked, see below), so ordering details are unverified.
- Runtime guardrails framed as pre-execution (should this tool call proceed), runtime monitoring, and post-execution verification. Source: Galileo agent-guardrails framework page, arXiv survey results. Not fetched.

## Gap: no source found for SKU *price* prediction with no history

The "analog SKU" method (find sibling or comparable items, adjust) surfaced only in demand-forecasting material. The one page fetched (https://www.linearloop.io/blog/launch-sku-without-historical-data) is demand-only: it says nothing on price, describes analogs as directional not precise ("not perfect, but better than guesswork"), and says results must be adjusted for price point.

Do not cite the demand-forecasting analog method as evidence for price prediction. Using category and attribute analogs for price is a reasonable design choice by analogy, and should be recorded as our own judgment, not as a researched best practice.

## Blocked or failed

- https://www.pandadoc.com/blog/cpq-price-waterfall/ returned HTTP 429. Do not retry.
- WebSearch and WebFetch intermittently failed with an auto-mode classifier error (no verdict). Transient; retrying once usually worked.
