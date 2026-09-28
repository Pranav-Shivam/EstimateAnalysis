# Phase 3 Design: Agent Loop, Pricing Tools, Guardrails

Date: 2026-09-28. Roadmap: `docs/roadmap.md` Phase 3. Research: `docs/research/pricing-model-and-guardrails.md`.

## Goal

Given a Phase 2 `QuoteRequest` (a `quote_requests` row), a LangGraph agent produces a priced draft estimate. Deterministic guardrail code, not the LLM, decides whether a draft is acceptable. Done when the agent produces a priced draft for a Phase 1 scenario email, and guardrails provably block at least one deliberately planted bad-discount case.

## Scope

In: price data additions, agent loop, tools, three guardrails, draft persistence, one HTTP endpoint, tests.

Out (later phases): Neo4j traversal (Phase 4; relationships here come from SQL), LLM judge and confidence calibration (Phase 5), tracing (Phase 6), UI (Phase 7).

## Decisions (agreed during brainstorming)

1. **Price book model.** `list_price` plus a per-contract `discount_pct` plus a `price_history` table. Matches the CPQ contracted-pricing shape (list price, scoped discount, effective dates).
2. **Price prediction.** Some SKUs are a price-book gap: no list price and no history. `predict_price` estimates from same-category peers (median list price with low/high range), tagged `predicted`, low confidence. Deterministic code, not an LLM guess. This design choice is our own judgment: no source was found for price prediction of SKUs with no history.
3. **Remediation policy.** The agent auto-resolves and annotates. Discontinued SKU: substitute `replaced_by`. Missing required part: add the required SKU. Discount not backed by the contract: guardrail rejects, agent re-prices that line at list. Every auto-change is recorded in `adjustments`. If a replacement is out of stock, or an added required part is discontinued, the draft is flagged instead of auto-fixed.
4. **Discount authority.** The LLM proposes a `discount_pct` per line (it may come from a tool result or from the email text). The guardrail is the sole authority. This makes the planted bad-discount case realistic: an email nudges the model to over-apply a contract rate.
5. **Quote date.** The agent takes an `as_of` date, defaulting to the documented constant `DATASET_AS_OF = 2024-09-01`. Reason: the synthetic contracts span 2023 to 2027 and only 9 of 125 are active on the real current date (0 of the 10 planted mismatch cases), which would make every discount look expired and hide the category-mismatch check. At 2024-09-01, 117 of 125 contracts are active, including all 10 mismatch cases. A real system would use the request's received timestamp.

## Architecture

Layer order follows `docs/backend-structure.txt`: route, service, repository, DB/LLM.

### Data additions

- `scripts/data_gen/price_gen.py`: seeded like the other generators (seed offset distinct from catalog, customers, scenarios). Writes `data/pricing.json` containing:
  - `discounts`: `contract_id` to `discount_pct`, chosen from {5, 8, 10, 12, 15}.
  - `gap_sku_ids`: about 10% of SKUs. Scenario-case SKUs, their `replaced_by` targets, and their required parts are excluded so planted cases stay priceable.
  - `history`: rows (`sku_id`, `unit_price`, `quoted_on`) for every non-gap SKU, realized price about 85 to 100% of list.
- Phase 1 output files are not modified.
- Alembic migration `0002`:
  - `skus.list_price` becomes nullable.
  - `contracts.discount_pct` (numeric, not null; the migration backfills existing rows).
  - New table `sku_requirements` (`sku_id`, `required_sku_id`), because `REQUIRES` currently lives only in `catalog.json`.
  - New table `price_history`.
  - New table `estimate_drafts` (`id` UUID, `quote_request_id` FK, `status`, `draft` JSONB nullable, `violations` JSONB, `iterations` int, `reason` text nullable, `created_at`).
- `scripts/load_data.py` loads requirements, discounts, gap flags and history. `validate.py` gains checks for `pricing.json`: every contract has a discount, gap SKUs have no history, history references real SKUs.

### Module `app/estimate/`

- `schemas.py`: `DraftLine` (sku_id, quantity, unit_price, price_source, discount_pct), `Adjustment` (kind, from, to, reason), `Violation` (guardrail, line index or null, message), `EstimateDraft` (customer_id, contract_id, lines, adjustments, flags), `Totals`, `EstimateResult` (status, as_of, draft, totals, violations, iterations, reason). `flags` are free-text reviewer notes the agent adds when it cannot auto-fix (for example an out-of-stock replacement); a draft with flags ends as `needs_review` even when every guardrail passes. Totals are computed by code, never submitted by the agent.
- `tools.py`: plain functions over a session, each returning data plus its source:
  - `lookup_customer`: customer, contract terms, whether the contract is active on `as_of`.
  - `search_price_book`: list price and last realized price, or "unpriced".
  - `check_stock`.
  - `get_related_parts`: a SKU's replacement (if discontinued) and its required parts.
  - `predict_price`: category-peer median with low/high, tagged `predicted`.
- `guardrails.py`: pure functions (draft plus reference data in, list of violations out).
- `graph.py`: the LangGraph wiring.
- `service.py`: `run_estimate(session, quote_request_id, as_of, llm_client)`.
- `repository.py`: saves and loads `estimate_drafts`.
- `api/v1/estimate/`: `POST /v1/estimate {quote_request_id, as_of?}` returns the draft, status and violations. Explicit commit after work, as in Phase 2.
- `core/llm/`: an OpenAI tool-calling client wrapper, injected so tests can pass a scripted fake. The API key comes from `Settings`, as in the intake route.

### Graph

```
agent (GPT-4o, tool calling) --tool calls--> tools --> agent
agent --submit_draft--> guardrails
guardrails --pass--> END (status ready)
guardrails --fail, fewer than 3 retries used--> agent (violation messages appended)
guardrails --fail, 3 retries already used--> END (status needs_review)
tool-step cap of 12 --> END (status needs_review)
```

`submit_draft` is a tool the agent calls to hand over its draft. It carries the draft payload and routes to the guardrail node.

### Guardrails

Run on every submitted draft, in code only:

1. **Contract discount.** A line's `discount_pct` must be 0 unless: the SKU's category is in the contract's `covered_categories`, the contract is active on `as_of`, and the pct equals the contract's `discount_pct`. Otherwise a violation names the line and the reason (uncovered category, expired contract, wrong pct).
2. **Required-field completeness.** Customer resolved; each line has a resolved SKU, an integer quantity above 0, a unit price and a `price_source`. An ambiguous quantity in the email ("4 or 5") must be recorded as an adjustment with the assumed value.
3. **Price provenance.** `unit_price` must equal the price-book value for that SKU, or be marked `predicted` and match `predict_price` output. Stops the LLM inventing a price.

Violations are returned to the agent as per-line messages.

## Error handling

- LLM call failure raises a typed `AgentError`, surfaced by the route as 502 (mirrors `ExtractionError`).
- Unknown `quote_request_id`: 404.
- Loop caps end the run as `needs_review`, never as an error and never as `ready`. "3 retries" means up to 4 submissions: the first, then 3 re-submissions after guardrail failures. The 12-step cap counts agent turns.

## Testing

- The suite makes no real OpenAI calls. A scripted fake LLM client drives the graph.
- Real Postgres on port 5433 with the rollback fixture. No assertion on absolute row counts; tests check only rows they create.
- Unit: each tool; each guardrail (pass and each violation kind); `predict_price` including a category with too few peers.
- Graph scenarios: clean draft; discontinued swap; missing required part; predicted price; planted bad discount blocked then corrected on retry; bad discount that persists through 3 retries and ends `needs_review`; expired contract using an explicit `as_of`; tool-step cap.
- Acceptance: for each of the 10 real `discount_category_mismatch` cases in `scenario_cases.json`, the scripted agent proposes a discount on the uncovered SKU and the guardrail must block it.
- Data: `price_gen` determinism, gap exclusions, loader idempotence, `validate.py` checks.

## Known gaps carried in

- No live-OpenAI run over the 60 real emails. It costs real money; it will not run without explicit approval.
- Phase 2 dedupe is not idempotent and has no timestamps. Phase 3 does not depend on either.
- `DATASET_AS_OF` is a synthetic-data convention, not production behavior.
- The three guardrails do not block a draft that leaves a discontinued SKU in place or omits a required part; those two cases are handled by agent policy only in Phase 3 (the graph in Phase 4 is the natural place to enforce them).
- Predicted prices are noise-level accurate because Phase 1 list prices are random per SKU. They are tagged and low-confidence by design; calibration is Phase 5.
