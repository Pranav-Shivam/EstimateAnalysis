# Backend

Synthetic data generation for the Phase 1 POC (see the repo root `README.md` and
`docs/adr/` for the overall system design), plus the Phase 2 intake and dedupe
application (FastAPI routes over a service/repository layering; see the Phase 2
section below). The `scripts/data_gen/` pipeline produces a structurally realistic
dataset (catalog, customers, graph, scenarios) for downstream components to work
against.

## Setup

Requires `uv` (Python 3.11+). All commands in this README are run from `backend/`,
since settings load `.env` relative to the current working directory.

Install dependencies:

```
uv sync
```

Copy the example environment file and fill in real values before running anything
that touches Postgres or OpenAI:

```
cp .env.example .env
```

## Running the data generation pipeline

All commands below are run from `backend/`. Each script resolves its own output paths
relative to `backend/data/` regardless of your current directory, so `--data-dir`/`--out`
defaults are correct whether you invoke a script via `uv run python scripts/data_gen/...`
or via `python -m data_gen....`.

Run the full pipeline (catalog, customers, graph export) in one step:

```
uv run python scripts/data_gen/run_pipeline.py
```

Pass `--force` to overwrite existing output files:

```
uv run python scripts/data_gen/run_pipeline.py --force
```

Individual steps can also be run on their own:

```
uv run python scripts/data_gen/catalog_gen.py --force
uv run python scripts/data_gen/customer_gen.py --force
uv run python scripts/data_gen/graph_export.py --force
```

Validate a generated dataset (referential integrity, scenario coverage):

```
uv run python scripts/data_gen/validate.py
```

Output lands in `backend/data/` (committed to the repo as the synthetic dataset used
by later phases; regenerate with `--force` rather than hand-editing it).

## Running the test suite

```
uv run pytest -v
```

## Phase 2: Intake and dedupe

Prerequisites: Postgres running (`docker compose up -d` from the repo root, via WSL), `OPENAI_API_KEY` set in `backend/.env`.

One-time setup:
```
uv run alembic upgrade head
uv run python scripts/load_data.py
```

Run the API:
```
uv run python main.py
```

`POST /v1/intake` with `{"email_text": "..."}` extracts and stores a structured quote request.
`POST /v1/dedupe/{quote_request_id}` classifies it against existing requests as `DUPLICATE_OF`, `REVISION_OF`, or `DISTINCT`.

## Phase 3: Agent, pricing tools, guardrails

Prerequisites: everything from Phase 2, plus the pricing data generated and loaded:
```
uv run python scripts/data_gen/price_gen.py          # writes data/pricing.json (already committed)
uv run alembic upgrade head                          # migration 0002
uv run python scripts/load_data.py                   # loads requirements, discounts, price gaps, history
```

`POST /v1/estimate` with `{"quote_request_id": "<uuid>", "as_of": "2024-09-01"}` (`as_of` optional, defaults to
`DATASET_AS_OF`) runs the LangGraph agent over a stored quote request and returns a priced draft with status `ready`
or `needs_review`, plus any guardrail violations. The agent calls OpenAI (real API cost); the test suite never does.

The guardrails (contract discount, required fields, price provenance) are plain functions in
`app/estimate/guardrails.py`. `tests/test_phase3_acceptance.py` proves that a discount on an uncovered category is
blocked for all 10 planted `discount_category_mismatch` cases.
