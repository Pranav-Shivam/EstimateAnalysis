# Roadmap

Phase breakdown for building the quote estimation agent from scratch, per `README.md` and the 4 ADRs in `docs/adr/`. This is the decomposition level, not the implementation level: each phase below gets its own written spec and then its own bite-sized TDD plan (via the `writing-plans` skill) before any code is written for it. No code exists yet; this document lays out order and dependency only.

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
Status: complete (see docs/superpowers/specs/2026-09-28-phase4-knowledge-graph-design.md). The full 10 node and 15 edge schema is built from Postgres as a rebuildable projection; Leiden, local and global modes, LLM community summaries (cached, cost-gated), the pgvector arm and the rule-based router are in. Embeddings and community summaries have not been generated against the real data: both scripts are dry runs until run with --yes.

## Phase 5: Evals and review workflow

What: LLM-as-judge (cross-vendor per ADR-0004), scoring against price book/contract/graph evidence path, a calibrated confidence threshold (per `docs/research/llm-judge-calibration.md`: build a golden set from labeled corrections, derive the threshold from Cohen's kappa against it, not a copied 0.85), the human review payload (one flagged fact to check, not the whole quote).
Depends on: Phase 3's agent output and Phase 4's graph evidence paths to score against.
Done when: the judge correctly flags the Phase 1 scenarios seeded as low-confidence (e.g. a SKU price that was predicted, not looked up) and passes the clean ones, measured against the scenario set's known ground truth.
Why fifth: needs something real to judge; building the judge before the agent and graph exist would mean scoring against nothing.

## Phase 6: LLMOps and tracing

What: Langfuse tracing (one trace per run, every tool call/graph hop/dedupe decision), eval-set construction from reviewer corrections, release gating on false-auto-send rate, the consolidation job (episodic to semantic/graph, via `procrastinate` per ADR-0003) that turns corrections into permanent facts and edges.
Depends on: Phases 2-5 all producing traceable events; this phase instruments what already exists rather than building new user-facing behavior.
Done when: a deliberately-planted correction (simulating a human fixing a predicted price) shows up as a new graph edge or semantic fact, and a subsequent identical scenario skips human review as a result.
Why sixth: this is the "memory that compounds" story from the article, the payoff only demonstrates once every earlier phase is producing the events it consolidates.

## Phase 7: Frontend (review queue UI)

What: Vite + React + Tailwind + Ant Design app showing the review queue (Meera's screen: one price, predicted, here's why), the quote detail view with the graph evidence path, and a simple dashboard of the tracked metrics (auto-send rate, correction rate, duplicate rate).
Depends on: Phase 2 through 6's backend endpoints existing to render real data.
Done when: a reviewer can open the app, see a low-confidence quote with its flagged reason, approve or correct it, and see that correction reflected in a later quote (ties back to Phase 6's consolidation).
Why last: it's a view onto data the backend phases produce; building it earlier means mocking data that later phases will make real anyway.

## Phase 8: Interview polish

What: a seeded demo run reproducing the article's Ravi/Kiran/Sana story beats on the synthetic dataset, README updated with actual screenshots/output, a documented local run procedure (Docker Compose up, seed data, run one email through end to end).
Depends on: all prior phases working end to end.
Done when: a stranger can clone the repo, follow the README, and watch one email produce a graph-corrected, judge-scored, possibly-deduped estimate without you narrating it live.
Why last: this is packaging, not capability; it only makes sense once there's a real system to package.

## Sequencing notes

- Phases 1 to 3 are close to strictly sequential (each needs the prior one's output to test against).
- Phase 4 (graph) and Phase 2 (dedupe) don't depend on each other and could be built in either order or in parallel if using subagent-driven development; the order above follows the article's own "where to invest, in this order" guidance, not a hard technical dependency between the two.
- Phase 5 needs both Phase 3 (agent) and Phase 4 (graph) done, since it judges graph-evidenced agent output.
- Given the 2-4 week budget, Phases 1 to 5 are the interview-relevant core (data, intake/dedupe, agent, graph, evals). Phases 6 to 8 are what separate a POC that runs once from one that demonstrates the article's central claim: memory that compounds. Worth protecting time for at least a thin version of Phase 6, since that's the specific thing this project is trying to prove out.

## Next step

Each phase above needs its own written spec (via the `brainstorming` skill's architectural path) before it gets a bite-sized implementation plan (via `writing-plans`). Phase 1 is next in line since nothing else can be tested without it.
