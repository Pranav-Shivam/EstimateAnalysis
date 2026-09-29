# Phase 5 Design: LLM-as-Judge Eval and Human Review Workflow

Date: 2026-09-29. Roadmap: `docs/roadmap.md` Phase 5. Research: `docs/research/llm-judge-calibration.md` (updated 2026-09-29 with the "Trust or Escalate" threshold-selection method), `docs/research/graphrag-vs-vector-rag.md` (no new findings needed there; graph evidence shape was already settled in Phase 4). ADRs in force: 0004 (cross-vendor judge). Builds on Phase 3's `EstimateResult`/guardrails and Phase 4's `GraphReader`.

## Goal

Every `ready` estimate draft gets a second, cross-vendor opinion before it can be trusted: an Anthropic Claude Haiku judge scores it against the same price book, contract, and graph evidence the agent and guardrails used, not a bare text critique. The judge's confidence threshold is derived from a hand-labeled golden set via Cohen's kappa, not copied from the source article's 0.85. A draft below threshold produces a review item naming one specific fact to check, not the whole quote.

Done when: running the (scripted, fake-client) judge over the hand-labeled golden set at the calibrated threshold correctly separates the seeded low-confidence cases (thin-evidence predicted price, near-expiry contract discount) from the clean ones, matching the golden set's own human labels.

## Scope

In:
- `app/judge/` module: evidence assembly, scoring/rollup logic, persistence, service, route.
- `core/llm/anthropic_judge_client.py`: cross-vendor judge client.
- Golden set data file, hand-labeled.
- `scripts/calibrate_judge.py`: dry-run-by-default calibration script, derives and persists the confidence threshold.
- `POST /v1/judge/{estimate_id}`, `GET /v1/review` endpoints.
- Migration `0005`: `judge_verdicts`, `review_items` tables.

Out (later phases): Langfuse tracing, the consolidation job that writes corrections back as graph edges/facts (Phase 6), the review queue UI (Phase 7), running the real agent over the 60 real emails to produce real `ready` drafts to judge live (carried-forward gap from Phases 3-4; still needs a live-OpenAI-run approval this phase does not grant).

## Decisions (agreed during brainstorming)

1. **Judge runs as a separate endpoint, not baked into the estimate route.** `POST /v1/judge/{estimate_id}` scores an already-persisted `EstimateDraftRow` of any status. Keeps two independently-failing external LLM calls (agent, judge) out of one request/response cycle, and lets tests call the judge without re-running the agent.
2. **Golden set is hand-labeled synthetic cases, not derived from `scenario_cases.json`.** The 3 planted-mistake scenario types (discontinued swap, missing required part, discount-category mismatch) are already blocked by Phase 4's `graph_integrity` and Phase 3's `contract_discount` guardrails before a draft ever reaches `ready`, so they would never reach the judge in practice and give it nothing to prove itself on. The golden set instead covers the class of problem code guardrails cannot structurally catch: a mathematically-consistent but evidentially-thin predicted price, a discount that matches the contract exactly but the contract expires in days, and their clean counterparts.
3. **Judge output is 3 scored dimensions plus a rollup, not one opaque score.** `price_provenance`, `contract_discount`, `graph_completion`, each 0-1 with a rationale and an evidence dict. `overall_confidence = min(dimension scores)`: the weakest dimension sets the ceiling, so one bad fact cannot be diluted by two good ones. `flagged_dimension` is the argmin (alphabetical tiebreak on an exact tie, since a real tie across 3 independent dimensions is not expected but must resolve deterministically for the review payload to be stable).
4. **`needs_review` drafts short-circuit the judge with zero LLM calls.** A draft code guardrails already rejected does not need a second opinion to know it needs one; the judge returns `trusted=False`, `flagged_dimension="guardrail"`, and a review item built directly from the guardrail's own `reason`/`violations`. Only `ready` drafts are actually scored by the LLM.
5. **Real Anthropic calls are dry-run-gated, same pattern as Phase 4's `embed_skus.py`/`summarize_communities.py`.** `scripts/calibrate_judge.py` prints case count and a token estimate and only calls the real API with `--yes`. The test suite uses a scripted fake judge client throughout: zero real calls in CI. The judge API route also takes a real `AnthropicJudgeClient`, but it is not invoked against the real API this phase without separate approval, consistent with the live-agent gap already carried from Phases 3-4.
6. **Threshold derivation follows the "Trust or Escalate" method** (`docs/research/llm-judge-calibration.md`): sweep candidate thresholds over the judge's `overall_confidence` on the golden set, compute Cohen's kappa at each threshold between (judge trusts vs. escalates) and the golden set's human labels, and pick the lowest threshold whose kappa still clears the acceptable band (>0.6, per the Future AGI research already on file). If no threshold clears 0.6, the script reports the best kappa found and refuses to write a threshold, per the research's own guidance that a low kappa means fix the rubric, not silently ship a bad cutoff.
7. **Review payload persists as a new table, not just an inline API field.** `ReviewItem` rows seed the `GET /v1/review` list, which Phase 7's queue UI will read directly. A verdict below threshold always produces exactly one open `ReviewItem`.

Decisions made without a question (constraints already set, or forced by the design):
- Judge model is a named constant, `claude-haiku-4-5-20251001` (current Claude Haiku, per ADR-0004; the ADR's own text says "currently" since the specific model changes).
- Evidence dimensions map exactly to the roadmap's own wording ("price book / contract / graph evidence path"): 3 dimensions, not more. No sentiment/tone/formatting dimension; that is not what ADR-0004 asked the judge to check.
- Golden set cases embed their own literal evidence bundle (not a live DB/graph lookup at calibration time). This decouples calibration from the real dataset's specific SKUs, contracts, and dates, so the golden set stays valid across data regenerations.
- The golden set's size target is ~30-40 cases, smaller than Galileo's 50-200: POC scale, single annotator (documented as a limitation, not hidden).
- No auth on the new routes, consistent with the rest of the POC.

## Architecture

Layer order follows `docs/backend-structure.txt`: route, service, repository, DB/LLM.

### New module `app/judge/`

- `models.py`: `JudgeVerdictRow` (`estimate_id` FK, `model`, `dimensions` JSONB, `overall_confidence`, `flagged_dimension`, `trusted`, `created_at`), `ReviewItemRow` (`id`, `judge_verdict_id` FK, `estimate_id` FK, `dimension`, `fact`, `evidence` JSONB, `line_index` nullable, `status` default `"open"`, `created_at`).
- `schemas.py`:
  - `DimensionScore(name: Literal["price_provenance", "contract_discount", "graph_completion"], score: float, rationale: str, evidence: dict)`
  - `JudgeVerdict(estimate_id, model, dimensions: list[DimensionScore], overall_confidence: float, flagged_dimension: str, trusted: bool)`
  - `ReviewItem(id, estimate_id, dimension, fact: str, evidence: dict, line_index: int | None, status: Literal["open", "resolved"])`
- `constant.py`: `JUDGE_MODEL = "claude-haiku-4-5-20251001"`, `DEFAULT_CONFIDENCE_THRESHOLD` (a conservative placeholder, e.g. `0.8`, used until `data/judge_calibration.json` exists), `KAPPA_ACCEPTABLE = 0.6`.
- `evidence.py`: `build_evidence(session, graph, draft, as_of) -> list[LineEvidence]`. Per line: price evidence (`get_sku`, `predict_price_for_sku` when predicted: `peer_count`, `low`, `high`), contract evidence (`GraphReader.contract_coverage`: `covered`, `active_on_as_of`, `effective_to`, days-to-expiry), graph evidence (`GraphReader.sku_chain`, `required_parts`: chain length, live end, required-parts presence). Pure function of already-existing repository/reader calls; no new data source.
- `scoring.py`: pure functions, no I/O.
  - `rollup(dimensions: list[DimensionScore]) -> tuple[float, str]`: `(min(d.score for d in dimensions), argmin name, alphabetical tiebreak)`.
  - `gate(overall_confidence: float, threshold: float) -> bool` (trusted or not).
  - `flag_reason(dimensions, flagged_dimension) -> DimensionScore`: picks the one dimension the review payload reports.
- `prompts.py`: judge system prompt. States the 3 dimensions, asks for a score 0-1 and one-sentence rationale per dimension, grounded only in the evidence bundle given (no outside knowledge, no re-deriving prices).
- `service.py`:
  - `run_judge(session, graph, as_of, estimate_id, llm_client) -> JudgeRunResult`. Loads the `EstimateDraftRow`. If `status == "needs_review"`: build the fast-path verdict from the row's own `reason`/`violations`, skip the LLM. If `status == "ready"`: `build_evidence`, call `llm_client.score(evidence, prompts)`, validate the 3 dimensions came back, `rollup`, `gate` against the loaded threshold (from `data/judge_calibration.json` if present, else `DEFAULT_CONFIDENCE_THRESHOLD`), persist verdict, and if not trusted, persist exactly one `ReviewItem`.
- `repository.py`: `save_judge_verdict`, `save_review_item`, `get_judge_verdict`, `list_open_review_items`.

### Cross-vendor client

`core/llm/anthropic_judge_client.py`:
- `AnthropicJudgeClient(client: anthropic.Anthropic | None = None)`, same injection/wrapping discipline as `openai_summary_client.py`.
- `score(evidence: list[LineEvidence], system_prompt: str) -> RawJudgeScore` (3 named dimension scores + rationales, as JSON via the Anthropic tool-use/structured-output path, mirroring how `OpenAIAgentClient` parses tool-call arguments).
- Malformed response (missing a dimension, non-numeric score, score outside `[0, 1]`), empty response, or API failure all become a typed `JudgeError`, never raised past the client boundary uncaught, never silently defaulting to a passing score.

### Golden set

`data/judge_golden_set.json`: list of ~30-40 cases. Each case:
```
{
  "case_id": "jg-0001",
  "label": "trust" | "escalate",
  "rationale": "<why this label, one sentence, human-authored>",
  "estimate_status": "ready" | "needs_review",
  "evidence": [ { <one LineEvidence dict per line, literal> } ],
  "guardrail_reason": "<only when estimate_status is needs_review>"
}
```
Coverage (indicative counts, exact split decided during implementation once cases are actually written):
- Clean, list-priced, fully covered, complete required parts: `trust`.
- Predicted price, `peer_count` near the Phase 3 `PEER_MIN` floor, wide `low`/`high` spread: `escalate`.
- Predicted price, many peers, tight `low`/`high` spread: `trust` (tests the judge distinguishes thin vs. strong evidence, not "predicted implies bad").
- Discount exact-match, contract well within its window: `trust`.
- Discount exact-match, contract `effective_to` within days of `as_of`: `escalate`.
- A couple of `needs_review` cases: `escalate` (fast-path correctness check, not a real LLM scoring case).

A small `scripts/validate_judge_golden_set.py` (or a test, decided during planning) checks: every case has both labels represented, every `ready` case has all 3 evidence dimensions present, every `needs_review` case has a `guardrail_reason`.

### Calibration

`scripts/calibrate_judge.py`:
- Loads the golden set. Default (no `--yes`): prints case count, estimated token spend, exits.
- `--yes`: calls the real `AnthropicJudgeClient` once per `ready` case (fast-path cases are not scored, their label is asserted directly), collects `overall_confidence` per case, sweeps thresholds, computes kappa at each per Decision 6, writes `data/judge_calibration.json` (`threshold`, `kappa`, `golden_set_size`, `computed_at`) on success, or prints the best kappa found and exits non-zero without writing on failure to clear 0.6.

### API

- `POST /v1/judge/{estimate_id}` → `run_judge`. 404 unknown estimate. 502 on `JudgeError` (mirrors the 502 pattern for `AgentError`). Response: the persisted `JudgeVerdict` plus the `ReviewItem` when one was created.
- `GET /v1/review` → `list_open_review_items`. No filtering/pagination this phase (POC scale); Phase 7 can add it when the UI needs it.

## Error handling

- `JudgeError` maps to 502 at the route, same as `AgentError`.
- A `GraphError` raised while building evidence for a `ready` draft (graph went down between estimate creation and judge call) maps to 503, same as the rest of the graph-backed surface.
- Fast-path (`needs_review`) never touches the LLM or the graph, so it cannot fail on either.

## Testing

- No real Anthropic (or OpenAI) API call anywhere in the suite. `AnthropicJudgeClient` is always a scripted fake in tests.
- Real Postgres on port 5433 with the existing rollback fixture. No test asserts an absolute row count; tests check only ids they create.
- Coverage:
  - `evidence.py`: each of the 3 dimensions' evidence assembled correctly from seeded rows (predicted vs. list price, covered/uncovered/expired contract, complete/incomplete required parts, discontinued chain).
  - `scoring.py`: rollup picks the minimum, alphabetical tiebreak on an exact tie, gate at threshold boundary (at, just above, just below).
  - `service.py`: fast-path for `needs_review` (zero client calls, verdict built from the row's own reason), `ready` path calls the client once, a verdict at/above threshold creates no `ReviewItem`, below threshold creates exactly one naming the flagged dimension, malformed client response surfaces as `JudgeError` and nothing is persisted.
  - `anthropic_judge_client.py`: malformed dimension, out-of-range score, empty response, API exception all become `JudgeError`.
  - `calibrate_judge.py`: threshold-sweep/kappa logic is a pure function, tested directly against a small fixed labeled+scored dataset (no client, no `--yes`, no real case data) covering: a threshold that clears 0.6, and a dataset where none does.
  - API: `POST /v1/judge/{id}` 404, verdict persisted, `ReviewItem` created only below threshold; `GET /v1/review` lists only open items.
  - Acceptance: the scripted fake judge scores the actual golden set cases (client returns each case's pre-scripted dimension scores, not real model output) and, at the calibrated threshold from a committed `data/judge_calibration.json` fixture, the resulting trust/escalate split matches every case's own `label`. This is what proves the roadmap's done-when criterion without a live paid call in CI; the real threshold used in the running service still comes from the actual `--yes` calibration run against real Claude Haiku, done separately with your approval.

## Cost gates

- Postgres is local: free.
- Calibration run (`scripts/calibrate_judge.py --yes`): one real Claude Haiku call per `ready` golden-set case (~25-30 calls, Haiku pricing). Dry run by default, reports the estimate first, requires your explicit `--yes` and prior approval before I run it for real.
- No live judge calls against real agent-produced drafts this phase (there are none yet; that still needs the Phase 3/4 live-agent-run approval).

## Risks

- The golden set is single-annotator (me), not the 2-3-annotator setup the Galileo methodology recommends; documented as a POC-scale limitation, not hidden. A kappa computed against one annotator's labels measures judge-vs-me agreement, not judge-vs-consensus-human agreement.
- If the real calibration run's kappa does not clear 0.6, the rubric (prompt, dimension definitions, or evidence given to the judge) needs revision before a threshold can be trusted; the script is designed to refuse to write a threshold in that case rather than ship a number that failed its own check.
- The golden set's evidence bundles are hand-authored, not drawn from the live graph/DB; if the real schema's evidence shape drifts (a field renamed in `ContractCoverage` or `SkuChain`, for instance) the golden set could silently stop matching what `evidence.py` actually produces. Mitigated by the golden-set validation check and by `evidence.py`'s own unit tests using the real schemas.

## Known gaps carried in

- No real `ready` drafts exist yet to judge in production (Phase 3/4's live-agent-run gap); this phase's acceptance is against the golden set, not real agent output.
- `GET /v1/review` has no pagination or filtering; fine at POC scale, a Phase 7 concern once the UI exists.
- Required-part *quantity* is still not checked anywhere (carried from Phase 4), so `graph_completion` evidence is presence-only, same limitation.
