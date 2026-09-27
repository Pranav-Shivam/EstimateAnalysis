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
