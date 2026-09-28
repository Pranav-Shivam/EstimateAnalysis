# Phase 4 Design: Knowledge Graph, Graph Query Modes, Hybrid Retrieval Router

Date: 2026-09-28. Roadmap: `docs/roadmap.md` Phase 4. Research: `docs/research/neo4j-gds-leiden-community.md`, `docs/research/article-graph-schema.md`, `docs/research/graphrag-vs-vector-rag.md`. ADRs in force: 0001 (pgvector), 0002 (Neo4j Community).

## Goal

The Phase 3 agent resolves the three planted mistake types (discontinued-SKU swap, missing required part, wrong-category discount) by traversing a Neo4j graph, and deterministic guardrail code, anchored on data the LLM did not write, blocks a draft that leaves a discontinued SKU in place or omits a required part. Beyond the agent, the graph supports Leiden communities, local (fan-out) and global (community-summary) query modes, and a router that picks SQL, graph-local, graph-global or vector per question.

Done when, on a namespace built from the real dataset, all 30 real scenario cases (10 discontinued swaps, 10 missing required parts, 10 wrong-category discounts from `scenario_cases.json`) are blocked or corrected through graph traversal by a scripted agent, and the guardrail bypass probes in Testing all fail closed.

## Scope

In:
- Data additions: product families, projects, contacts, SKU embeddings table, community summary cache.
- Neo4j service, driver wrapper, the article's full schema (10 node types, 15 edge types), a rebuildable projection from Postgres, best-effort incremental sync of runtime entities.
- Two graph-backed agent tools, one new router-backed tool, a new `graph_integrity` guardrail with a freshness check.
- Leiden via GDS, local and global query modes, LLM narrative summaries with a Postgres cache.
- pgvector vector arm (SKU embeddings) and the rule-based router.
- Endpoints, tests, acceptance test.

Out (later phases): LLM judge and confidence (Phase 5), tracing and the consolidation job that writes corrections back as edges (Phase 6), UI (Phase 7), fixing intake's own `site_id` resolution (a separate follow-up, see Known gaps).

## Decisions (agreed during brainstorming)

1. **Schema scope: the article's full 10 nodes and 15 edges.** Recommended alternative was the 4-node core; the owner chose the full schema. Consequence: Phase 4 also extends the data generators and Postgres.
2. **The three edges with no source in the article's terms are defined from data the system holds.** VARIANT_OF: QuoteRequest to QuoteRequest, same customer, a `DISTINCT` verdict whose `content_jaccard` is at or above `VARIANT_MIN_JACCARD` (a named constant chosen in the plan from the real verdict distribution). SUPERSEDES: Quote to Quote, a later `estimate_drafts` row for the same quote request supersedes the earlier one. PRICE_VARIANCE: Quote to SKU, one edge per draft line that carries a discount or a predicted price, with properties `list_price`, `unit_price`, `discount_pct`, `price_source`, `net_unit_price`.
3. **Postgres stays authoritative; the graph is a derived, rebuildable projection.** Nothing writes to the graph independently. `rebuild_graph` wipes and reloads a namespace from Postgres. Runtime entities (QuoteRequest, Quote, verdict edges) are also synced incrementally after the route commits, best-effort: a sync failure is logged and never fails the request. Any drift is healed by a rebuild.
4. **Graph tools augment the SQL tools.** SQL keeps `lookup_customer`, `search_price_book`, `check_stock`, `predict_price`. `get_related_parts` becomes graph-backed and `check_contract_coverage` is new. Each question has one owner.
5. **Guardrails use the graph, anchored on intake.** Intake's `resolved_line_items` (code-resolved SKU ids) are the anchor, not the draft. Chosen over draft-only checks because a draft-only rule is bypassed by dropping the offending line (the same class as the Phase 3 customer bypass).
6. **Router and global mode: base plus LLM narrative summaries plus the vector arm.** Summaries and embeddings both call a paid API only behind an explicit `--yes` gate, and never without the owner's approval.
7. **FOR_PROJECT is resolved at graph-sync time only.** Intake never resolves a site (`resolve_extraction` hardcodes `site_id=None`). `sync_quote_request` matches `site_hint` to one of the customer's sites by a unique zip or street match, then follows Site to Project. Nothing in Postgres or Phase 2 changes.

Decisions made without a question (constraints the owner set, or forced by the design):
- **Neo4j Community, pinned image tag, host ports 17474 (HTTP) and 17687 (Bolt).** The tag is chosen in the plan after verifying `gds.version()` on the container. Candidates: `2026.09.0-community`, `5.26.31-community`. Never the default ports, never `latest`.
- **Namespaces.** Every graph node carries an `ns` property and a `key` property equal to `ns + ":" + id`, with a uniqueness constraint on `key` per label (Community edition has no composite node key). The dev graph uses `ns="main"`; each test uses `ns="test-<uuid>"` and drops it on teardown. Rebuild and every query are namespace-scoped.
- **Fail closed.** A graph-backed guardrail that cannot reach the graph, or finds it stale, ends the run as `needs_review`. It never skips silently.
- **The SQL `contract_discount` guardrail stays the sole discount authority.** `check_contract_coverage` is advisory, so a stale graph cannot authorize a discount.
- **`ToolContext` gets a required `graph` reader and required `request_sku_ids`, and `request_customer_id` loses its default.** This closes the Phase 3 gap where it defaulted to `None`.
- **Summary model is a named constant, default `gpt-4o-mini`.** Embeddings use `text-embedding-3-small` (1536 dimensions), per the README.

## Architecture

Layer order follows `docs/backend-structure.txt`: route, service, repository, DB/LLM.

### Data additions

- `scripts/data_gen/structure_gen.py`, seeded with its own offset like the other generators, writes `data/structure.json`. Phase 1 and Phase 3 outputs are not modified.
  - `families`: `family_id`, `name`, derived from the SKU name stem (the name minus its size and finish suffix), and the `sku_id` to `family_id` mapping.
  - `projects`: exactly one per site (`project_id`, `customer_id`, `site_id`, `name`), so a resolved site gives a unique project.
- Contacts come from the existing `customers.json`. Each gets a deterministic id `<customer_id>-C<n>`.
- Alembic migration `0004`:
  - `CREATE EXTENSION IF NOT EXISTS vector`.
  - `product_families` and nullable `skus.family_id`.
  - `projects`, `contacts`.
  - `sku_embeddings` (`sku_id` PK and FK, `embedding vector(1536)`, `model`, `created_at`).
  - `community_summaries` (`member_hash` PK, `summary`, `model`, `created_at`).
- `scripts/load_data.py` loads families, projects and contacts idempotently. `validate.py` gains checks: every SKU has a family, every site has exactly one project, project sites belong to the project's customer, contacts reference real customers.

### Infrastructure

- `docker-compose.yml` gets a `neo4j` service: pinned Community tag, `NEO4J_PLUGINS='["graph-data-science"]'`, ports `17474:7474` and `17687:7687`, a named volume, auth from environment.
- `Settings` gains `neo4j_uri` (default `bolt://localhost:17687`), `neo4j_user`, `neo4j_password`, with dev defaults matching the compose file, so the documented inline-env test procedure needs no extra variables.
- Dependencies added: `neo4j` (driver), `pgvector` (SQLAlchemy type).

### Modules

- `core/graph/`: driver wrapper with read and write helpers and a per-query timeout; typed `GraphUnavailable`.
- `app/graph/`: `repository.py` (all Cypher and GDS calls), `service.py`, `schemas.py`, `constant.py`, `helper.py`.
  - Service functions: `rebuild_graph`, `sync_quote_request`, `sync_dedupe_verdicts`, `sync_quote`, `run_communities`, `local_query`, `global_query`, `reference_fingerprint`.
- `app/retrieval/`: `router.py`, `service.py`, `vector.py`, `summarizer.py` (interface plus the community-summary orchestration).
- `core/llm/`: `openai_embedding_client.py`, `openai_summary_client.py`, both injected so tests pass fakes. Same wrapping discipline as `openai_agent_client.py`: malformed or empty responses become a typed error.
- `api/v1/retrieval/`: `POST /v1/retrieval/ask`. `api/v1/graph/`: `POST /v1/graph/rebuild`.
- `app/estimate/`: `tools.py` and `guardrails.py` modified; `graph.py` gains the graph-unavailable and unreplaceable terminal outcomes; `prompts.py` updated for the new tools; the intake, dedupe and estimate routes call the sync functions after commit.

### Graph schema

Nodes (each also has `ns` and `key`):

| Node | Id | Properties | Source |
|---|---|---|---|
| Customer | customer_id | name, account_tier | `customers` |
| Person | contact id | name, email, phone | `contacts` |
| Contract | contract_id | discount_pct, discount_category, effective_from, effective_to | `contracts` |
| PricingCategory | category name | none | distinct `skus.category` |
| ProductFamily | family_id | name | `product_families` |
| SKU | sku_id | name, category, list_price, discontinued, in_stock, community_id | `skus` |
| Project | project_id | name | `projects` |
| Site | site_id | address, zip | `sites` |
| QuoteRequest | request uuid | case_id, created_at | `quote_requests` |
| Quote | draft uuid | quote_request_id, status, created_at | `estimate_drafts` |
| GraphMeta | ns | reference_fingerprint, built_at | computed at rebuild |

Edges:

| Edge | Direction | Source |
|---|---|---|
| WORKS_FOR | Person to Customer | `contacts.customer_id` |
| HOLDS | Customer to Contract | `contracts.customer_id` |
| COVERS | Contract to PricingCategory | `contracts.covered_categories` |
| IN_FAMILY | SKU to ProductFamily | `skus.family_id` |
| REPLACED_BY | SKU to SKU | `skus.replaced_by` |
| PRICED_IN | SKU to PricingCategory | `skus.category` |
| REQUIRES | SKU to SKU | `sku_requirements` |
| HAS_PROJECT | Customer to Project | `projects.customer_id` |
| AT_SITE | Project to Site | `projects.site_id` |
| FOR_PROJECT | QuoteRequest to Project | sync-time `site_hint` match (Decision 7) |
| DUPLICATE_OF | QuoteRequest to QuoteRequest | `dedupe_verdicts`, property `content_jaccard` |
| REVISION_OF | QuoteRequest to QuoteRequest | `dedupe_verdicts`, property `content_jaccard` |
| VARIANT_OF | QuoteRequest to QuoteRequest | Decision 2 |
| SUPERSEDES | Quote to Quote | Decision 2 |
| PRICE_VARIANCE | Quote to SKU | Decision 2 |

Quote nodes carry a `quote_request_id` property, which is how `sync_quote` finds the prior draft for the same request when it writes SUPERSEDES. No sixteenth edge type is added.

### Freshness fingerprint

`reference_fingerprint(session)` is an md5 over the ordered rows of `skus` (id, category, discontinued, replaced_by, family_id, in_stock), `sku_requirements`, and `contracts` (id, customer_id, covered_categories, dates, discount_pct). `rebuild_graph` stores it on the `GraphMeta` node. Runtime entities are excluded, so intake and estimate runs do not invalidate the graph. The guardrail node recomputes it once per run and compares.

### Agent tools

- `get_related_parts(sku_id)`, graph-backed: follows REPLACED_BY (bounded to 10 hops, relationship-unique paths so a cycle terminates) to the live end. Returns the chain, `live_replacement` (or null when the chain ends on a discontinued SKU), the REQUIRES parts of the live SKU with their own status, and an `evidence_path` (node ids and edge types) for Phase 5.
- `check_contract_coverage(customer_id, sku_id)`, new: Customer HOLDS Contract COVERS PricingCategory PRICED_IN SKU. Per contract: covered or not, the SKU's category, the covered categories, `discount_pct`, active on `as_of` (evaluated against the node dates), and the path. Advisory only.
- `ask_knowledge(question)`, new: router-backed, described to the model as for similarity and portfolio questions only.
- Tool errors, including `GraphUnavailable`, are returned as an error dict, never raised, following the existing `handle_tool` discipline (all arguments must be strings).

### Guardrail `graph_integrity`

Runs with the existing four. Inputs: the draft, the graph reader, the intake-resolved SKU ids (`ToolContext.request_sku_ids`).

1. Discontinued line: a line whose SKU is discontinued is a violation; the message names the chain's live replacement.
2. Request coverage: each intake-resolved SKU must be covered by a line holding the live end of its REPLACED_BY chain (the SKU itself when it is live).
3. Required parts: every line SKU's REQUIRES parts must appear as lines. Lines added to satisfy this are checked on the next pass, so the rule holds transitively. Presence is checked, quantity is not.
4. Unreplaceable SKU: a chain with no live end cannot be fixed by a retry, so the run ends `needs_review` at once with the SKU named in the reason. It does not consume retries.

Freshness: before rules 1 to 4, the fingerprint check. On mismatch or `GraphUnavailable` the run ends `needs_review` with a reason ("knowledge graph unavailable or out of date, rebuild"). The result never reaches `ready`.

### Sync

The routes commit, then call, best-effort (log and continue on `GraphUnavailable` or Cypher failure):
- intake route: `sync_quote_request` (node, FOR_PROJECT by `site_hint`).
- dedupe route: `sync_dedupe_verdicts` (DUPLICATE_OF, REVISION_OF, VARIANT_OF).
- estimate route: `sync_quote` (Quote node, SUPERSEDES to the prior draft, PRICE_VARIANCE edges).

All syncs use MERGE and are idempotent. `rebuild_graph` reconstructs everything, runtime entities included, from Postgres.

### Leiden

- Projection (namespace-scoped, Cypher projection): SKU and ProductFamily nodes; IN_FAMILY, REQUIRES, REPLACED_BY, all `UNDIRECTED`. PricingCategory is excluded: five hubs would make every community a category. Category becomes a per-community statistic.
- Fixed `randomSeed` constant, default `gamma`. Written back as `community_id` on the projected nodes. The projection is dropped after the run.
- `run_communities` returns the community count and size distribution. The spec does not predict them; the plan's acceptance step reports them from the real graph, and that count sets the summary cost.

### Local mode

`local_query(node_id, hops)`: hops capped at 2. Never expands through a PricingCategory or ProductFamily hub; hubs appear only as leaves (a 2-hop walk through a category would return about 190 SKUs). Returns nodes, edges and paths, capped at 50 nodes with a `truncated` flag. The node id is validated against the namespace.

### Global mode and summaries

- `global_query()` returns one record per community: id, size, families, dominant category share, discontinued count, count with requirements, example SKUs, and the cached summary when one exists. The statistics are computed by code and always present.
- Narrative summaries: an injected summarizer is given the statistics and member names and told to state nothing else. Results cache in `community_summaries` keyed by a SHA-256 of the sorted member ids, so a rebuild or a relabeled community reuses paid output and only cache misses call the model.
- `scripts/summarize_communities.py` is a dry run by default: it prints the number of communities that need a call and a token estimate, and calls the API only with `--yes`.
- Retrieval returns evidence, not a final answer; the agent's model writes the prose.

### Router and vector arm

`route_question` returns a route and the rule that fired. It is deterministic, free, and precedence-ordered:

1. Portfolio or aggregate phrasing ("which product groups", "across the catalog", "most exposed"): graph-global.
2. Similarity phrasing ("similar to", "alternative to", "something like"): vector, even when an id is present (the SKU's embedding text is used).
3. An explicit id (SKU, CUST, CTR pattern) plus relationship phrasing ("replaced by", "requires", "covers", "connected"): graph-local.
4. An explicit id with anything else: SQL attribute lookup.
5. Anything else: SQL name search.

The SQL arm reuses Phase 3's fuzzy search, extracted from `tools.py` into `reference_data` and called by both, not copied.

Vector arm: `scripts/embed_skus.py` embeds "name | category | family" per SKU with `text-embedding-3-small` into `sku_embeddings`. It is a dry run by default (prints SKU count and a token estimate) and calls the API only with `--yes`. Search is an exact cosine scan (`<=>`); at about 650 rows an index adds nothing. Each vector question costs one small embedding call at run time. An empty table returns a typed "embeddings not built" error, not an empty result.

## Error handling

- `GraphUnavailable` maps to 503 at the routes. LLM failures map to 502 as in Phase 3.
- Sync failures are logged and never change a route's response.
- Guardrail outcomes: violations loop back to the agent up to the existing retry cap; stale graph, graph down and unreplaceable SKU end the run `needs_review` at once.

## Testing

- No real OpenAI or other paid API call anywhere in the suite. Scripted fakes for the agent, embedder and summarizer.
- Real Postgres on port 5433 with the rollback fixture. Real Neo4j on port 17687 with per-test namespaces, dropped on teardown. No test asserts an absolute row or node count; tests check only ids they create.
- If Neo4j is unreachable the suite fails loudly with the compose command to start it. There are no silent skips.
- Coverage:
  - Data: `structure_gen` determinism and one-project-per-site, loader idempotence, new `validate.py` checks.
  - Graph: rebuild idempotence and namespace isolation, each of the 15 edge types built from seeded rows, fingerprint change detection, sync idempotence and sync-failure swallowing.
  - Tools: REPLACED_BY chain to the live end, a chain with no live end, a cycle, required parts, coverage covered, uncovered and expired, hop bound, wrong-typed arguments.
  - Guardrail rules 1 to 4, plus bypass probes: drop the offending line, swap to a mid-chain (still discontinued) SKU, omit a required part, stale fingerprint, graph down, unresolved intake item (documents the residual gap).
  - Leiden: determinism with a fixed seed on planted clusters, projection dropped after the run, namespace scoping.
  - Local: hub non-expansion, node cap and `truncated`, hop cap. Global: statistics correct, summary cache hit makes zero model calls, only misses call.
  - Router: a table-driven test over every rule and its precedence. Vector: fake embedder, empty-table error.
  - Acceptance: the 30 real scenario cases on a test namespace built from the real dataset, run through a naive scripted agent that must be blocked or corrected by graph traversal.

## Cost gates

- Neo4j and Postgres are local: free.
- Embedding run (about 650 short strings) and community summaries (one call per cache miss): both dry-run by default, both require `--yes` and the owner's approval before I run them. Counts and token estimates are reported first.
- No live-OpenAI run of the agent over the 60 real emails. That gap from Phase 3 remains and needs approval.

## Risks

- The GDS plugin is downloaded at container start and has failed on some Neo4j versions. Mitigation: pin a tag, assert `gds.version()`, try the second candidate tag if the first fails, and stop and ask if both fail.
- The dev Postgres must have the `vector` extension available for migration `0004`. The compose image is `pgvector/pgvector`, but the instance actually serving port 5433 must be checked before the migration runs.
- Docker Desktop was not running when checked on 2026-09-28. Neo4j and every graph test need it.

## Known gaps carried in

- Intake items that did not resolve to a SKU cannot be anchored by `graph_integrity`; only the draft-only rules apply to them.
- A wrong intake fuzzy match is inherited by the guardrails, as with the customer match in Phase 3.
- Required-part quantity is not checked, only presence.
- Intake still never sets `site_id` on `quote_requests`; FOR_PROJECT works around it at sync time. Fixing intake is a separate change that would alter dedupe behavior.
- The dev `quote_requests`, `dedupe_verdicts` and `estimate_drafts` tables are empty because the 60 emails were never run through intake (it needs a paid API call). Runtime graph nodes are therefore empty on the dev graph until that happens; tests seed their own.
- Leiden communities on this data are structural clusters (family, REQUIRES, REPLACED_BY). The catalog has no purchase history, so they are not buying patterns.
- The router is rule-based and will misroute phrasing its rules do not cover. An LLM classifier was rejected for cost and testability.
- No auth on the new rebuild route, consistent with the rest of the POC.
