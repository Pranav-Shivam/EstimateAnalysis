# Phase 6 Design: LLMOps and Tracing

Date: 2026-09-29. Roadmap: `docs/roadmap.md` Phase 6. Research: `docs/research/llm-judge-calibration.md` (Cohen's kappa / threshold-selection method, reused for the release gate). ADRs in force: 0003 (procrastinate + cachetools, no Redis). Builds on Phase 5's `judge_verdicts`/`review_items`, Phase 4's `GraphReader`/graph service, Phase 3's estimate/pricing.

## Goal

Close the "memory that compounds" loop: a human correcting a judge-flagged estimate should mean the same mistake is never repeated. Concretely, resolving a review item with a correction writes the missing or wrong reference fact into Postgres, permanently, for whichever of the three judge dimensions was flagged: a corrected price becomes the SKU's real `list_price`, a confirmed missing part becomes a new `SkuRequirement` row, a confirmed-covered category gets added to the contract's `covered_categories`. The next identical scenario reads the real fact instead of hitting the gap that required a human the first time, so the judge trusts it and no review item is created. Every resolution (approved or corrected) also grows a real eval set from production data, not just Phase 5's hand-authored golden set, and a release gate blocks writing a new calibrated threshold if it would push the false-auto-send rate on that eval set above an acceptable ceiling. Langfuse traces every run, tool call, graph hop, and dedupe decision, wired to the real SDK but safe to run with no Langfuse instance configured.

Done when: a planted correction (simulating a human fixing a predicted price, per the roadmap's own example) results in a new permanent fact (`Sku.list_price`), and a subsequent identical scenario's `price_provenance` check passes without producing a review item, as a single acceptance test. The same mechanism is proven for `graph_completion` and `contract_discount` too, one acceptance test each.

## Scope

In:
- Migration 0006: `review_items` gains `outcome`, `correction`, `resolved_at`; new `eval_cases` table. Migration 0007: procrastinate's own schema.
- `POST /v1/review/{review_item_id}/resolve`: records approve/correct, builds an eval case, enqueues consolidation on correct.
- `app/consolidation/`: procrastinate task, three correction handlers, one per judge dimension:
  - `price_provenance` → writes `Sku.list_price`.
  - `graph_completion` → writes a new `SkuRequirement` row.
  - `contract_discount` → appends a category to `Contract.covered_categories`.
  Each handler does a best-effort graph sync of the one node/edge it touched.
- `app/reference_data/repository.py`: write functions the consolidation handlers call (`set_sku_list_price`, `add_sku_requirement`, `add_contract_coverage`), all idempotent.
- `backend/scripts/run_worker.py`: procrastinate worker entrypoint.
- `app/judge/models.py`: `EvalCaseRow`. `scripts/calibrate_judge.py`: reads golden set + `eval_cases` together, computes false-auto-send rate at the swept threshold, refuses to write `calibration.json` if the rate exceeds a ceiling constant.
- `core/tracing/langfuse_client.py`: thin wrapper, no-ops when unconfigured. Instrumentation in the estimate agent loop, dedupe service, and graph reader's guardrail-time reads.
- `app/graph/service.py`: `sync_sku`, `sync_requirement`, `sync_contract_coverage` (single-node/single-edge best-effort syncs, same pattern as existing `sync_quote`/`sync_quote_request`).
- `.env.example`: commented-out `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST`.
- `pyproject.toml`: `procrastinate`, `langfuse` dependencies.

Out (deferred, documented as gaps at phase close):
- Live production false-auto-send tracking (flagging a previously auto-sent estimate as wrong after the fact) — the release gate reads the golden set + `eval_cases` only, not production `judge_verdicts` traffic.
- Self-hosted or cloud Langfuse actually receiving real traces — the SDK integration is real and testable against a fake client; connecting it to a live Langfuse instance needs your separate go-ahead, same as any other hosted-service call.
- Phase 7's review queue UI (this phase only builds the endpoint it will call).
- Re-judging superseding logic (Phase 5's carried-forward gap; unrelated to this phase).

## Decisions (agreed during brainstorming)

1. **Correction capture is new backend surface, not deferred to Phase 7.** `review_items.status='open'` only tracked existence, not resolution. Phase 6's own done-when requires planting a correction, so `POST /v1/review/{id}/resolve` is built now; Phase 7's UI calls it later, it doesn't invent it.
2. **Consolidation target for `price_provenance` is `Sku.list_price`, not a separate "corrected price" table.** Read from `check_price_provenance`/`_provenance_problem` (`backend/app/estimate/guardrails.py`): a line is scored `predicted` only when `sku.list_price is None`. Writing the corrected value into `Sku.list_price` is the only change that makes a *future* line for that SKU eligible for `price_source == "list"` and skip prediction entirely — a vector/semantic-only fact would not, because the guardrail reads `Sku.list_price` directly, never a vector store. This also lands as a **graph edge/property** for free: `rebuild_reference_graph` already projects `s.list_price` onto the SKU node.
3. **Three consolidation handlers this phase, one per judge dimension, all writing the reference fact the matching guardrail already reads:**
   - `price_provenance` → `Sku.list_price` (decision 2 above).
   - `graph_completion` → a new `SkuRequirement(sku_id, required_sku_id)` row. `check_graph_integrity` and the judge's `GraphEvidence.missing_required_part_ids` both derive from `reader.required_parts(sku_id)`, which is itself sourced from this table (`all_requirements` → `REQUIRES` edges in `rebuild_reference_graph`). A human confirming "X actually requires Y" when the graph has no such edge is exactly the class of fact code guardrails can't invent on their own; writing the row closes both the judge's low-confidence flag and the deterministic guardrail's blind spot for every future draft, not just the one under review.
   - `contract_discount` → appends a category to `Contract.covered_categories`. `check_contract_discount`'s first failure mode is `category not in contract.covered_categories`; `ContractEvidence.covered` mirrors the same check for the judge. A human confirming "this contract does cover that category" (a data-entry gap, not a policy change) is modeled here; correcting the discount *percentage* itself is a different, narrower kind of correction and stays out of scope; see Deferred gaps.
   All three follow the identical shape: read the missing/wrong reference fact off the review item's own evidence, write it into the Postgres table the relevant guardrail already reads, best-effort sync the one graph node/edge affected.
4. **Correction shape is read back from the review item's own evidence, not caller-supplied free text, and its shape is dimension-specific:**
   - `price_provenance`: `{"sku_id": "...", "corrected_unit_price": 42.50}`, `sku_id` must appear in the review item's stored `evidence["lines"]`; the price must be a finite number above zero.
   - `graph_completion`: `{"sku_id": "...", "required_sku_id": "..."}`, `sku_id` must appear in `evidence["lines"]`; `required_sku_id` must exist as a real SKU (checked at resolve time, not deferred to the consolidation task, so a bad correction fails the request instead of silently failing in the background).
   - `contract_discount`: `{"contract_id": "...", "category": "..."}`, `contract_id` must match the review item's own `evidence["lines"][*]["contract_id"]`, and `category` must be the `Sku.category` of a line flagged under that contract.
   Each shape takes exactly its listed keys with the listed types; a `corrected` outcome with no correction is rejected the same way (422).
   Every shape is validated against the review item's own evidence or a real reference-data lookup at resolve time; a resolve call can never invent a correction for something the judge never flagged.
5. **Both resolution outcomes feed the eval set, only `corrected` triggers consolidation.** `approved` means the judge over-escalated a genuinely fine estimate — valuable signal for a future lower threshold (`label='trust'`), but nothing to consolidate. `corrected` means the judge was right to escalate (`label='escalate'`) and produces a permanent fact.
6. **procrastinate over inline execution for consolidation**, per ADR-0003: the resolve endpoint enqueues a task rather than writing the correction synchronously in the request. Keeps the API request fast and matches ADR-0003's stated reason for adopting procrastinate at all ("consolidate every N conversations" style background work). Same Postgres instance (5433), no new service.
7. **`calibrate_judge.py` gains the release gate rather than a new script.** A separate `release_gate.py` would duplicate the same Anthropic-gated scoring loop under a second `--yes` flag. Folding the false-auto-send check into the existing script means one script, one gated real-API call path, and "release gating" reads naturally as "gating whether a new threshold gets released."
8. **False-auto-send rate is computed against the golden set + `eval_cases`, not live production traffic.** Same reasoning as Phase 5's kappa: `pairs = [(judge_trusts_at_threshold, human_label) for ...]` already exists in `calibration.py`; false-auto-send is `sum(1 for trust, human in pairs if trust and not human) / len(pairs)`, a two-line addition, no new production-monitoring feature.
9. **Langfuse is SDK-wired but no-op by default**, same dry-run-safe discipline as `embed_skus.py`/`summarize_communities.py`/`calibrate_judge.py`. `TracingClient(client: Langfuse | None)`; `None` (the default when `settings.langfuse_public_key` is unset) makes every span call a no-op. Avoids adding Langfuse's own stack (ClickHouse, Redis, separate Postgres/worker) to `docker-compose.yml`, which would cut directly against ADR-0003's "no new stateful services" reasoning.
10. **Tracing client is injected per call site, not a global singleton.** Matches this codebase's existing DI discipline (`AnthropicJudgeClient`, `OpenAIEmbeddingClient` are all constructor-injected); keeps every instrumented function testable with a fake tracer and no monkeypatching.

Decisions made without a question (constraints already set, or forced by the design):
- No auth on the new `/v1/review/{id}/resolve` route, consistent with the rest of the POC.
- `eval_cases.case_id` uses an `"rc-"` prefix (reviewer-corrected), distinct from the golden set's `"jg-"`, so the two sources stay distinguishable in `calibrate_judge.py`'s output.
- `Sku.list_price` correction is a direct overwrite, not a price-history table. No requirement in this phase reads price history; the guardrail only ever checks the current value.

## Architecture

Layer order follows `docs/backend-structure.txt`: route, service, repository, DB/LLM.

### `review_items` additions (migration 0006, `app/judge/models.py`)

```python
class ReviewItemRow(Base):
    ...
    # status: 'open' | 'approved' | 'corrected' | 'consolidated'
    outcome: Mapped[str | None] = mapped_column(Text)          # 'approved' | 'corrected'
    correction: Mapped[dict | None] = mapped_column(JSONB)
    resolved_at: Mapped[datetime | None]
```

`app/judge/schemas.py` adds `ResolveReviewItem(outcome: Literal["approved", "corrected"], correction: dict | None)`.

### `app/judge/service.py` additions

`resolve_review_item(session, review_item_id, outcome, correction) -> ReviewItemRow`:
- loads the row with `SELECT ... FOR UPDATE` so concurrent resolves serialize (404-equivalent `ReviewItemNotFound` if missing, `status != 'open'` raises `ReviewItemAlreadyResolved`). One exception: `corrected` again with the identical correction on a row still `corrected` is a redrive. It records no new eval case and only re-enqueues consolidation, the recovery path when the first enqueue was lost.
- if `outcome == "corrected"`: validates `correction` against `row.dimension`, per decision 4's per-dimension shape (`validate_correction(dimension, correction, evidence) -> None`, new pure function in `app/judge/schemas.py`, raises `InvalidCorrection` on any mismatch); an unrecognized `dimension` (no handler exists) also raises `InvalidCorrection` rather than silently accepting a correction nothing will ever consolidate
- updates `status`, `outcome`, `correction`, `resolved_at`
- calls `build_eval_case(row, outcome)` (new pure function in `app/judge/schemas.py`, mirroring how `evidence.py` builds other dataclasses, since `calibration.py` stays I/O-free per its current pure-function shape) to build an `EvalCase` value, then `repository.save_eval_case(session, case)` persists it as an `EvalCaseRow`
- on `corrected`, enqueues `consolidate_review_item.defer(review_item_id=str(review_item_id))`

`POST /v1/review/{review_item_id}/resolve` (new route in `app/judge`'s router) calls this and returns the updated `ReviewItem` schema plus `outcome`.

### `app/judge/models.py`: `EvalCaseRow`

```python
class EvalCaseRow(Base):
    __tablename__ = "eval_cases"
    id: UUID
    source_review_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("review_items.id"))
    case_id: Mapped[str] = mapped_column(Text, unique=True)   # "rc-0001", ...
    label: Mapped[str] = mapped_column(Text)                  # 'trust' | 'escalate'
    estimate_status: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSONB)              # same LineEvidence[] shape as judge_golden_set.json
    created_at: Mapped[datetime]
```

`case_id` sequence: `next_eval_case_id(session)` in `app/judge/repository.py`, `"rc-" + zero-padded count + 1`, mirroring the golden set's `"jg-NNNN"` convention closely enough to read side by side.

### `app/consolidation/` (new module)

- `models.py`: none needed beyond procrastinate's own tables (its bootstrap migration).
- `tasks.py`:
  ```python
  from procrastinate import App
  app = App(connector=...)  # PsycopgConnector, built from settings.database_url

  @app.task(name="consolidate_review_item")
  def consolidate_review_item(review_item_id: str) -> None: ...
  ```
  Loads the `ReviewItemRow` (must be `status == "corrected"`), dispatches on `dimension` to one of three handlers, each writing its fact then doing a best-effort graph sync via the existing `sync_best_effort` wrapper:
  - `"price_provenance"` → `set_sku_list_price(session, sku_id, corrected_unit_price)` (new `app/reference_data/repository.py` function: `session.get(Sku, sku_id)`, sets `list_price`, flush) → `sync_best_effort("sku price correction", sync_sku, session, client, ns, sku_id)`.
  - `"graph_completion"` → `add_sku_requirement(session, sku_id, required_sku_id)` (idempotent: `session.get(SkuRequirement, (sku_id, required_sku_id))` first, insert only if absent) → `sync_best_effort("sku requirement correction", sync_requirement, session, client, ns, sku_id, required_sku_id)`.
  - `"contract_discount"` → `add_contract_coverage(session, contract_id, category)` (idempotent: append only if `category not in contract.covered_categories`) → `sync_best_effort("contract coverage correction", sync_contract_coverage, session, client, ns, contract_id, category)`.
  - any other `dimension` → `logger.warning("no consolidation handler for dimension %s", dimension)`, no-op (defensive only: `resolve_review_item` already rejects an unrecognized dimension at correction time, per decision 4, so this path is unreachable in practice and exists only so a future dimension added without a handler fails loudly instead of crashing the worker).
  - marks the review item `status = "consolidated"`, commits.
  - locks the row first; a row already `consolidated` (a redelivered or redriven job) is a no-op. The task retries `OperationalError` (dropped connection, deadlock) with exponential backoff, at most 5 attempts; any other error fails the job at once.
- The API opens this app sync in its FastAPI lifespan (`main.py`): the resolve route is a sync `def`, and an async connector never opened async hands sync `.defer()` callers its own sync pool. The worker opens it async.
- Task is a plain function; tests call `consolidate_review_item(review_item_id=...)` directly against a session fixture rather than requiring a running worker (procrastinate tasks are ordinary callables when not `.defer()`-dispatched through a live app/worker).

### `app/reference_data/repository.py` additions

```python
def set_sku_list_price(session: Session, sku_id: str, list_price: float) -> None:
    sku = session.get(Sku, sku_id)
    sku.list_price = list_price
    session.flush()

def add_sku_requirement(session: Session, sku_id: str, required_sku_id: str) -> None:
    if session.get(SkuRequirement, (sku_id, required_sku_id)) is None:
        session.add(SkuRequirement(sku_id=sku_id, required_sku_id=required_sku_id))
        session.flush()

def add_contract_coverage(session: Session, contract_id: str, category: str) -> None:
    contract = session.get(Contract, contract_id)
    if category not in contract.covered_categories:
        contract.covered_categories = [*contract.covered_categories, category]
        session.flush()
```
All three raise naturally (`AttributeError` on `None`) if the id doesn't exist; the consolidation task only ever calls these with ids already validated at resolve time (decision 4), so this is not expected to fire in practice, matching this codebase's existing style of trusting internally-validated input rather than re-checking it.

### `app/graph/service.py` additions

```python
def sync_sku(session: Session, client: GraphClient, ns: str, sku_id: str) -> None:
    sku = get_sku(session, sku_id)
    if sku is None:
        return
    merge_nodes(client, ns, "SKU", [{"id": sku.sku_id, "props": {
        "name": sku.name, "category": sku.category, "list_price": sku.list_price,
        "discontinued": sku.discontinued, "in_stock": sku.in_stock,
    }}])

def sync_requirement(session: Session, client: GraphClient, ns: str, sku_id: str, required_sku_id: str) -> None:
    merge_edges(client, ns, "REQUIRES", "SKU", "SKU", [_edge(sku_id, required_sku_id)])

def sync_contract_coverage(session: Session, client: GraphClient, ns: str, contract_id: str, category: str) -> None:
    merge_nodes(client, ns, "PricingCategory", [{"id": category, "props": {}}])
    merge_edges(client, ns, "COVERS", "Contract", "PricingCategory", [_edge(contract_id, category)])
```
`sync_requirement`/`sync_contract_coverage` also take the `reference_fingerprint` the handler read before its Postgres write. They raise `GraphSyncIncomplete` (a `GraphError`, so `sync_best_effort` logs it) when the edge's endpoint node is missing, and then compare-and-set `GraphMeta`: the post-correction fingerprint is stamped only while the stored one still equals the pre-write value, so a graph already stale (an earlier failed sync, a rebuild mid-load with no `GraphMeta`) stays stale until a rebuild. `rebuild_reference_graph` reads the fingerprint it stamps before reading any reference row, so a correction committed mid-rebuild leaves the graph stale rather than current.

`sync_sku` mirrors the existing `SKU` merge shape inside `rebuild_reference_graph`, scoped to one node. `sync_requirement`/`sync_contract_coverage` reuse the existing `merge_edges`/`_edge` helpers already in this file, no new merge logic. `sync_contract_coverage` merges the `PricingCategory` node first since the category may be brand new (a contract can cover a category no SKU uses yet, same reasoning `rebuild_reference_graph` already documents for its own category-node merge).

### `backend/scripts/run_worker.py`

```python
from app.consolidation.tasks import run_worker
# `python scripts/run_worker.py` from backend/ runs the worker; run_worker() opens the app async on a
# SelectorEventLoop, since psycopg's async pool cannot run on Windows' default Proactor loop.
```
Not started by the test suite or by any other script; a manually-run background process, same operational category as the FastAPI server itself.

### `scripts/calibrate_judge.py` changes

- loads `judge_golden_set.json` cases as today, **and** all `EvalCaseRow` rows from Postgres, concatenated before scoring.
- after computing `result` via `calibrate(...)`, also computes `false_auto_send_rate` at `result.threshold`: `calibration.py`'s `CalibrationResult` dataclass gains a `pairs: list[tuple[bool, bool]]` field, populated by `calibrate()` from its winning candidate's sweep; a new pure function `false_auto_send_rate(pairs: list[tuple[bool, bool]]) -> float` returns `sum(1 for trust, human in pairs if trust and not human) / len(pairs)`.
- new constant `FALSE_AUTO_SEND_CEILING = 0.05` in `app/judge/constant.py`.
- if `false_auto_send_rate > FALSE_AUTO_SEND_CEILING`: prints which cases would auto-send wrongly (case_id, score, label) and exits 1 **without** writing `calibration.json`. This is the release gate: a threshold that clears kappa but breaches the ceiling is not released.
- `calibration.json`'s written payload gains `false_auto_send_rate` and `eval_case_count` alongside the existing fields, so the artifact records what it was gated on.

### `core/tracing/langfuse_client.py` (new)

```python
class TraceHandle:
    def span(self, name: str, **metadata) -> "TraceHandle": ...   # context manager, no-ops if client is None
    def update(self, **metadata) -> None: ...

class TracingClient:
    def __init__(self, client: Langfuse | None): ...
    def trace(self, name: str, **metadata) -> TraceHandle: ...    # context manager
```
Construction: `TracingClient(Langfuse(public_key=..., secret_key=..., host=...) if settings.langfuse_public_key else None)`, built once per process (FastAPI app startup, scripts' `main()`), passed down like `AnthropicJudgeClient`.

Instrumentation points (one trace per run, child spans within it):
- `app/estimate/service.py`: trace opened at the top of the agent-loop entry point, tagged `estimate_id`, `quote_request_id`; each tool call inside the LangGraph loop opens a child span (tool name, arguments, result summary — no full prompt/response bodies, to keep spans small).
- `app/dedupe/service.py`: child span per verdict decision (verdict, both fingerprints compared, candidate id).
- `app/graph/reader.py`: child span per guardrail-time read (`sku_chain`, `required_parts`, `contract_coverage`) during a single estimate run — passed the same `TracingClient`/current trace context the estimate service already holds, not opened independently.

### Config / dependencies

`core/config/settings.py`: `langfuse_public_key: str | None = None`, `langfuse_secret_key: str | None = None`, `langfuse_host: str | None = None`.
`.env.example`: commented `LANGFUSE_PUBLIC_KEY=`, `LANGFUSE_SECRET_KEY=`, `LANGFUSE_HOST=http://localhost:3000`.
`pyproject.toml` dependencies: `procrastinate`, `langfuse`.

### Migration 0006

- `alembic revision` altering `review_items` (3 new nullable columns) and creating `eval_cases`.
- procrastinate's own schema lives in its own revision, 0007: it executes the `schema.sql` packaged with the installed procrastinate (the SQL `procrastinate schema --apply` runs) through the driver cursor, and its downgrade drops every procrastinate table, function and type.
- `migrations/env.py`: register `app.judge` (already registered from Phase 5, `EvalCaseRow` lives in the same module so no new import needed) and `app.consolidation` if it defines any SQLAlchemy models beyond procrastinate's own tables (it doesn't, per this design — no entry needed, but verified during implementation since Phase 5's own gap was exactly this kind of miss).

## Testing

- TDD per task.
- `resolve_review_item`: approve path (eval case created, `label='trust'`, no task enqueued), correct path per dimension (eval case `label='escalate'`, task enqueued), already-resolved rejection, invalid-correction rejection for each of the three dimension-specific shapes (unknown SKU, unknown required SKU, mismatched contract id), unrecognized-dimension rejection.
- `consolidate_review_item`: called directly as a function (no worker process), one test per handler:
  - `price_provenance`: seeded `review_item` with a price correction; asserts `Sku.list_price` updated, `sync_sku` called (fake `GraphClient`), review item `status == 'consolidated'`.
  - `graph_completion`: seeded `review_item` naming a `required_sku_id`; asserts a new `SkuRequirement` row exists, `sync_requirement` called, idempotent on a second run (no duplicate row, no error).
  - `contract_discount`: seeded `review_item` naming a `category`; asserts the category is appended to `Contract.covered_categories`, `sync_contract_coverage` called, idempotent when the category is already covered.
- **Acceptance tests (the literal done-when, one per handler)**: for each of the three, the same before/after shape — run the relevant guardrail check (`check_price_provenance`, `check_graph_integrity`, `check_contract_discount`) on a scenario and confirm it currently fails or requires the uncorrected form; create and resolve the matching review item; run `consolidate_review_item` inline; re-run the same guardrail check on a fresh identical scenario and assert it now passes with zero violations. The roadmap's own example (predicted price) is the `price_provenance` case; the other two prove the same mechanism generalizes.
- `calibrate_judge.py`'s ceiling check: scripted-fake Anthropic client, golden set + injected `eval_cases` fixtures engineered to cross the ceiling in one test and stay under it in another; asserts `calibration.json` is/isn't written accordingly.
- `TracingClient`: fake `Langfuse`-shaped double asserting span open/close/tag calls; a `None`-client test asserting every call is a true no-op (no attribute access that would raise `AttributeError` on `None`).
- No real Anthropic, OpenAI, or Langfuse network calls anywhere in the test suite.

## Deferred gaps (documented at phase close, not silently dropped)

- `contract_discount` correction only covers a missing-category data gap (`covered_categories`); correcting the discount *percentage* itself (a real policy change, not a data-entry fix) has no handler this phase.
- Live production false-auto-send monitoring (flag a previously-trusted estimate wrong after the fact): needs a mechanism Phase 7's UI doesn't yet exist to drive.
- Real Langfuse connection: SDK is integrated and tested against a fake client; no real instance (self-hosted or cloud) is connected without your separate approval.
- Real `--yes` run of `calibrate_judge.py` against the live Anthropic API: still blocked on the same missing API key as Phases 4-5.
