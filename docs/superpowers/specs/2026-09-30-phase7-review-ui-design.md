# Phase 7 Design: Review Queue UI

Date: 2026-09-30. Roadmap: `docs/roadmap.md` Phase 7. Research: `docs/research/frontend-stack-versions.md` (verified versions, Tailwind 4 + antd 6 layer setup). ADRs in force: none change; this phase adds read-only backend surface and a frontend. Builds on Phase 5's `judge_verdicts`/`review_items`, Phase 6's `POST /v1/review/{id}/resolve` and consolidation, Phase 2's dedupe verdicts, Phase 3's estimate drafts.

## Goal

A reviewer opens the app, sees a low-confidence quote with the one flagged fact, approves or corrects it, and then sees that correction take effect on a later identical quote. The UI is a view onto data the backend phases already produce; the only backend work is read-only endpoints (plus CORS) so the UI has something real to render.

Done when: with the demo dataset seeded, a reviewer can (1) open the queue and see a flagged quote with its reason, (2) open the detail view and see the estimate lines, the dedupe verdicts and the graph/price/contract evidence for the flagged fact, (3) correct it, and (4) open the same quote after the seed script's replay step and see a second, clean estimate with no review item, next to the first flagged one. The dashboard shows the three tracked rates.

## Scope

In:
- Backend read endpoints: `GET /v1/review?status=`, `GET /v1/quotes`, `GET /v1/quotes/{id}`, `GET /v1/metrics`. CORS middleware.
- `scripts/seed_demo.py` and `scripts/demo/` (scripted LLM fakes, scenario driver, replay step).
- `frontend/`: Vite + React + TypeScript + Tailwind + Ant Design app with four screens (queue, quote detail, all quotes, dashboard).
- OpenAPI-generated TypeScript types.
- Tests: pytest for endpoints and one seed-replay acceptance test; Vitest + Testing Library for the frontend.

Out (documented as gaps at phase close):
- Auth of any kind, consistent with the rest of the POC.
- Any UI that triggers intake, dedupe, estimate or judge. Those calls hit paid OpenAI/Anthropic APIs and there is no key; the seed script covers data instead.
- Resolving guardrail-path review items (`needs_review` drafts, dimension `guardrail`). `resolve` rejects them today (400 `ReviewItemNotResolvable`); the UI shows them read-only with the violation list and no action buttons.
- A live graph query view. The evidence path shown is the snapshot the judge stored.
- Correcting a discount percentage (carried from Phase 6), live Langfuse links, live false-auto-send monitoring.

## Decisions (agreed during brainstorming)

1. **Include the backend read endpoints in this phase.** Nothing lists estimates, quote requests, dedupe verdicts or judge verdicts today, and the roadmap's done-when cannot be met without them.
2. **Seed script drives the real services with scripted LLM fakes**, not fixture rows. Stored evidence, graph paths and review items are produced by real code, and the "later identical quote skips review" step is real (resolve, consolidate inline, re-run). Only the OpenAI agent and Anthropic judge clients are faked, as the acceptance tests already do. Rejected: hand-inserted fixture rows (drift from real shapes, cannot replay a correction), and recorded live outputs (needs API keys that do not exist).
3. **Guardrail-path items are read-only in the UI** (option a). Approving a guardrail-blocked draft raises open semantics (what does it mean, does it feed the eval set) that belong to a later phase.
4. **Graph evidence path comes from stored judge evidence**, not a live graph query. It is an audit snapshot of what the judge saw at judging time, which is what a reviewer needs to check the flagged fact.
5. **API types are generated from FastAPI's OpenAPI schema** (`openapi-typescript`), so a backend schema change fails the frontend build instead of the browser.
6. **Tailwind 4 and antd 6 coexist via cascade layers** (verified in `docs/research/frontend-stack-versions.md`): `StyleProvider layer` plus `@layer theme, base, antd, components, utilities;` before `@import "tailwindcss"`.
7. **`GET /v1/review` gains an optional `status` filter, default `open`**, so the existing route's behavior and its callers do not change.

Decisions made without a question (forced by constraints already set):
- Frontend lives in `frontend/` at the repo root, next to `backend/`. Dev server on Vite's default port; backend CORS allows that origin from a setting (`cors_allowed_origins`), not a hardcoded string.
- No new write endpoint. The UI's only writes go through the existing `POST /v1/review/{id}/resolve`.
- Latest stable versions of every package, per the research doc; re-verified at install time.

## Backend architecture

Layer order per `docs/backend-structure.txt`: route, service, repository, DB. New read models span modules, so they get their own modules rather than being bolted onto `app/judge`.

### `api/v1/review/route.py` (change)

`list_review_items(status: Literal["open", "resolved", "all"] = "open")`. `app/judge/repository.py` gains `list_review_items(session, status)`; `list_open_review_items` becomes the `open` case of it (callers updated, no duplicate query). `ReviewItemListResponse` gains `quote_request_id` (so queue rows link to their quote) and the nullable `outcome`, `correction`, `resolved_at` so the resolved view can show what was done.

### `app/quotes/` and `api/v1/quotes/` (new)

- `repository.py`: reads across `quote_requests`, `dedupe_verdicts`, `estimate_drafts`, `judge_verdicts`, `review_items`. Batch queries (one per table keyed by the listed ids), not per-row loops, so the list endpoint is a fixed number of queries.
- `schema.py`: `QuoteSummary`, `QuoteDetail`, `EstimateWithJudgement` dataclasses/Pydantic models.
- `service.py`: assembles the payloads.
- `GET /v1/quotes` returns `list[QuoteSummary]`, newest first: `quote_request_id`, `case_id`, `customer_id`, `created_at`, `latest_estimate_status`, `latest_trusted` (from the latest judge verdict, null if not judged), `open_review_items` (count), `is_duplicate` (any `DUPLICATE_OF` verdict where this request is the subject), `estimate_count`.
- `GET /v1/quotes/{quote_request_id}` returns `QuoteDetail`: the request (`raw_email_text`, `parsed_json`, customer/site/contract ids), `dedupe_verdicts` (candidate id, verdict, both jaccards, `signals_fired`), a `skus` map (name, category, discontinued) for every SKU an estimate or its evidence mentions (the contract correction form needs the category, which stored evidence does not hold), and `estimates` newest first, each with `estimate_id`, `status`, `draft`, `totals`, `violations`, `reason`, `iterations`, `created_at`, its `judge_verdict` (or null) and its `review_items`. 404 when the request does not exist (`QuoteRequestNotFound`, mapped in the route like the other modules).
- The response reuses `EstimateDraft`, `Violation` and `DimensionScore` from existing schemas rather than redefining them.

### `app/metrics/` and `api/v1/metrics/` (new)

`GET /v1/metrics` returns `{auto_send_rate, correction_rate, duplicate_rate, counts: {...}}`. Definitions, stated so the dashboard can label them exactly:
- `auto_send_rate` = judge verdicts with `trusted = true` / all judge verdicts.
- `correction_rate` = review items with `outcome = 'corrected'` / review items with an outcome (resolved).
- `duplicate_rate` = distinct quote requests that have at least one `DUPLICATE_OF` verdict / distinct quote requests that have any dedupe verdict.
- Each rate is `null` (not 0) when its denominator is zero, and `counts` returns numerators and denominators so the UI can show "3 of 12".

### `main.py` and `core/config/settings.py`

`CORSMiddleware` with `allow_origins=settings.cors_allowed_origins` (default `["http://localhost:5173"]`), methods `GET` and `POST`, no credentials. New routers registered.

## Seed script

`scripts/seed_demo.py` (dry run by default, `--yes` to write, same discipline as `embed_skus.py`):

- `scripts/demo/fakes.py`: scripted stand-ins for the extraction, agent and judge clients (`ScriptedExtractionClient`, `ScriptedAgentClient`, `DemoJudgeClient`) plus `build_draft`, which builds the draft a correct agent would submit. They implement the same interfaces as the real clients, so intake, `run_estimate` and `run_judge` run unmodified. No network.
- `scripts/demo/scenarios.py`: `select_cases` picks one Phase 1 scenario per role by predicates over the reference data (clean x2, discontinued, price_gap, graph_gap, contract_gap, duplicate pair, revision pair, blocked). A role no scenario can fill raises `DemoSetupError`; the demo never runs with a story missing. The dataset's unpriced SKUs appear in no scenario, so the price gap is planted by removing one scenario SKU's list price; the graph gap is planted by deleting one `SkuRequirement` row. The contract gap already exists in the data. The guardrail case is a draft with a zero quantity.
- `scripts/demo/seed.py`: `seed` runs intake, dedupe, estimate and judge per case through the real service functions and checks each outcome against the role's expectation (`DemoExpectationFailed`). `replay` re-runs estimate and judge for seeded quotes whose latest flag a reviewer has resolved, consolidating inline what the procrastinate worker would. With `cases`, it first resolves each flag with the case's planned correction; only the acceptance test does that.
- `seed_demo.py --replay` therefore resolves nothing itself: the reviewer corrects in the UI, then `--replay --yes` re-runs the quotes. The quote detail then shows two estimates: flagged, then clean.
- Prerequisites: Postgres and Neo4j up and the Phase 1 dataset loaded via `scripts/load_data.py`. The script exits with a clear message if the reference data is missing.
- Idempotence: it refuses to seed when seeded quotes already exist (tagged by `case_id`) and points to `--replay`.
- The fakes live in `scripts/demo/`, not `tests/`; the older acceptance tests are not refactored to share them.

## Frontend architecture

`frontend/` layout:

```
frontend/
  package.json, vite.config.ts, tsconfig.json, index.html
  src/
    main.tsx            providers: StyleProvider(layer) > ConfigProvider > QueryClientProvider > Router
    index.css           @layer order, @import "tailwindcss"
    api/
      schema.d.ts       generated by openapi-typescript (committed, regenerated by an npm script)
      client.ts         openapi-fetch client, base URL from VITE_API_URL
      queries.ts        TanStack Query hooks: useReviewItems, useQuotes, useQuote, useMetrics, useResolveReviewItem
    pages/
      QueuePage.tsx
      QuotesPage.tsx          all quotes, the only place clean, auto-sent and duplicate quotes are visible
      QuoteDetailPage.tsx
      DashboardPage.tsx
    components/
      FlaggedFactCard.tsx     the one fact, its dimension, Approve / Correct actions
      CorrectionForm.tsx      per-dimension form, client-side validation mirroring the backend shapes
      EvidencePanel.tsx       renders price / contract / graph evidence per dimension
      EstimateLinesTable.tsx
      DedupeVerdicts.tsx
      EstimateHistory.tsx     newest-first tabs, marks which estimate a review item belongs to
    lib/
      format.ts             money, percent, dates
```

### Screens

- **Queue (`/`)**: antd `Table` of review items, segmented control open / resolved / all. Columns: dimension tag, the fact (one line), quote (link to detail), created, and for resolved rows the outcome and correction. Empty state when the queue is clear.
- **Quote detail (`/quotes/:id`)**: header (customer, case id, duplicate badge). Sections: email and parsed request; dedupe verdicts; estimate tabs (newest first). Within an estimate: the lines table, totals, adjustments (substituted, added required part, discount removed), violations, judge scores per dimension with rationale, and the review item as a `FlaggedFactCard`. The evidence panel is per dimension:
  - `price_provenance`: price source, list price or predicted price with peer count and range.
  - `contract_discount`: contract id, covered, active on the as-of date, days to expiry, discount.
  - `graph_completion`: discontinued flag, live replacement SKU, required parts, and which are missing.
- **`FlaggedFactCard`** actions for an open, resolvable item: Approve (posts `outcome: approved`), Correct (opens `CorrectionForm`). For a resolved item, shows the outcome and correction read-only. For a `guardrail` item, shows the violation list and a note that guardrail-blocked drafts are not resolvable here; no buttons.
- **`CorrectionForm`** fields match `CORRECTION_FIELDS` in `backend/app/judge/schemas.py` exactly:
  - `price_provenance`: `sku_id` (select from the flagged lines), `corrected_unit_price` (positive number).
  - `graph_completion`: `sku_id` (select from the flagged lines), `required_sku_id` (text/select, must differ from `sku_id`).
  - `contract_discount`: `contract_id` and `category` (both taken from the flagged lines, read-only).
  Client validation is a convenience; the backend's 422 message is shown verbatim on failure, and 409 (already resolved) and 400 (not resolvable) get their own messages.
- **Dashboard (`/dashboard`)**: three antd `Statistic` cards for the rates, each with "n of m", and "no data yet" when the rate is null.

### Ant Design 6 notes

`Alert` takes `title` (not `message`); layout uses Tailwind flex and grid instead of `Space` (its API changed in v6). The frontend has no ESLint: `tsc --noEmit` is the static gate.

### State and errors

TanStack Query owns server state. Resolve is a mutation that invalidates the review, quote and metrics queries. Loading and error states are explicit on every page; a failed request shows the backend's `detail` string, not a generic message. Consolidation is asynchronous (procrastinate worker), so after a `corrected` resolve the UI states "correction saved, applying in the background" rather than claiming the fact is already live.

## Testing

- **TDD per task.**
- Backend pytest, against the real test DB like the existing suite: `GET /v1/review` status filter (open default unchanged, resolved, all), `GET /v1/quotes` (fixed query count, duplicate flag, latest verdict), `GET /v1/quotes/{id}` (multiple estimates newest first, 404), `GET /v1/metrics` (each rate, and null on empty denominators), CORS preflight from the allowed origin and rejection from another.
- **Acceptance test (the literal done-when, backend half)**: seed with fakes into the test DB, list the queue, resolve a correction, run consolidation, replay, fetch `GET /v1/quotes/{id}` and assert two estimates where the second has no review item, and `GET /v1/metrics` reflects the correction.
- Frontend Vitest + Testing Library (jsdom): `CorrectionForm` validation per dimension, `FlaggedFactCard` states (open, resolved, guardrail read-only), queue filter, dashboard null-rate rendering. The API layer is mocked at the fetch boundary, not the hooks.
- **Manual end-to-end verification** (reported honestly, not claimed from tests): `docker compose up`, load data, `seed_demo.py --yes`, start backend and frontend, walk queue to detail to correct, run `--replay`, reload detail. Uses the `run` skill.
- `openapi-typescript` output is regenerated in CI-style check: a test/script fails if `schema.d.ts` differs from what the running backend's schema would generate.
- No real OpenAI, Anthropic or Langfuse calls anywhere.

## Deferred gaps (documented at phase close)

- No pipeline-trigger UI; needs live API keys.
- Guardrail-path items are read-only.
- Evidence is a stored snapshot, not a live graph view.
- No auth; CORS is origin-scoped only.
- Replay proves correction-to-clean for the three correctable dimensions with scripted judge output, not a real model's judgment; the real calibrated run is still blocked on the missing Anthropic key (Phases 4 to 6 gap).
- TypeScript is pinned to 5.9.3: `openapi-typescript` 7.13 crashes under TypeScript 7 (no JavaScript compiler API). Lift the pin when it supports 7.
