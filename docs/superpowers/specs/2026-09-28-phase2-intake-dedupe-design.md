# Phase 2: Intake and Dedupe, Design Spec

Written 2026-09-28. Implements Phase 2 of `docs/roadmap.md`. Read `README.md`, the 4 ADRs in `docs/adr/`, and Phase 1's spec/plan first if you have not: this spec assumes Postgres+pgvector (ADR-0001), no Redis/`procrastinate` for queueing (ADR-0003), and Phase 1's generated dataset (`backend/data/{catalog,customers,scenarios}.json`) without repeating that reasoning.

## Purpose

Two things a real quote-request pipeline needs before any pricing or agent logic can run: turn a raw email into structured data, and catch the same job arriving twice (verbatim or reworded) or as a legitimate follow-up revision, before it wastes a rep's time twice. Phase 1 built the synthetic emails this phase is tested against, including 5 planted duplicate pairs and 5 planted revision pairs. This is also the first phase with real running application code: Postgres, a thin FastAPI surface, and the route/service/repo layering `docs/backend-structure.txt` fixes as this project's convention.

## Scope

In scope: Postgres stood up via Docker Compose (pgvector image); Alembic migrations; a one-time loader for Phase 1's flat JSON into relational tables (`skus`, `customers`, `contracts`, `sites`); the intake service (email text to structured `QuoteRequest`, via a live OpenAI structured-extraction call); an entity-resolution step (extracted names to real IDs); the dedupe service (blocking, two fingerprints, classifier); thin API routes for both.

Out of scope: Neo4j (Phase 4 adds its own `docker-compose.yml` service once there's a graph consumer); the LangGraph agent loop (Phase 3); any pricing logic; a frontend (Phase 7); calibrated confidence thresholds via a golden set (Phase 5's methodology — Phase 2's thresholds are justified directly against Phase 1's 60 known-label cases, not a separately calibrated golden set).

## Done when

Per `docs/roadmap.md`: the dedupe classifier correctly labels Phase 1's scenario set against its known ground truth — `duplicate_pair` cases as `DUPLICATE_OF`, `revision_pair` cases as `REVISION_OF`, everything else (`discontinued_swap`, `missing_required_part`, `discount_category_mismatch`, `clean_distinct`) as `DISTINCT`. Intake correctly extracts a `QuoteRequest` (customer, line items) from all 60 emails, with entity resolution correctly matching extracted names back to real `customer_id`/`sku_id` values.

## Infrastructure

**`docker-compose.yml`** (repo root, new): one service, Postgres with the `pgvector/pgvector` image (a Postgres image with the pgvector extension pre-built in, so `CREATE EXTENSION vector` works without a separate install step). Named volume for data persistence across restarts. Run via `docker compose up -d`; this project's dev environment runs Docker through WSL, not the Windows-native Docker Desktop pipe, so no command in this plan invokes `docker` directly — that's a step for you to run, not the implementation plan.

**Alembic**: `backend/migrations/` (env.py, `versions/`), driven by `DATABASE_URL` from `core/config`. First migration creates all tables listed under Data Model below in one revision, since they ship together.

**Config and secrets**: `core/config/settings.py`, a `pydantic-settings` `Settings` class reading `DATABASE_URL` and `OPENAI_API_KEY` from the environment (`.env` loaded via `python-dotenv`/`pydantic-settings`'s built-in support). `backend/.env` already holds `OPENAI_API_KEY` (added by you, for other work, alongside settings for an unrelated project) — the app reads only the env var name it needs; nothing in this plan touches, prints, or commits that file's contents. `backend/.env.example` is added (checked in) listing every variable name the app reads, with placeholder values, so a clone knows what to set without seeing real secrets.

## Data model

**Reference tables** (loaded once from Phase 1's JSON, read-only from the app's perspective after that):

- `skus`: `sku_id (pk), name, category, list_price, discontinued (bool), replaced_by (fk to skus.sku_id, nullable), in_stock (bool)`. (`requires` is a many-to-many relationship; Phase 2 doesn't need to query it, so it stays in `backend/data/graph/edges.json` rather than getting its own join table — reintroduce it when a phase actually queries it.)
- `customers`: `customer_id (pk), name, account_tier`.
- `sites`: `site_id (pk), customer_id (fk), address, zip`.
- `contracts`: `contract_id (pk), customer_id (fk), discount_category, covered_categories (text[]), effective_from (date), effective_to (date)`.

**App tables** (written by this phase's own code):

- `quote_requests`: `id (uuid pk), case_id (text, nullable — Phase 1's case_id when the source is a synthetic scenario, null for anything else), customer_id (fk, nullable until resolved), site_id (fk, nullable), contract_id (fk, nullable), raw_email_text (text), parsed_json (jsonb — the full extracted `QuoteRequest`), content_fingerprint (jsonb — sorted resolved `sku_id` list), style_fingerprint (jsonb — normalized line-token set from `raw_email_text`), created_at (timestamptz, default now)`.
- `dedupe_verdicts`: `id (uuid pk), quote_request_id (fk), candidate_quote_request_id (fk), verdict (text: `DUPLICATE_OF` / `REVISION_OF` / `DISTINCT`), content_jaccard (float), style_jaccard (float), signals_fired (text[] — e.g. `identical_sku_set`, `same_contract`, `superset_relation`), created_at (timestamptz, default now)`. A verdict row is written for every candidate pair scored, including `DISTINCT` ones with a nonzero score, so the classifier's reasoning is inspectable later, not just its final label — reversible/auditable per the entity-resolution research (`docs/research/entity-resolution-and-dedupe.md`), never a destructive merge.

## Loader script

`backend/scripts/load_data.py`: reads `backend/data/{catalog,customers}.json`, inserts into `skus`/`customers`/`sites`/`contracts`. Idempotent (upsert on primary key, safe to rerun after a `docker compose down -v` and back up). Not part of the request-serving app; run once per fresh database, same spirit as Phase 1's `run_pipeline.py`.

## Intake

**`QuoteRequest` schema** (`app/intake/schemas.py`, Pydantic): `customer_name_as_written (str), contact_name_as_written (str | None), site_hint (str | None — raw text mention of an address/site, unresolved), line_items (list of {sku_name_as_written: str, quantity: str | None — kept as free text since customers write "a couple"/"about 20", not always an int}), requested_by (str | None), raw_text (str)`.

**Extraction call** (`core/llm/openai_client.py` + `app/intake/service.py`): one call to the OpenAI Python SDK per email, `response_format` constrained to the `QuoteRequest` JSON schema (structured outputs — the model cannot return malformed JSON, only a schema-valid or empty result). No LangGraph here: this is a single extraction call, not an agent loop; Phase 3's actual agent loop adopts LangGraph separately, for tool-calling over multiple steps, which this task doesn't need.

**Entity resolution** (`app/intake/service.py`, after extraction): exact case-insensitive match against `customers.name` and `skus.name` first (Phase 1's generation prompt forbids the model from inventing or renaming entities, so exact match is expected to resolve the large majority of cases). Falls back to fuzzy match (`rapidfuzz`, token-sort ratio, threshold 90) for a customer's informal shorthand (e.g. "Zenith" for "Zenith Contractors") or minor SKU wording drift. A `line_item` whose `sku_name_as_written` resolves to zero or multiple candidates above threshold is kept unresolved (`sku_id: null` on that line item) rather than guessed; an unresolved line item does not block the rest of the `QuoteRequest` from being stored, but excludes that SKU from the content fingerprint (an unresolved item can't be compared for equality/superset against anything).

## Dedupe

**Blocking**: candidates for comparison against a new `quote_request` are every existing `quote_request` sharing the same resolved `customer_id`, OR sharing the same `site_id`, OR linked to the same `contract_id` (the "graph relationship" signal from the roadmap — Phase 4's Neo4j isn't up yet, so this reads directly from the `contracts`/`sites` foreign keys already in Postgres, which is the same relationship a graph traversal would find, just via a SQL join instead of Cypher). No blocking key produces an all-customers-in-one-block situation at this dataset's scale (125 customers), so no oversized-block skip logic is needed yet; the Apify research's skip-oversized-blocks concern is a note for when this scales past this POC, not a Phase 2 requirement.

**Fingerprints**, computed once at intake time and stored on the `quote_requests` row:
- **Content** ("what"): the sorted set of resolved `sku_id`s across all line items. `content_jaccard(A, B) = |A ∩ B| / |A ∪ B|`.
- **Style** ("how"): normalized line-token set of `raw_email_text` (lowercase, whitespace-collapsed, split on lines, stopword-stripped). `style_jaccard(A, B)` computed the same way. Used only as a confidence booster/tie-breaker, never as the primary signal — see rationale below.

**Classifier** (`app/dedupe/service.py`), run against every blocked candidate:

1. `content_jaccard == 1.0` (identical resolved SKU sets) → `DUPLICATE_OF`.
2. One request's SKU set is a strict superset of the other's, and `content_jaccard >= 0.4` → `REVISION_OF`. (The 0.4 floor exists so a request sharing only one incidental SKU with a much larger, otherwise-unrelated order isn't misread as a revision of it; Phase 1's `revision_pair` cases add exactly one SKU to a 1-2-item original, so their true Jaccard lands at 0.5-0.67, comfortably clear of that floor.)
3. Otherwise → `DISTINCT`.

`style_jaccard` is recorded on every verdict row for inspection but does not change steps 1-3's outcome in this phase: Phase 1's ground truth was built from the SKU-set relationship directly (see Phase 1's `scenario_gen.py`, `_select_duplicate_pair`/`_select_revision_pair`), so a rule keyed on that relationship is the correct thing to test against, not a heuristic layered on top of it. Promoting `style_jaccard` to a primary signal (e.g. to catch a duplicate whose intake extraction mis-resolved one SKU differently between the two copies) is a reasonable future refinement, flagged under Open Items, not built now — building it without a labeled case that actually needs it would be speculative.

**Known scope limit**: Phase 1's data carries no timestamp on a request, so nothing here can distinguish a true duplicate from a customer legitimately reordering the identical parts weeks later. Accepted: Phase 1's own ground truth doesn't model separate time windows either, so this doesn't affect the done-when criterion. Revisit if/when request timestamps enter the data model.

## API

Thin routes, matching `docs/backend-structure.txt`'s route → service → repo convention:

- `POST /v1/intake` — body `{email_text: str}`, returns the stored `QuoteRequest` (with resolution results) and its assigned `quote_request_id`.
- `POST /v1/dedupe/{quote_request_id}` — runs blocking + classification for that request against existing ones, returns the list of `dedupe_verdicts` produced (typically 0 candidates for most requests, 1 for a genuine duplicate/revision pair).

No route composes the two yet (e.g. "submit an email and get a verdict back in one call") — that orchestration is Phase 3's agent loop's job once it exists; Phase 2 exposes the two capabilities independently so each is independently testable.

## Error handling

- Intake: an OpenAI call that fails (network, rate limit, schema violation) is not silently swallowed — the route returns an error response naming the failure; no partial/guessed `QuoteRequest` is ever stored.
- Entity resolution: an unresolved line item is stored as unresolved (`sku_id: null`), not dropped and not guessed. A `QuoteRequest` with zero resolved line items still gets stored (so it's visible for manual follow-up) but is excluded from dedupe blocking, since it can't be meaningfully compared.
- Loader script: upsert semantics, safe to rerun; fails loud (not silently skips) on a referential-integrity problem in the source JSON, matching Phase 1's `validate.py` philosophy.
- Dedupe: every scored candidate pair gets a `dedupe_verdicts` row, including `DISTINCT` ones, so "why wasn't this flagged" is always answerable from data already stored, not by re-running the classifier.

## Testing

No test calls a real OpenAI API. Intake's LLM call is mocked/stubbed in unit tests (fixed fake responses covering a clean extraction, a partially-unresolved extraction, and an API failure); a small number of tests may run against the real API as an explicit, separately-run integration check (not part of the default `pytest` run), since Phase 1's convention (no live LLM calls in the default test suite) carries forward.

- Entity resolution: exact match, fuzzy match above/below threshold, zero-candidate and multi-candidate-tie cases.
- Dedupe classifier: unit tests using constructed fixtures for identical/superset/disjoint SKU sets, plus an end-to-end test running the classifier against Phase 1's actual `duplicate_pair`/`revision_pair`/`clean_distinct` cases from `backend/data/scenarios.json` (loaded and resolved via a test-only fixture, not live intake) and asserting the verdicts match Phase 1's known labels for all of them — this is the direct test of this phase's done-when criterion.
- Blocking: a candidate sharing only a `contract_id` (not `customer_id`/`site_id`) is still returned.

## Open items for the implementation plan

- Exact `rapidfuzz` fuzzy-match threshold (90 above is a starting point; the implementation plan tunes it against real false-match/miss cases found while testing against `scenarios.json`).
- Whether `style_jaccard` ever gets promoted to a primary signal — deferred until a labeled case exists that the SKU-set rule alone gets wrong.
- Neo4j-backed blocking (replacing the SQL-join relationship check with a real graph traversal) is explicitly Phase 4's job, not this phase's.

Nothing else is open; every other question raised during design was resolved above.
