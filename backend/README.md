# Backend

Synthetic data generation for the Phase 1 POC (see the repo root `README.md` and
`docs/adr/` for the overall system design). This directory has no application code yet,
only the `scripts/data_gen/` pipeline that produces a structurally realistic dataset
(catalog, customers, graph, scenarios) for downstream components to work against.

## Setup

Requires `uv` (Python 3.11+). Install dependencies from `backend/`:

```
uv sync
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

Output lands in `backend/data/` (gitignored; regenerate rather than commit it).

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
