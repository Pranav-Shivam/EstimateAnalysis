# Phase 6 Design: LLMOps and Tracing

Date: 2026-09-29. Roadmap: `docs/roadmap.md` Phase 6. Research: `docs/research/llm-judge-calibration.md` (Cohen's kappa / threshold-selection method, reused for the release gate). ADRs in force: 0003 (procrastinate + cachetools, no Redis). Builds on Phase 5's `judge_verdicts`/`review_items`, Phase 4's `GraphReader`/graph service, Phase 3's estimate/pricing.

## Goal

Close the "memory that compounds" loop: a human correcting a judge-flagged estimate should mean the same mistake is never repeated. Concretely, a reviewer resolving a `price_provenance` review item with a corrected price writes that price into Postgres as a permanent fact; the next estimate for that SKU reads the real price instead of predicting one, so the judge trusts it and no review item is created. Every resolution (approved or corrected) also grows a real eval set from production data, not just Phase 5's hand-authored golden set, and a release gate blocks writing a new calibrated threshold if it would push the false-auto-send rate on that eval set above an acceptable ceiling. Langfuse traces every run, tool call, graph hop, and dedupe decision, wired to the real SDK but safe to run with no Langfuse instance configured.

Done when: a planted correction (simulating a human fixing a predicted price) results in a new permanent fact (`Sku.list_price`), and a subsequent identical scenario's `price_provenance` check passes without producing a review item, as a single acceptance test.

## Scope

In:
- Migration 0006: `review_items` gains `outcome`, `correction`, `resolved_at`; new `eval_cases` table; procrastinate's own schema.
- `POST /v1/review/{review_item_id}/resolve`: records approve/correct, builds an eval case, enqueues consolidation on correct.
- `app/consolidation/`: procrastinate task, `price_provenance` correction handler (writes `Sku.list_price`, best-effort graph sync of that one node).
- `backend/scripts/run_worker.py`: procrastinate worker entrypoint.
- `app/judge/models.py`: `EvalCaseRow`. `scripts/calibrate_judge.py`: reads golden set + `eval_cases` together, computes false-auto-send rate at the swept threshold, refuses to write `calibration.json` if the rate exceeds a ceiling constant.
- `core/tracing/langfuse_client.py`: thin wrapper, no-ops when unconfigured. Instrumentation in the estimate agent loop, dedupe service, and graph reader's guardrail-time reads.
- `app/graph/service.py`: `sync_sku` (single-node best-effort sync, same pattern as existing `sync_quote`/`sync_quote_request`).
- `.env.example`: commented-out `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST`.
- `pyproject.toml`: `procrastinate`, `langfuse` dependencies.

Out (deferred, documented as gaps at phase close):
- `graph_completion` (missing required part) correction handler — same shape as `price_provenance`, no new mechanism needed, just not built this phase (see brainstorming scope decision).
- `contract_discount` correction handler — contract terms aren't naturally "corrected" per-quote; out of scope.
- Live production false-auto-send tracking (flagging a previously auto-sent estimate as wrong after the fact) — the release gate reads the golden set + `eval_cases` only, not production `judge_verdicts` traffic.
- Self-hosted or cloud Langfuse actually receiving real traces — the SDK integration is real and testable against a fake client; connecting it to a live Langfuse instance needs your separate go-ahead, same as any other hosted-service call.
- Phase 7's review queue UI (this phase only builds the endpoint it will call).
- Re-judging superseding logic (Phase 5's carried-forward gap; unrelated to this phase).

## Decisions (agreed during brainstorming)

1. **Correction capture is new backend surface, not deferred to Phase 7.** `review_items.status='open'` only tracked existence, not resolution. Phase 6's own done-when requires planting a correction, so `POST /v1/review/{id}/resolve` is built now; Phase 7's UI calls it later, it doesn't invent it.
2. **Consolidation target for `price_provenance` is `Sku.list_price`, not a separate "corrected price" table.** Read from `check_price_provenance`/`_provenance_problem` (`backend/app/estimate/guardrails.py`): a line is scored `predicted` only when `sku.list_price is None`. Writing the corrected value into `Sku.list_price` is the only change that makes a *future* line for that SKU eligible for `price_source == "list"` and skip prediction entirely — a vector/semantic-only fact would not, because the guardrail reads `Sku.list_price` directly, never a vector store. This also lands as a **graph edge/property** for free: `rebuild_reference_graph` already projects `s.list_price` onto the SKU node.
3. **Single consolidation handler this phase: `price_provenance`.** Matches the roadmap's literal example. `graph_completion` would follow an identical shape (write a `Requirement` row instead of `Sku.list_price`) but isn't built now, to keep this phase thin; documented as a deferred gap, not silently dropped.
4. **Correction shape is read back from the review item's own evidence, not caller-supplied free text.** `{"outcome": "corrected", "correction": {"sku_id": "...", "corrected_unit_price": 42.50}}`, and the service validates `sku_id` is one of the SKUs actually named in that review item's stored `evidence`. Prevents a resolve call from "correcting" a SKU the judge never flagged.
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
- loads the row (404-equivalent `ReviewItemNotFound` if missing, `status != 'open'` raises `ReviewItemAlreadyResolved`)
- if `outcome == "corrected"`: validates `correction["sku_id"]` appears in `row.evidence["lines"]`; anything else raises `InvalidCorrection`
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
  app = App(connector=...)  # PsycopgConnector, built from settings.database_url in the entrypoint

  @app.task(name="consolidate_review_item")
  def consolidate_review_item(review_item_id: str) -> None: ...
  ```
  Loads the `ReviewItemRow` (must be `status == "corrected"`), dispatches on `dimension`:
  - `"price_provenance"` → `consolidate_price_correction(session, sku_id, corrected_unit_price)`: `session.get(Sku, sku_id)`, sets `list_price = corrected_unit_price`, flush, commit.
  - anything else → `logger.warning("no consolidation handler for dimension %s", dimension)`, no-op (matches decision 3).
  - best-effort graph sync: `sync_best_effort("sku price correction", sync_sku, session, client, ns, sku_id)` (existing `sync_best_effort` wrapper from `app/graph/service.py`, reused as-is).
  - marks the review item `status = "consolidated"`, commits.
- Task is a plain function; tests call `consolidate_review_item(review_item_id=...)` directly against a session fixture rather than requiring a running worker (procrastinate tasks are ordinary callables when not `.defer()`-dispatched through a live app/worker).

### `app/graph/service.py` addition

```python
def sync_sku(session: Session, client: GraphClient, ns: str, sku_id: str) -> None:
    sku = get_sku(session, sku_id)
    if sku is None:
        return
    merge_nodes(client, ns, "SKU", [{"id": sku.sku_id, "props": {
        "name": sku.name, "category": sku.category, "list_price": sku.list_price,
        "discontinued": sku.discontinued, "in_stock": sku.in_stock,
    }}])
```
Mirrors the existing `SKU` merge shape inside `rebuild_reference_graph`, scoped to one node.

### `backend/scripts/run_worker.py`

```python
from app.consolidation.tasks import app as procrastinate_app
# procrastinate CLI entrypoint: `python run_worker.py` runs `procrastinate_app.run_worker()`
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
- procrastinate's own schema, applied via its documented `procrastinate schema --apply` SQL, folded into the same migration file (or an immediately-preceding one if procrastinate's tooling requires running its SQL outside alembic's `op.execute` — confirmed during implementation, not assumed here).
- `migrations/env.py`: register `app.judge` (already registered from Phase 5, `EvalCaseRow` lives in the same module so no new import needed) and `app.consolidation` if it defines any SQLAlchemy models beyond procrastinate's own tables (it doesn't, per this design — no entry needed, but verified during implementation since Phase 5's own gap was exactly this kind of miss).

## Testing

- TDD per task.
- `resolve_review_item`: approve path (eval case created, `label='trust'`, no task enqueued), correct path (eval case `label='escalate'`, task enqueued), already-resolved rejection, unknown-SKU-in-correction rejection.
- `consolidate_review_item`: called directly as a function (no worker process) against a seeded `review_item` with a `price_provenance` correction; asserts `Sku.list_price` updated, graph `sync_sku` called (fake `GraphClient`), review item `status == 'consolidated'`.
- **Acceptance test (the literal done-when)**: seed a SKU with `list_price = None` (predicted-price-eligible), build a draft line priced via `predict_price_for_sku`, run `check_price_provenance` and confirm it currently requires `price_source == "predicted"`; create and resolve a review item correcting that SKU's price; run `consolidate_review_item` inline; build a fresh identical draft line for the same SKU and assert `check_price_provenance` now requires (and accepts) `price_source == "list"` matching the corrected value, with zero violations — i.e., the same scenario that produced a review item before consolidation produces none after.
- `calibrate_judge.py`'s ceiling check: scripted-fake Anthropic client, golden set + injected `eval_cases` fixtures engineered to cross the ceiling in one test and stay under it in another; asserts `calibration.json` is/isn't written accordingly.
- `TracingClient`: fake `Langfuse`-shaped double asserting span open/close/tag calls; a `None`-client test asserting every call is a true no-op (no attribute access that would raise `AttributeError` on `None`).
- No real Anthropic, OpenAI, or Langfuse network calls anywhere in the test suite.

## Deferred gaps (documented at phase close, not silently dropped)

- `graph_completion` and `contract_discount` consolidation handlers: same shape as `price_provenance`, not built this phase.
- Live production false-auto-send monitoring (flag a previously-trusted estimate wrong after the fact): needs a mechanism Phase 7's UI doesn't yet exist to drive.
- Real Langfuse connection: SDK is integrated and tested against a fake client; no real instance (self-hosted or cloud) is connected without your separate approval.
- Real `--yes` run of `calibrate_judge.py` against the live Anthropic API: still blocked on the same missing API key as Phases 4-5.
