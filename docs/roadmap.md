# Roadmap

Phase breakdown for building the quote estimation agent from scratch, per `README.md` and the 4 ADRs in `docs/adr/`. This is the decomposition level, not the implementation level: each phase below gets its own written spec and then its own bite-sized TDD plan (via the `writing-plans` skill) before any code is written for it. Phases 0 to 7 are built and merged to `master`; each phase's Status line records what shipped.

Built for a 2-4 week timeline aimed at a FAANG Applied AI Engineer POC, so depth is weighted toward the phases that differentiate this from a plain RAG demo: the knowledge graph, the dedupe agent, and the eval gate.

## Phase 0: Foundations (done)

What: problem statement, architecture, tech stack, 4 locked ADRs, research notes, gotchas log, checklist.
Depends on: nothing.
Done when: `README.md`, `docs/adr/`, `docs/research/`, `docs/gotchas.md`, `docs/checklist.md` all exist and agree with each other.
Status: complete, committed.

## Phase 1: Synthetic data generation

What: `catalog_gen.py` (500-800 SKUs, product families, pricing categories, discontinued/`REPLACED_BY` and `REQUIRES` relationships), `customer_gen.py` (100-150 customers, contracts, contacts, projects/sites), `graph_export.py` (Neo4j-loadable nodes/edges matching the 15-edge-type schema), `scenario_gen.py` (LLM-generated messy quote emails with a hidden ground-truth label per scenario type: discontinued swap, missing required part, discount-category mismatch, duplicate pair, revision pair, clean distinct request), `validate.py` (referential integrity + scenario coverage checks).
Depends on: nothing else; this is the foundation every other phase reads from.
Done when: `validate.py` passes on a generated dataset, and a manual spot-check of 10-15 generated emails reads as realistic, not templated.
Why first: every other phase needs data to reason over; without it nothing downstream is testable, only theoretical.

## Phase 2: Intake and dedupe

What: email/attachment to structured `QuoteRequest` JSON (intake), the dedupe agent (blocking on site/zip/account, graph-relationship matching, the two-fingerprint key/value classifier from the source article).
Depends on: Phase 1's synthetic customers, contacts, and scenario emails (especially the duplicate/revision pairs) to test against.
Done when: the dedupe classifier correctly labels the Phase 1 scenario set (duplicate pairs as `DUPLICATE_OF`, revision pairs as `REVISION_OF`, distinct requests as `DISTINCT`) against its known ground truth.
Why second: cheapest payback per the article ("removes waste without changing how reps price"), and doesn't need the graph or the agent loop to exist yet.

## Phase 3: Agent and pricing tools

What: LangGraph agent loop, tool set (CRM/customer lookup, price book search, stock check, price prediction for SKUs with no history), code-level guardrails (contract discount enforcement, required-field completeness).
Depends on: Phase 1's catalog/customer/contract data; Phase 2's structured `QuoteRequest` as the agent's input.
Done when: the agent produces a priced draft estimate for a Phase 1 scenario email, with guardrails provably blocking at least one deliberately-planted bad discount case.
Why third: this is the core "does it actually price things right" loop; evals and the graph make it trustworthy, but the loop has to exist first for them to have something to check.
Status: complete (see docs/superpowers/specs/2026-09-28-phase3-agent-pricing-design.md).

## Phase 4: Knowledge graph

What: Neo4j schema (10 node types, 15 edge types per the article), entity/relationship extraction from Phase 1's catalog/customer/contract data, Leiden community detection via GDS, local (fan-out) and global (community-summary) query modes, the hybrid retrieval router deciding vector vs. SQL vs. graph per question.
Depends on: Phase 1's data to build the graph from; Phase 3's agent to actually call it as a tool.
Done when: the agent (Phase 3) correctly resolves at least the three planted mistake types from Phase 1's scenarios (discontinued-SKU swap, missing required part, wrong-category discount) by traversing the graph, not by guessing from text.
Why fourth, not first: per the article and `docs/research/graphrag-vs-vector-rag.md`, the graph is the most expensive piece to keep correct and only pays off once there's an agent loop and real scenarios to justify it. Building it before Phase 3 would mean building relationships with nothing yet consuming them.
Status: complete (see docs/superpowers/specs/2026-09-28-phase4-knowledge-graph-design.md). The full 10 node and 15 edge schema is built from Postgres as a rebuildable projection; Leiden, local and global modes, LLM community summaries (cached, cost-gated), the pgvector arm and the rule-based router are in. Embeddings (650 SKUs) and community summaries (56 communities) were generated against the real data on 2026-09-30 with `OPENAI_API_KEY` (about 20k tokens in total) and are stored in `backend/data/llm_snapshot.json.gz`, so another machine restores them instead of paying again.

## Phase 5: Evals and review workflow

What: LLM-as-judge (cross-vendor per ADR-0004), scoring against price book/contract/graph evidence path, a calibrated confidence threshold (per `docs/research/llm-judge-calibration.md`: build a golden set from labeled corrections, derive the threshold from Cohen's kappa against it, not a copied 0.85), the human review payload (one flagged fact to check, not the whole quote).
Depends on: Phase 3's agent output and Phase 4's graph evidence paths to score against.
Done when: the judge correctly flags the Phase 1 scenarios seeded as low-confidence (e.g. a SKU price that was predicted, not looked up) and passes the clean ones, measured against the scenario set's known ground truth.
Why fifth: needs something real to judge; building the judge before the agent and graph exist would mean scoring against nothing.
Status: complete (see docs/superpowers/specs/2026-09-29-phase5-judge-review-design.md). Cross-vendor judge (Claude Haiku scoring GPT-4o drafts) scores 3 dimensions rolled up by minimum, gated on a threshold calibrated from a 32-case hand-labeled golden set via Cohen's kappa (threshold 0.85, kappa 1.0). A `needs_review` draft short-circuits the judge at zero cost. The real `--yes` calibration against live Claude Haiku ran on 2026-09-30. It first failed the 5% false-auto-send release gate (10.3%: a 4-peer predicted price and contracts expiring in 26 and 27 days were scored 0.65 to 0.73 where the golden set says escalate); two explicit anchors in the judge prompt (fewer than 10 peers scores 0.4 or lower, a contract expiring within 30 days scores 0.5 or lower) fixed it, and two further runs gave threshold 0.85, kappa 1.00, false-auto-send 0.000, stored in `backend/data/judge_calibration.json`. Run-to-run variance is real (3 misses on one run, 4 on the next before the fix), so re-run calibration after any prompt or model change.

## Phase 6: LLMOps and tracing

What: Langfuse tracing (one trace per run, every tool call/graph hop/dedupe decision), eval-set construction from reviewer corrections, release gating on false-auto-send rate, the consolidation job (episodic to semantic/graph, via `procrastinate` per ADR-0003) that turns corrections into permanent facts and edges.
Depends on: Phases 2-5 all producing traceable events; this phase instruments what already exists rather than building new user-facing behavior.
Done when: a deliberately-planted correction (simulating a human fixing a predicted price) shows up as a new graph edge or semantic fact, and a subsequent identical scenario skips human review as a result.
Why sixth: this is the "memory that compounds" story from the article, the payoff only demonstrates once every earlier phase is producing the events it consolidates.
Status: complete (see docs/superpowers/specs/2026-09-29-phase6-llmops-tracing-design.md). A reviewer correction posted to `POST /v1/review/{id}/resolve` is validated, stored with a full-evidence eval case, and consolidated by a `procrastinate` worker into a permanent fact (SKU list price, required part, or contract coverage) plus its graph edge; acceptance tests prove a later identical scenario is no longer flagged for all three dimensions. Langfuse tracing is a no-op without keys and has never been pointed at a hosted service. The release gate on false-auto-send rate is in `scripts/calibrate_judge.py` (dry run by default). Known gaps: trace payloads record full tool results rather than args, the gate's denominator is all ready cases, and a failed graph sync needs a manual rebuild.

## Phase 7: Frontend (review queue UI)

What: Vite + React + Tailwind + Ant Design app showing the review queue (Meera's screen: one price, predicted, here's why), the quote detail view with the graph evidence path, and a simple dashboard of the tracked metrics (auto-send rate, correction rate, duplicate rate).
Depends on: Phase 2 through 6's backend endpoints existing to render real data.
Done when: a reviewer can open the app, see a low-confidence quote with its flagged reason, approve or correct it, and see that correction reflected in a later quote (ties back to Phase 6's consolidation).
Why last: it's a view onto data the backend phases produce; building it earlier means mocking data that later phases will make real anyway.
Status: complete (see docs/superpowers/specs/2026-09-30-phase7-review-ui-design.md). Read-only backend endpoints (`GET /v1/review?status=`, `/v1/quotes`, `/v1/quotes/{id}`, `/v1/metrics`) plus CORS, a seed script (`scripts/seed_demo.py`) that drives the real intake, dedupe, estimate and judge services with scripted LLM stand-ins, and a `frontend/` app (Vite, React, Tailwind 4, Ant Design 6, TanStack Query) with the review queue, quote detail, all-quotes list and dashboard. Observed in a real browser against the dev database on 2026-09-30: the queue showed 4 open flags (price, graph, contract, guardrail); the price flag detail showed the email, a `predicted` line, judge scores, peer evidence and Approve / Correct; a price of `0` was blocked client-side and a valid one showed "Correction saved"; the guardrail item showed its violation and no buttons; after correcting all three correctable flags in the UI, `seed_demo.py --replay --yes` re-ran them and each quote showed a clean Latest estimate with the auto-sent notice next to the earlier flagged one marked resolved; the dashboard showed 71.4% auto-send, 100% correction (3 of 3) and 33.3% duplicate. Automated (final, after the graph work below): 747 backend and 81 frontend tests. Known gaps: no pipeline-trigger UI, guardrail items read-only, evidence is a stored snapshot, the scripted judge and extraction prove plumbing not model judgment (the demo quotes all use quantity 1), no auth, TypeScript pinned to 5.9.3 because openapi-typescript cannot load under 7, and eight minor review findings deferred (for example a 409 on resolve leaves stale buttons). Addendum, added the same day after the first review found the UI showed graph evidence only as text: a live graph explorer at `/graph` (schema overview with counts, then a type's 60 most connected nodes, then one-hop expansion, plus a draw-everything button; Cytoscape with the fCoSE layout, because the built-in layout took 20 s on the 1712-node full graph) and dashboard bar charts (flags by dimension, graph node and edge counts). The dev graph now holds 10 node types and 12 of the 15 edge types; `FOR_PROJECT`, `VARIANT_OF` and `SUPERSEDES` never occur in the demo data. See `docs/superpowers/plans/2026-09-30-graph-explorer-and-dashboard-charts.md`.

## Phase 8: Interview polish

What: a seeded demo run reproducing the article's Ravi/Kiran/Sana story beats on the synthetic dataset, README updated with actual screenshots/output, a documented local run procedure (Docker Compose up, seed data, run one email through end to end).
Depends on: all prior phases working end to end.
Done when: a stranger can clone the repo, follow the README, and watch one email produce a graph-corrected, judge-scored, possibly-deduped estimate without you narrating it live.
Why last: this is packaging, not capability; it only makes sense once there's a real system to package.
Status: not started, ready to start. Already in place: every prior phase merged, a 747-test backend and 81-test frontend, a seeded demo (11 quotes covering every role), a documented no-cost setup for a new machine (`docs/new-machine-setup.md`, restoring the embeddings and summaries from `backend/data/llm_snapshot.json.gz`), and a working reviewer UI with a graph explorer. Open inputs before it can be finished: (1) the Ravi/Kiran/Sana story beats are named here and in two plans but written down nowhere in the repo, so the source article's beats need to be supplied to map them onto scenarios; (2) "watch one email produce an estimate" needs a way to trigger the pipeline, and none exists (no UI, no CLI), so it needs either a small trigger script running the live OpenAI extraction and agent and the Anthropic judge (pennies of spend) or an accepted scripted-only demo; (3) README screenshots; (4) the deferred Phase 7 minors are optional but two backend acceptance tests still fail on a database that already holds the seeded demo (absolute row counts), which a stranger following the README would hit; (5) `docs/checklist.md` is badly out of date and should be reconciled.

## Sequencing notes

- Phases 1 to 3 are close to strictly sequential (each needs the prior one's output to test against).
- Phase 4 (graph) and Phase 2 (dedupe) don't depend on each other and could be built in either order or in parallel if using subagent-driven development; the order above follows the article's own "where to invest, in this order" guidance, not a hard technical dependency between the two.
- Phase 5 needs both Phase 3 (agent) and Phase 4 (graph) done, since it judges graph-evidenced agent output.
- Given the 2-4 week budget, Phases 1 to 5 are the interview-relevant core (data, intake/dedupe, agent, graph, evals). Phases 6 to 8 are what separate a POC that runs once from one that demonstrates the article's central claim: memory that compounds. Worth protecting time for at least a thin version of Phase 6, since that's the specific thing this project is trying to prove out.

## Next step

Phase 8 (interview polish) is next. As with the earlier phases it needs a short spec (via `brainstorming`) and a plan (via `writing-plans`) first, and the open inputs listed in its Status line settled: the story beats, and how a stranger triggers one email end to end.
