# 02. System Design Walkthrough

This is the project told as a worked answer to: "Design a system that turns messy B2B quote-request emails into correct, priced estimates." Module paths are under `backend/app` unless stated. ADRs are in `docs/adr`.

Before the walkthrough, one honest note about scope. Each stage is its own module and its own endpoint. There is no single "run the whole pipeline" trigger in the running app. The seeded demo chains the stages in `backend/scripts/demo/seed.py`, with scripted stand-ins for the three model clients. A second script, `backend/scripts/run_live_estimates.py`, chains intake, dedupe and the agent with the real OpenAI models, for a measured run (see file 04). I say this early so nobody discovers it later.

## The data flow (matches the code)

```
 email text
    |
    v
 [1 INTAKE]  intake/service.py
    | one GPT-4o structured-output call -> names as written
    | resolution.py (code): exact match, then fuzzy match, else null
    | writes quote_requests row with two fingerprints:
    |   content = sorted resolved SKU ids
    |   style   = normalized word tokens of the email
    v
 [2 DEDUPE]  dedupe/service.py
    | block: same customer OR same site OR same contract (SQL)
    | classify on SKU sets: identical -> DUPLICATE_OF
    |                       strict superset and jaccard >= 0.4 -> REVISION_OF
    |                       else DISTINCT
    | writes dedupe_verdicts (also records style jaccard)
    v
 [3 AGENT LOOP]  estimate/graph.py (LangGraph)
    |
    |   START -> agent -> tools -> (submit_draft?) -> guardrails
    |              ^                                      |
    |              |         violations and retries < 3   |
    |              +--------------------------------------+
    |
    |   agent:      GPT-4o picks tools or submits a draft (max 12 turns)
    |   tools:      lookup_customer, search_price_book, check_stock,
    |               get_related_parts (graph), check_contract_coverage (graph),
    |               predict_price, ask_knowledge (router)
    |   guardrails: required fields, customer identity, price provenance,
    |               contract discount, graph integrity (all plain code)
    |   ends:       ready | needs_review (never an error, never silent)
    |
    |   tools read:  Postgres + pgvector (SQL, vectors)   Neo4j (graph)
    v
 [4 JUDGE]  judge/service.py
    | needs_review draft -> fast path, no model call, cost zero
    | ready draft -> evidence.py assembles per-line evidence in code
    |   Claude Haiku scores 3 dimensions via a forced tool call
    |   overall = min(price_provenance, contract_discount, graph_completion)
    |   trusted = overall >= calibrated threshold (judge_calibration.json)
    v
   trusted? --yes--> auto-send path (ready, no human)
      |
      no
      v
 [5 REVIEW]  one ReviewItem: weakest dimension, its evidence, one sentence
    | UI: review queue -> quote detail -> Approve or Correct
    | POST /v1/review/{id}/resolve  (validate, lock, store eval case, commit)
    v
 [6 CONSOLIDATION]  consolidation/  (procrastinate worker, Postgres queue)
    | correction -> Postgres fact (list price | required part | coverage)
    |            -> one Neo4j property or edge, graph fingerprint updated
    v
   next identical quote finds a list price / requirement / coverage
   and the judge has nothing to flag

 Side channels:  core/tracing (Langfuse, no-op without keys)
                 metrics/ (auto-send, correction, duplicate rates)
                 graph rebuild: POST /v1/graph/rebuild (Postgres -> Neo4j)
```

## The walkthrough, stage by stage

### 0. Requirements I state first

I always start here, out loud.

- **Goal:** a priced estimate from a free-text email, right the first time.
- **The wrong-answer cost is asymmetric.** A late quote loses a sale. A wrong quote that goes out loses margin or trust. So the system should prefer "send to a human" over "send something wrong".
- **Scale I designed for:** a POC. About 650 SKUs and 125 customers (`backend/data`). I say that plainly and then talk about what changes at 100x (see file 04).
- **Non-goals:** no auth, no pipeline-trigger UI, no real data.

### 1. Intake (`intake/`)

The model reads only words. So extraction returns names as written. Code then resolves them to real IDs: exact match first, fuzzy match second (`resolution.py`, rapidfuzz), and if it is not exactly one confident answer, the field stays empty. An unresolved guess is safer than a resolved wrong one. Source: `../phase2-interview.md`.

### 2. Dedupe (`dedupe/`)

Two ideas. First, blocking: only compare against requests sharing a customer, site, or contract (`repository.py`). Second, two fingerprints. The content fingerprint is the resolved SKU set. The style fingerprint is the email's word tokens. Only the content fingerprint decides the verdict today. The style similarity is recorded on each verdict row but does not change the label. I state that when asked, because it is easy to overclaim.

### 3. Agent loop (`estimate/`)

LangGraph state machine with three nodes: agent, tools, guardrails (`graph.py`). Limits: 3 retries (4 submissions) and 12 agent turns (`constant.py`). Hitting either ends as `needs_review`. The model never sets totals. Code computes them (`helper.py`).

The design rule is "the model proposes, code disposes". Guardrails (`guardrails.py`) check required fields, customer identity, price provenance (list price must equal the price book, predicted price must equal the prediction function), contract discount, and graph integrity. Each guardrail anchors on something the model did not write: the customer stored on the request, and the SKU ids resolved by code at intake.

### 4. The four memories, and what is actually built

This is the part where I am precise, because the README describes the design and the code is a subset.

| Memory | What I built | Where | What I did not build |
|---|---|---|---|
| Procedural (rules, policy) | The agent's system prompt and the guardrail code | `estimate/prompts.py`, `estimate/guardrails.py` | A skill-file loader. The rules are in code, not files the agent loads. |
| Semantic (durable facts, vector search) | SKU embeddings (pgvector, `text-embedding-3-small`), and corrections consolidated into permanent facts | `retrieval/vector.py`, `consolidation/` | Per-customer fact memory retrieved by vector search |
| Episodic (what happened before) | Every request, estimate, verdict, review item, and eval case in Postgres | `intake/`, `estimate/`, `judge/models.py` | Retrieving past episodes into the agent's context |
| Knowledge graph | Neo4j: 10 node types, 15 edge types defined, 12 occur in the demo data | `graph/`, ADR-0002 | Nothing missing in structure. Three edge types never occur in the data. |

### 5. Hybrid retrieval router (`retrieval/router.py`)

A deterministic, ordered list of regex rules decides where a question goes: portfolio phrasing goes to graph-global (community summaries), similarity phrasing goes to vector search, an ID with relationship words goes to graph-local, a bare ID goes to SQL or graph, a name goes to SQL search. No model in the loop, so it is free and testable. The agent reaches it through the `ask_knowledge` tool. The trade-off: regex routing breaks on phrasing it has not seen. I have not measured router accuracy (see file 06).

### 6. Estimate guardrails and the graph (`estimate/guardrails.py`, `graph/`)

The graph is a rebuildable projection of Postgres, namespaced per test (ADR-0002). If Neo4j is down or stale, the run ends `needs_review` before any model call. Freshness is checked before the loop and again on every guardrail pass, plus before and after the graph reads, because a rebuild mid-check once let a bad draft reach `ready` in a review probe. A Postgres advisory lock serializes rebuilds.

### 7. Judge and review routing (`judge/`)

Evidence first, judgment second. `evidence.py` builds per-line facts in code: price source and peer spread, contract coverage and days to expiry, discontinued status and missing required parts. The judge scores only that evidence. Threshold calibration is in `judge/calibration.py` and `scripts/calibrate_judge.py`. Model choice follows ADR-0004: GPT-4o agent, Claude Haiku judge, different vendors.

### 8. Correction consolidation (`consolidation/`)

Resolve first, then enqueue after commit, on a Postgres queue (`procrastinate`, ADR-0003). Three handlers: a price sets `Sku.list_price`, a required part adds a `SkuRequirement`, a coverage adds a covered category. Each mirrors to one graph write. Graph freshness uses a compare-and-set fingerprint that fails closed.

### 9. LLMOps and observability (`core/tracing/`, `metrics/`)

Langfuse spans wrap the estimate run, each tool call, each graph-integrity check, and each dedupe verdict. It is a no-op without keys and never raises into the agent loop. It has never been pointed at a hosted service. The dashboard shows three rates computed from Postgres: auto-send, correction, duplicate. A rate is `null`, never `0`, when nothing has been measured.

## What I say about trade-offs

- Postgres plus pgvector, not a vector database (ADR-0001). Scale is small and one fewer service to run.
- Neo4j for relationships that are open-ended hops (ADR-0002). Only Neo4j was evaluated, and I say so. No comparison against other graph databases was done.
- `procrastinate`, not Redis (ADR-0003). One fewer service. The ceiling is lower, and the honest scaling answer is a future swap.
- One point of drift: ADR-0003 also names an in-process `cachetools` cache. There is no `cachetools` dependency or cache in the code today. The router runs uncached. I mention this only if asked about caching.

## One-page template: any LLM system-design question

Use this skeleton. The right column is this project as the example.

| Step | Ask yourself | This project |
|---|---|---|
| 1. Goal and cost of error | What does a wrong answer cost, compared with a slow one? | A wrong quote costs more than a late one, so prefer human review over a wrong send |
| 2. Inputs | What arrives, how messy, how often? | Free-text email, no part numbers |
| 3. Structure the input | What must code decide, not the model? | Model extracts names. Code resolves IDs. Empty beats a guess. |
| 4. Cheap filters first | What can be settled before any model call? | Dedupe blocking, `needs_review` skips the judge |
| 5. The model's job | What is the model good at here? | Reading the email, choosing tools, proposing a draft |
| 6. Hard rules in code | What must be guaranteed, not probable? | Guardrails. Anchored on facts the model did not write. |
| 7. Memory types | What must it remember, and in which form? | Rules in code, facts in Postgres, relationships in a graph, history in SQL |
| 8. Retrieval | Which questions need SQL, graph, vector? | Deterministic router with a fixed precedence |
| 9. Evaluation | How do you know it is right, and who checks the checker? | Different-vendor judge, hand-labeled golden set, kappa threshold, false-auto-send gate |
| 10. Human in the loop | What does the human see? | One flagged fact with evidence, not the whole quote |
| 11. Learning loop | How does a fix become permanent? | Correction becomes a fact and a graph edge |
| 12. Failure modes | What happens when a dependency is down or stale? | Fail closed: graph stale means `needs_review` |
| 13. Observability | How would you debug one bad quote? | Trace per run, spans per tool, metrics on rates |
| 14. Cost and latency | Where do the tokens go? | Measured once in a script: about 2.5 cents and 13 seconds per quote before the judge. Not yet in the product. |
| 15. Scale and next steps | What breaks at 100x? | Queue, single-transaction agent runs, regex router (see file 04) |

The habit that makes this land: at each row, say what I built, what I did not, and how I would know.
