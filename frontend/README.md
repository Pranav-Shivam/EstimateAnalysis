# Estimate Review UI

The reviewer's screen for the quote estimation agent. It has a live knowledge-graph explorer (search a node, click to expand its neighbors one hop at a time, deep-linked from each review item's evidence) and a dashboard with bar charts of flags by dimension and graph node and edge counts by type. It also shows the review queue (one flagged fact per item, with the evidence the judge saw), a quote detail view (email, dedupe verdicts, every estimate with its judge scores), an all-quotes list, and a dashboard with the three tracked rates. A reviewer can approve a flagged item or correct it; the correction goes through the existing `POST /v1/review/{id}/resolve` route and is consolidated into the reference data by the backend worker.

## Prerequisites

- Node 20.19+ or 22.12+ (Vite 8 requirement).
- Postgres and Neo4j running: `docker compose up -d` from the repo root.
- Backend migrated and loaded, from `backend/`: `uv run alembic upgrade head` then `uv run python scripts/load_data.py`.

## Run

```bash
cd backend && uv run python scripts/seed_demo.py --yes    # demo quotes; plants a graph gap and a price gap
cd backend && uv run python main.py                       # API on :8000
cd frontend && npm install && npm run dev                 # UI on :5173
```

`seed_demo.py` without `--yes` is a dry run. After correcting flags in the UI, run `uv run python scripts/seed_demo.py --replay --yes` from `backend/` to re-run estimate and judge for the corrected quotes; the quote detail then shows a second, clean estimate.

The API URL comes from `VITE_API_URL` (default `http://localhost:8000`). The backend allows the origin in its `cors_allowed_origins` setting (default `http://localhost:5173`).

## API types

Types are generated from the backend's OpenAPI schema, so a backend change that breaks the UI fails `tsc` instead of the browser.

- `npm run gen:api` regenerates `src/api/schema.d.ts` (commit the result).
- `npm run check:api` fails if the committed file differs from what the backend would generate now.

## Test and build

```bash
npm test               # Vitest + Testing Library, the API mocked at the fetch boundary
npx tsc --noEmit       # the static gate (there is no ESLint)
npm run build
```

## Versions

Latest stable at install time (2026-09-30): react 19.3.0, react-router 8.4.0, vite 8.3.1, tailwindcss 4.3.3, antd 6.6.5, @tanstack/react-query 5.104.0, openapi-fetch 0.17.0, openapi-typescript 7.13.0, vitest 5.0.2.

TypeScript is pinned to 5.9.3, not the latest 7.0.2: `openapi-typescript` 7.13 needs the JavaScript compiler API (peer `typescript ^5.x`), which TypeScript 7 does not ship, and crashed on load with it. Lift the pin when openapi-typescript supports 7.

## Tailwind 4 with Ant Design 6

Both libraries style the same elements, and Tailwind's reset would override antd. `main.tsx` wraps the app in `StyleProvider layer` so antd emits its CSS inside an `@layer`, and `src/index.css` declares `@layer theme, base, antd, components, utilities;` before `@import "tailwindcss"`. The reset then sits below antd, and Tailwind utilities sit above it. Layout uses Tailwind flex and grid rather than antd `Space`, which changed its API in v6. Source: `docs/research/frontend-stack-versions.md`.

## Known gaps

- No UI to trigger intake, dedupe, estimate or judge (those call paid LLM APIs; the seed script covers data).
- Guardrail-blocked drafts (dimension `guardrail`) are shown read-only; the backend rejects resolving them.
- The evidence panel shows the snapshot the judge stored, not a live graph query. Its "View in graph" link opens the live explorer on that SKU.
- The explorer returns at most 60 neighbors of a node (a category or family hub has hundreds) and says so when it cuts; it has no multi-hop path search.
- No authentication; CORS is origin-scoped only.
- The seed script's judge is a scripted stand-in, so the demo proves the correction-to-clean plumbing, not a real model's judgment.
