# Phase 1: Synthetic Data Generation, Design Spec

Written 2026-09-27. Implements Phase 1 of `docs/roadmap.md`. Read `README.md` and the 4 ADRs in `docs/adr/` first if you have not: this spec assumes their decisions (Postgres+pgvector, Neo4j, no Redis, cross-vendor judge) without repeating the reasoning.

## Purpose

There is no real dataset for this project and none should be assumed. Every downstream phase (dedupe, agent, graph, evals) needs a structurally realistic dataset to reason over: referential integrity across entities, the discontinued/substitute/required-part patterns, and a set of quote-request emails with a known ground truth per scenario type. This phase builds that dataset and nothing else. No FastAPI, no LangGraph, no database writes: Postgres and Neo4j are not installed yet (Docker deferred), so everything here is file-based.

## Scope

In scope: `catalog_gen.py`, `customer_gen.py`, `graph_export.py`, `scenario_gen.py`, `validate.py`, and the fixed-seed config they share.

Out of scope: loading generated data into Postgres or Neo4j (a later phase, once Docker is installed), the dedupe agent itself (Phase 2), any FastAPI surface.

## Done when

- `validate.py` passes against a generated dataset (referential integrity and scenario coverage checks, both defined below).
- A manual spot-check of 10-15 generated scenario emails reads as realistic, not templated.
- Running the full pipeline twice with the same seed produces identical output.

## Repository layout

```
backend/scripts/data_gen/
  catalog_gen.py
  customer_gen.py
  graph_export.py
  scenario_gen.py
  validate.py
  config.py
backend/data/
  catalog.json
  customers.json
  graph/nodes.json
  graph/edges.json
  prompts/batch_*.md        (generated, git-ignored)
  responses/batch_*.json    (manually pasted replies, git-ignored)
  scenarios.json            (final, ingested and validated)
```

`backend/data/` holds generated output, not source; add it to `.gitignore` except for a small checked-in sample used in later phases' tests (exact sample file to be chosen when Phase 2 needs it, not decided here).

## Configuration

`config.py` holds a single fixed seed and the generation counts (catalog: 500-800 SKUs; customers: 100-150; scenarios: 60 total, 10 per type). Every generator seeds its random source from this value. Running the pipeline twice with the same seed and counts must produce byte-identical output; this is a hard requirement, not a nice-to-have, since `validate.py` and later phases depend on a stable dataset to test against.

## Data model

**SKU** (`catalog_gen.py`): `sku_id, name, category, list_price, discontinued (bool), replaced_by (sku_id or null), requires (list of sku_ids), in_stock (bool)`. `replaced_by` is only set when `discontinued` is true, and always points to a non-discontinued SKU. `requires` entries always point to SKUs that exist and are not discontinued (unless the case data explicitly needs a broken one, which is scenario-specific state, not catalog state).

**Customer** (`customer_gen.py`): `customer_id, name, account_tier, contacts (list of {name, email, phone}), sites (list of {site_id, address, zip}), contracts (list of {contract_id, discount_category, covered_categories (list), effective_from, effective_to})`. Every customer has at least one contact, one site, and one contract.

**Scenario case** (`scenario_gen.py`): `case_id, scenario_type, entities (references into catalog/customer data specific to that type), email_text (filled in after ingest)`. `scenario_type` is one of: `discontinued_swap`, `missing_required_part`, `discount_category_mismatch`, `duplicate_pair`, `revision_pair`, `clean_distinct`.

## Graph schema (minimal, Phase 1 only)

`graph_export.py` emits only what `catalog_gen.py` and `customer_gen.py` actually produce:

- Nodes: `SKU`, `Customer`, `Contract`, `Category`.
- Edges: `REPLACED_BY` (SKU to SKU), `REQUIRES` (SKU to SKU), `COVERS` (Contract to Category), `BELONGS_TO` (SKU to Category).

This is deliberately not the full 10-node/15-edge-type schema mentioned in `docs/roadmap.md`'s Phase 4 description. That fuller schema gets defined in Phase 4's own spec, once there is a knowledge-graph consumer to justify each edge type; this file's job is only to export what Phase 1's data actually contains. Output format: `backend/data/graph/nodes.json` and `backend/data/graph/edges.json`, each a flat JSON array of `{id, label, properties}` (nodes) or `{from, to, type, properties}` (edges), loadable into Neo4j once it exists.

## Scenario generation workflow

`scenario_gen.py` does not call an LLM API directly. It has three steps:

1. **Case selection (programmatic).** For each of the 6 scenario types, pick 10 concrete cases from the already-generated catalog and customer data (e.g. a real discontinued SKU with a real `replaced_by` target, a real customer whose contract does not cover a category they are about to request). This step decides every fact; it never depends on the LLM.
2. **Prompt generation.** Render each batch of same-type cases into the template at `docs/prompts/scenarios_gen_prompt.md`, substituting `{{BATCH_CASES_JSON}}`. Write each batch to `backend/data/prompts/batch_NNN.md`. You paste that file's content into a chat platform (Claude, ChatGPT, or similar) and save the raw reply to `backend/data/responses/batch_NNN.json`.
3. **Ingest.** Parse each response file as a JSON array, match entries back to their `case_id`s. Reject (and report by `case_id`) anything that: is missing from the response, fails JSON parsing for the whole batch, or has `email_text` that mentions the scenario type or otherwise leaks the label. Rejected cases are re-batched into a new prompt file automatically; nothing is hand-edited. Ingest only completes once every case_id across all batches has an accepted `email_text`, at which point it writes `backend/data/scenarios.json`.

## Error handling

- Generators fail loud on invalid config (count of 0 or negative, missing seed) rather than silently defaulting.
- No generator silently overwrites existing output; re-running requires an explicit `--force` flag or a clean `backend/data/` directory.
- Ingest never repairs a bad LLM reply. It only classifies each case as accepted or rejected and re-batches rejects; a human never edits generated email text by hand, so every email in the final dataset actually came from the model.
- `validate.py` reports every failing check by name, not a single generic failure message.

## validate.py checks

- **Referential integrity**: every `replaced_by` and `requires` reference in the catalog points to a SKU that exists; every `contract_id`/`covered_categories` reference used by a scenario case points to a customer/contract that exists; every scenario case's entity references resolve.
- **Scenario coverage**: exactly 10 cases per scenario type, all 60 with a non-empty `email_text`, no duplicate `case_id`s, no case still marked rejected.
- **Determinism check**: running the full pipeline twice with the same seed produces identical `catalog.json` and `customers.json` (byte-for-byte or structurally-equal comparison; exact comparison method left to the implementation plan).

Exit code 0 only if every check passes; otherwise exit non-zero with the list of failing checks.

## Testing

Unit tests (`pytest`) per generator, no test calls a real LLM:

- `catalog_gen.py`: every `replaced_by` target exists and is not discontinued; every `requires` target exists.
- `customer_gen.py`: every customer has at least one contact, site, and contract; contract `effective_from` precedes `effective_to`.
- `graph_export.py`: node and edge counts match the input catalog/customer counts (e.g. one `BELONGS_TO` edge per SKU).
- `scenario_gen.py` case selection: exactly 10 cases per type, no duplicate `case_id`s.
- `scenario_gen.py` ingest: tested against fixture response files covering a valid batch, a malformed-JSON batch, and a label-leaking case, asserting each is accepted or rejected correctly.

## Open items for the implementation plan

- Exact file format for the `backend/data/` sample checked into git for later phases' tests (deferred to whenever Phase 2 needs it).
- Exact byte-for-byte vs structural-equality method for the determinism check.

Nothing else is open; every other question raised during design was resolved above.
