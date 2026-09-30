# Phase 7 Review Queue UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A reviewer can open a React app, see a flagged quote in a queue, inspect its evidence, approve or correct it, and then see a later clean estimate for the same quote, backed by new read-only backend endpoints and a seed script.

**Architecture:** FastAPI gains read-only modules (`app/quotes`, `app/metrics`), a review status filter and CORS. A seed script drives the real intake, dedupe, estimate and judge services with scripted stand-ins for the three LLM clients. A new `frontend/` app (Vite, React, TypeScript, Tailwind 4, Ant Design 6, TanStack Query) renders the queue, quote detail and dashboard from OpenAPI-generated types.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2, pytest, Postgres 5433, Neo4j 17687; React 19.3, Vite 8, TypeScript, Tailwind 4.3, antd 6, TanStack Query 5, react-router, Vitest 5, Testing Library, openapi-typescript / openapi-fetch.

**Spec:** `docs/superpowers/specs/2026-09-30-phase7-review-ui-design.md`. Versions and the Tailwind + antd layer setup: `docs/research/frontend-stack-versions.md`.

## Global Constraints

- No em dash anywhere in the repo (code, comments, prose, commit messages). No emojis.
- Commits and PRs never mention Claude, Anthropic or any AI tool, and carry no Co-Authored-By trailer. This overrides any default attribution.
- Code reads like a senior engineer wrote it: no dead code, no unexplained magic, no TODOs.
- Backend layer order: route -> service -> repository -> DB. Files per `docs/backend-structure.txt` and the existing modules: `route.py`, `request.py`, `response.py` under `api/v1/<module>/`; `service.py`, `repository.py`, `schemas.py`, `constant.py` under `app/<module>/`. Routes are plain `def`, not `async def`.
- No new write endpoint. The UI's only writes go through the existing `POST /v1/review/{review_item_id}/resolve`.
- No real OpenAI, Anthropic or Langfuse network calls anywhere, in tests or in the seed script.
- Tests share the real Postgres (`DATABASE_URL`) inside a rolled-back transaction, so the database may already hold committed demo data. Tests must assert on rows they created or on before/after deltas, never on absolute table totals.
- The `created_at` column uses `server_default=func.now()`, which is the transaction start time, so rows created in one test transaction share a timestamp. Tests that depend on ordering must set `created_at` explicitly (helper `_stamp` below).
- Frontend: latest stable versions installed with `npm install <pkg>` (caret-pinned by npm to what the registry serves). Node `^20.19 || >=22.12` (local is 24.16).
- Frontend styles: `StyleProvider layer` plus `@layer theme, base, antd, components, utilities;` before `@import "tailwindcss"` (verified in the research doc).
- Run backend commands from `backend/` with `uv run`. Run frontend commands from `frontend/`.
- Rate definitions, which the dashboard captions state in words: auto-send = trusted judge verdicts / all judge verdicts; correction = corrected review items / resolved review items; duplicate = requests with a `DUPLICATE_OF` verdict / requests that have any dedupe verdict. A rate is `null`, never 0, when its denominator is 0.
- Guardrail-path review items (dimension `guardrail`) are read-only in the UI: no Approve or Correct buttons.

## Review Focus

Failure modes the spec implies that no single task's happy path exercises. Each has a pinned test in the owning task.

1. A quote request with no estimate yet, or an estimate with no judge verdict (the seed's duplicate-pair member, or a run that failed mid-pipeline): the list and detail endpoints must return it with null verdict fields, not 500. Pinned in Task 3.
2. A `needs_review` estimate has `draft = null`: the detail endpoint and the lines table must handle no draft. Pinned in Tasks 3 and 12, and end to end in Task 14.
3. Resolving an item that was already resolved (409), or with a bad correction (422): the UI must show the backend's `detail` string verbatim, not a generic error. Guardrail items (which the backend rejects with 400) never offer the action at all. Pinned in Tasks 13 and 14.
4. Metrics on an empty (or all-zero-denominator) database: rates are `null` and the dashboard says "no data yet", never "0%" or NaN. Pinned in Tasks 4 and 15.
5. A correction submitted for a price of `0`, negative, `NaN`, `Infinity`, `1e3`, hex or empty text, or a required SKU equal to the flagged SKU: the form blocks it before the network call, mirroring the backend shapes. Pinned in Tasks 11 and 13.

---

## File Structure

Backend (new unless marked):

- `backend/core/config/settings.py` (modify): `cors_allowed_origins`.
- `backend/main.py` (modify): CORS middleware, new routers.
- `backend/app/judge/repository.py` (modify): `list_review_items(session, status)` replaces `list_open_review_items`.
- `backend/app/estimate/repository.py` (modify): `quote_request_ids_for_estimates`.
- `backend/api/v1/review/route.py`, `response.py` (modify): status filter, resolved fields, `quote_request_id`.
- `backend/app/quotes/{__init__,schemas,repository,service}.py`; `backend/api/v1/quotes/{__init__,route,response}.py`.
- `backend/app/metrics/{__init__,schemas,repository,service}.py`; `backend/api/v1/metrics/{__init__,route,response}.py`.
- `backend/scripts/export_openapi.py`: writes the OpenAPI JSON for the frontend type generator.
- `backend/scripts/load_data.py` (modify): extract `load_all(session, data_dir)` from `run()`.
- `backend/scripts/demo/{__init__,fakes,scenarios,seed}.py` and `backend/scripts/seed_demo.py`.
- Tests mirror each module under `backend/tests/`.

Frontend (`frontend/`):

- Config: `package.json`, `vite.config.ts`, `tsconfig.json`, `tsconfig.node.json`, `eslint.config.js`, `index.html`, `.gitignore`, `README.md`.
- `src/main.tsx`, `src/App.tsx`, `src/index.css`.
- `src/api/{client,types,queries,schema.d.ts}` (`schema.d.ts` generated).
- `src/lib/{format,correction}.ts`.
- `src/components/{EvidencePanel,EstimateLinesTable,DedupeVerdicts,JudgePanel,FlaggedFactCard,CorrectionForm,EstimateHistory}.tsx`.
- `src/pages/{QueuePage,QuoteDetailPage,DashboardPage}.tsx`.
- `src/test/{setup.ts,render.tsx}`.
- `scripts/check-api-types.mjs`.

---

## Task 1: CORS

**Files:**
- Modify: `backend/core/config/settings.py`
- Modify: `backend/main.py`
- Create: `backend/tests/api/v1/test_cors.py`

**Interfaces:**
- Produces: `Settings.cors_allowed_origins: list[str]` (default `["http://localhost:5173"]`), overridable by env `CORS_ALLOWED_ORIGINS` as a JSON list.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/api/v1/test_cors.py`:

```python
from fastapi.testclient import TestClient

from main import app

ALLOWED = "http://localhost:5173"


def _preflight(origin: str):
    return TestClient(app).options(
        "/v1/review",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )


def test_preflight_from_the_allowed_origin_is_accepted():
    response = _preflight(ALLOWED)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED


def test_preflight_from_another_origin_is_rejected():
    response = _preflight("http://evil.example")

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest tests/api/v1/test_cors.py -v`
Expected: `test_preflight_from_the_allowed_origin_is_accepted` FAILS (405 or missing header).

- [ ] **Step 3: Implement**

In `backend/core/config/settings.py` add after `langfuse_host`:

```python
    # The Vite dev server's origin. The API has no auth, so CORS is the only browser-side gate.
    cors_allowed_origins: list[str] = ["http://localhost:5173"]
```

In `backend/main.py` add imports and the middleware:

```python
from fastapi.middleware.cors import CORSMiddleware
```
```python
from core.config.settings import Settings
```
and after `app = FastAPI(...)`:

```python
app.add_middleware(
    CORSMiddleware, allow_origins=Settings().cors_allowed_origins, allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd backend && uv run pytest tests/api/v1/test_cors.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/core/config/settings.py backend/main.py backend/tests/api/v1/test_cors.py
git commit -m "feat: allow the frontend origin through CORS"
```

---

## Task 2: Review status filter

**Files:**
- Modify: `backend/app/judge/repository.py:40-47`
- Modify: `backend/app/estimate/repository.py` (append)
- Modify: `backend/api/v1/review/route.py:19-27`
- Modify: `backend/api/v1/review/response.py`
- Modify: `backend/tests/app/judge/test_repository.py:6,50`
- Test: `backend/tests/api/v1/test_review_route.py`

**Interfaces:**
- Produces: `list_review_items(session: Session, status: Literal["open","resolved","all"] = "open") -> list[ReviewItemRow]` in `app.judge.repository` (replaces `list_open_review_items`).
- Produces: `quote_request_ids_for_estimates(session: Session, estimate_ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]` in `app.estimate.repository`.
- Produces: `GET /v1/review?status=open|resolved|all` returning `ReviewItemListResponse` with new fields `quote_request_id: uuid.UUID`, `outcome: str | None`, `correction: dict | None`, `resolved_at: datetime | None`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/api/v1/test_review_route.py`:

```python
def _get(session, query=""):
    app.dependency_overrides[get_session] = lambda: session
    try:
        return TestClient(app).get(f"/v1/review{query}")
    finally:
        app.dependency_overrides.clear()


def _resolve(item):
    item.status = "corrected"
    item.outcome = "corrected"
    item.correction = {"sku_id": "SKU-E-A1", "required_sku_id": "SKU-E-B1"}


def test_review_endpoint_default_excludes_resolved_items(db_session):
    open_item = _open_review_item(db_session)
    resolved_item = _open_review_item(db_session)
    _resolve(resolved_item)
    db_session.flush()

    ids = [row["id"] for row in _get(db_session).json()]

    assert str(open_item.id) in ids
    assert str(resolved_item.id) not in ids


def test_review_endpoint_resolved_filter_returns_outcome_and_correction(db_session):
    open_item = _open_review_item(db_session)
    resolved_item = _open_review_item(db_session)
    _resolve(resolved_item)
    db_session.flush()

    rows = {row["id"]: row for row in _get(db_session, "?status=resolved").json()}

    assert str(open_item.id) not in rows
    assert rows[str(resolved_item.id)]["outcome"] == "corrected"
    assert rows[str(resolved_item.id)]["correction"] == {"sku_id": "SKU-E-A1", "required_sku_id": "SKU-E-B1"}


def test_review_endpoint_all_filter_returns_both(db_session):
    open_item = _open_review_item(db_session)
    resolved_item = _open_review_item(db_session)
    _resolve(resolved_item)
    db_session.flush()

    ids = [row["id"] for row in _get(db_session, "?status=all").json()]

    assert str(open_item.id) in ids
    assert str(resolved_item.id) in ids


def test_review_endpoint_includes_the_quote_request_id(db_session):
    item = _open_review_item(db_session)
    db_session.flush()

    row = next(r for r in _get(db_session).json() if r["id"] == str(item.id))

    assert row["quote_request_id"] is not None


def test_review_endpoint_rejects_an_unknown_status(db_session):
    assert _get(db_session, "?status=bogus").status_code == 422
```

`_open_review_item` calls `seed_world` each time; the second call upserts, which is safe.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/api/v1/test_review_route.py -v`
Expected: new tests FAIL (no filter, missing fields).

- [ ] **Step 3: Implement the repository changes**

In `backend/app/judge/repository.py` replace `list_open_review_items` with:

```python
def list_review_items(session: Session, status: Literal["open", "resolved", "all"] = "open") -> list[ReviewItemRow]:
    statement = select(ReviewItemRow).order_by(ReviewItemRow.created_at, ReviewItemRow.id)
    if status == "open":
        statement = statement.where(ReviewItemRow.status == "open")
    elif status == "resolved":
        statement = statement.where(ReviewItemRow.status != "open")
    return list(session.scalars(statement))
```

and add `from typing import Literal` to its imports.

In `backend/tests/app/judge/test_repository.py` change the import to `list_review_items` and the call at line 50 to `list_review_items(db_session, "open")`.

Append to `backend/app/estimate/repository.py`:

```python
def quote_request_ids_for_estimates(session: Session, estimate_ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    if not estimate_ids:
        return {}
    rows = session.execute(
        select(EstimateDraftRow.id, EstimateDraftRow.quote_request_id).where(EstimateDraftRow.id.in_(estimate_ids))
    )
    return {estimate_id: quote_request_id for estimate_id, quote_request_id in rows}
```

- [ ] **Step 4: Implement the route and response**

Replace `backend/api/v1/review/response.py`'s `ReviewItemListResponse` with:

```python
class ReviewItemListResponse(BaseModel):
    id: uuid.UUID
    estimate_id: uuid.UUID
    quote_request_id: uuid.UUID
    dimension: str
    fact: str
    evidence: dict
    line_index: int | None
    status: str
    outcome: str | None
    correction: dict | None
    resolved_at: datetime | None
    created_at: datetime
```

Replace `list_review_items` in `backend/api/v1/review/route.py` (add `from typing import Literal`, change the repository import to `list_review_items as load_review_items` is NOT needed; name the route function `list_items`):

```python
from app.estimate.repository import quote_request_ids_for_estimates
from app.judge.repository import list_review_items
```
```python
@router.get("", response_model=list[ReviewItemListResponse])
def list_items(
    status: Literal["open", "resolved", "all"] = "open", session: Session = Depends(get_session),
) -> list[ReviewItemListResponse]:
    items = list_review_items(session, status)
    quote_request_ids = quote_request_ids_for_estimates(session, [item.estimate_id for item in items])
    return [
        ReviewItemListResponse(
            id=item.id, estimate_id=item.estimate_id, quote_request_id=quote_request_ids[item.estimate_id],
            dimension=item.dimension, fact=item.fact, evidence=item.evidence, line_index=item.line_index,
            status=item.status, outcome=item.outcome, correction=item.correction, resolved_at=item.resolved_at,
            created_at=item.created_at,
        )
        for item in items
    ]
```

Remove the now-unused `list_open_review_items` import from the route.

- [ ] **Step 5: Run to verify pass**

Run: `cd backend && uv run pytest tests/api/v1/test_review_route.py tests/app/judge/test_repository.py tests/api/v1/test_review_resolve_route.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/judge/repository.py backend/app/estimate/repository.py backend/api/v1/review backend/tests
git commit -m "feat: filter the review list by status and include the quote request id"
```

## Task 3: Quotes read endpoints

**Files:**
- Modify: `backend/app/reference_data/repository.py` (append `skus_by_ids`)
- Create: `backend/app/quotes/__init__.py` (empty), `schemas.py`, `repository.py`, `service.py`
- Create: `backend/api/v1/quotes/__init__.py` (empty), `route.py`, `response.py`
- Modify: `backend/main.py` (register router)
- Test: `backend/tests/api/v1/test_quotes_route.py`

**Interfaces:**
- Consumes: `get_quote_request(session, id)` from `app.intake.repository`; `compute_totals(lines) -> Totals` from `app.estimate.helper`; `EstimateDraft`, `Totals` from `app.estimate.schemas`; `save_quote_request`, `save_estimate_draft`, `save_judge_verdict`, `save_review_item`, `save_verdict` (dedupe) for tests.
- Produces: `GET /v1/quotes` -> `list[QuoteSummaryResponse]`; `GET /v1/quotes/{quote_request_id}` -> `QuoteDetailResponse` (404 `{"detail": ...}` when unknown). `app.quotes.service.list_quotes(session)`, `get_quote_detail(session, quote_request_id)`, `QuoteNotFound`.
- Response field names (the frontend depends on these exactly):
  - `QuoteSummaryResponse`: `quote_request_id, case_id, customer_id, created_at, estimate_count, latest_estimate_status, latest_trusted, open_review_items, is_duplicate`.
  - `QuoteDetailResponse`: `quote_request_id, case_id, customer_id, site_id, contract_id, raw_email_text, parsed_json, created_at, dedupe_verdicts[QuoteDedupeVerdictResponse], estimates[QuoteEstimateResponse], skus{sku_id: QuoteSkuInfoResponse}`.
  - `QuoteEstimateResponse`: `estimate_id, status, draft, totals, violations, iterations, reason, created_at, judge_verdict[QuoteJudgeVerdictResponse|null], review_items[QuoteReviewItemResponse]`.
  - `QuoteDedupeVerdictResponse`: `candidate_quote_request_id, verdict, content_jaccard, style_jaccard, signals_fired, created_at`.
  - `QuoteJudgeVerdictResponse`: `id, model, dimensions[DimensionScore], overall_confidence, flagged_dimension, trusted, created_at`.
  - `QuoteReviewItemResponse`: `id, dimension, fact, evidence, line_index, status, outcome, correction, resolved_at, created_at`.
  - `QuoteSkuInfoResponse`: `name, category, discontinued`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/api/v1/test_quotes_route.py`:

```python
import uuid
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import event

from app.dedupe.repository import save_verdict
from app.estimate.repository import save_estimate_draft
from app.intake.repository import save_quote_request
from app.judge.repository import save_judge_verdict, save_review_item
from core.db.session import get_session
from main import app
from tests.app.estimate.seed import seed_world

# Far in the future so these rows sort ahead of any committed demo data, and stamped explicitly because one
# transaction gives every row the same server-side created_at.
BASE = datetime(2030, 1, 1, 12, 0)
LINE = {"sku_id": "SKU-E-A1", "quantity": 2, "unit_price": 100.0, "price_source": "list", "discount_pct": 0.0}


def _stamp(session, row, minutes):
    row.created_at = BASE + timedelta(minutes=minutes)
    session.flush()


def _request(session, minutes=0, case_id=None):
    row = save_quote_request(
        session, raw_email_text="need parts", parsed_json={"resolved_line_items": []},
        content_fingerprint={}, style_fingerprint={}, case_id=case_id,
    )
    _stamp(session, row, minutes)
    return row


def _estimate(session, request, minutes, status="ready"):
    draft = None if status == "needs_review" else {"customer_id": None, "contract_id": None, "lines": [LINE]}
    row = save_estimate_draft(
        session, quote_request_id=request.id, status=status, draft=draft, violations=[], iterations=1,
        reason="blocked" if status == "needs_review" else None,
    )
    _stamp(session, row, minutes)
    return row


def _verdict(session, estimate, minutes, trusted):
    row = save_judge_verdict(
        session, estimate_id=estimate.id, model="test-judge",
        dimensions=[{"name": "graph_completion", "score": 0.2, "rationale": "thin", "evidence": []}],
        overall_confidence=0.95 if trusted else 0.2, flagged_dimension="graph_completion", trusted=trusted,
    )
    _stamp(session, row, minutes)
    return row


def _item(session, estimate, verdict, evidence=None, status="open"):
    row = save_review_item(
        session, judge_verdict_id=verdict.id, estimate_id=estimate.id, dimension="graph_completion",
        fact="check this", evidence=evidence or {"lines": []}, line_index=0,
    )
    row.status = status
    session.flush()
    return row


def _get(session, path):
    app.dependency_overrides[get_session] = lambda: session
    try:
        return TestClient(app).get(path)
    finally:
        app.dependency_overrides.clear()


def _summary(session, request):
    rows = _get(session, "/v1/quotes").json()
    return next(row for row in rows if row["quote_request_id"] == str(request.id))


def test_list_returns_a_request_with_no_estimate_and_null_verdict_fields(db_session):
    request = _request(db_session)

    row = _summary(db_session, request)

    assert row["estimate_count"] == 0
    assert row["latest_estimate_status"] is None
    assert row["latest_trusted"] is None
    assert row["open_review_items"] == 0
    assert row["is_duplicate"] is False


def test_list_reports_the_latest_estimate_and_its_latest_verdict(db_session):
    seed_world(db_session)
    request = _request(db_session)
    first = _estimate(db_session, request, 1)
    _item(db_session, first, _verdict(db_session, first, 2, trusted=False))
    second = _estimate(db_session, request, 10)
    _verdict(db_session, second, 11, trusted=True)

    row = _summary(db_session, request)

    assert row["estimate_count"] == 2
    assert row["latest_estimate_status"] == "ready"
    assert row["latest_trusted"] is True
    assert row["open_review_items"] == 1


def test_list_handles_an_estimate_that_was_never_judged(db_session):
    request = _request(db_session)
    _estimate(db_session, request, 1)

    row = _summary(db_session, request)

    assert row["latest_estimate_status"] == "ready"
    assert row["latest_trusted"] is None


def test_list_flags_a_request_with_a_duplicate_verdict(db_session):
    original = _request(db_session, 0)
    copy = _request(db_session, 5)
    save_verdict(
        db_session, quote_request_id=copy.id, candidate_quote_request_id=original.id, verdict="DUPLICATE_OF",
        content_jaccard=1.0, style_jaccard=0.9, signals_fired=["identical_sku_set"],
    )

    assert _summary(db_session, copy)["is_duplicate"] is True
    assert _summary(db_session, original)["is_duplicate"] is False


def test_list_uses_a_fixed_number_of_queries(db_session):
    def statements_for_list():
        count = []
        connection = db_session.get_bind()
        listener = lambda *args: count.append(1)
        event.listen(connection, "before_cursor_execute", listener)
        try:
            _get(db_session, "/v1/quotes")
        finally:
            event.remove(connection, "before_cursor_execute", listener)
        return len(count)

    _request(db_session, 0)
    baseline = statements_for_list()
    for minutes in range(1, 6):
        request = _request(db_session, minutes)
        _estimate(db_session, request, minutes)

    assert statements_for_list() == baseline


def test_detail_returns_404_for_an_unknown_request(db_session):
    response = _get(db_session, f"/v1/quotes/{uuid.uuid4()}")

    assert response.status_code == 404


def test_detail_orders_estimates_newest_first_with_their_own_verdicts_and_items(db_session):
    seed_world(db_session)
    request = _request(db_session, case_id="sc-detail")
    first = _estimate(db_session, request, 1)
    first_item = _item(db_session, first, _verdict(db_session, first, 2, trusted=False))
    second = _estimate(db_session, request, 10)
    _verdict(db_session, second, 11, trusted=True)

    body = _get(db_session, f"/v1/quotes/{request.id}").json()

    assert body["case_id"] == "sc-detail"
    assert [e["estimate_id"] for e in body["estimates"]] == [str(second.id), str(first.id)]
    assert body["estimates"][0]["judge_verdict"]["trusted"] is True
    assert body["estimates"][0]["review_items"] == []
    assert body["estimates"][1]["judge_verdict"]["trusted"] is False
    assert [i["id"] for i in body["estimates"][1]["review_items"]] == [str(first_item.id)]
    assert body["estimates"][0]["totals"]["net_total"] == 200.0


def test_detail_handles_a_needs_review_estimate_with_no_draft(db_session):
    request = _request(db_session)
    _estimate(db_session, request, 1, status="needs_review")

    estimate = _get(db_session, f"/v1/quotes/{request.id}").json()["estimates"][0]

    assert estimate["draft"] is None
    assert estimate["totals"] is None
    assert estimate["reason"] == "blocked"
    assert estimate["judge_verdict"] is None


def test_detail_includes_sku_info_for_draft_lines_and_evidence(db_session):
    seed_world(db_session)
    request = _request(db_session)
    estimate = _estimate(db_session, request, 1)
    verdict = _verdict(db_session, estimate, 2, trusted=False)
    _item(db_session, estimate, verdict, evidence={"lines": [
        {"line_index": 0, "sku_id": "SKU-E-A1", "live_sku_id": "SKU-E-A1", "required_part_ids": ["SKU-E-B1"],
         "missing_required_part_ids": ["SKU-E-B1"]},
    ]})

    skus = _get(db_session, f"/v1/quotes/{request.id}").json()["skus"]

    assert skus["SKU-E-A1"] == {"name": "Zorpwidget Alpha 9000", "category": "Cat-E-A", "discontinued": False}
    assert skus["SKU-E-B1"]["category"] == "Cat-E-B"


def test_detail_includes_dedupe_verdicts(db_session):
    original = _request(db_session, 0)
    copy = _request(db_session, 5)
    save_verdict(
        db_session, quote_request_id=copy.id, candidate_quote_request_id=original.id, verdict="DUPLICATE_OF",
        content_jaccard=1.0, style_jaccard=0.9, signals_fired=["identical_sku_set"],
    )

    verdicts = _get(db_session, f"/v1/quotes/{copy.id}").json()["dedupe_verdicts"]

    assert verdicts[0]["verdict"] == "DUPLICATE_OF"
    assert verdicts[0]["candidate_quote_request_id"] == str(original.id)
    assert verdicts[0]["signals_fired"] == ["identical_sku_set"]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/api/v1/test_quotes_route.py -v`
Expected: FAIL with 404 on `/v1/quotes` (route missing).

- [ ] **Step 3: Add `skus_by_ids`**

Append to `backend/app/reference_data/repository.py` (it already imports `select`; add the import only if missing):

```python
def skus_by_ids(session: Session, sku_ids: set[str]) -> list[Sku]:
    if not sku_ids:
        return []
    return list(session.scalars(select(Sku).where(Sku.sku_id.in_(sku_ids))))
```

- [ ] **Step 4: Write `app/quotes/schemas.py`**

```python
import uuid
from dataclasses import dataclass
from datetime import datetime

from app.estimate.schemas import Totals


@dataclass(frozen=True)
class QuoteSummary:
    quote_request_id: uuid.UUID
    case_id: str | None
    customer_id: str | None
    created_at: datetime
    estimate_count: int
    latest_estimate_status: str | None
    latest_trusted: bool | None
    open_review_items: int
    is_duplicate: bool


@dataclass(frozen=True)
class SkuInfo:
    name: str
    category: str
    discontinued: bool


@dataclass(frozen=True)
class DedupeVerdictView:
    candidate_quote_request_id: uuid.UUID
    verdict: str
    content_jaccard: float
    style_jaccard: float
    signals_fired: list[str]
    created_at: datetime


@dataclass(frozen=True)
class JudgeVerdictView:
    id: uuid.UUID
    model: str
    dimensions: list[dict]
    overall_confidence: float
    flagged_dimension: str
    trusted: bool
    created_at: datetime


@dataclass(frozen=True)
class ReviewItemView:
    id: uuid.UUID
    dimension: str
    fact: str
    evidence: dict
    line_index: int | None
    status: str
    outcome: str | None
    correction: dict | None
    resolved_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class EstimateView:
    estimate_id: uuid.UUID
    status: str
    draft: dict | None
    totals: Totals | None
    violations: list[dict]
    iterations: int
    reason: str | None
    created_at: datetime
    judge_verdict: JudgeVerdictView | None
    review_items: list[ReviewItemView]


@dataclass(frozen=True)
class QuoteDetail:
    quote_request_id: uuid.UUID
    case_id: str | None
    customer_id: str | None
    site_id: str | None
    contract_id: str | None
    raw_email_text: str
    parsed_json: dict
    created_at: datetime
    dedupe_verdicts: list[DedupeVerdictView]
    estimates: list[EstimateView]
    skus: dict[str, SkuInfo]
```

- [ ] **Step 5: Write `app/quotes/repository.py`**

```python
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dedupe.models import DedupeVerdictRow
from app.estimate.models import EstimateDraftRow
from app.intake.models import QuoteRequestRow
from app.judge.models import JudgeVerdictRow, ReviewItemRow


def list_quote_requests(session: Session) -> list[QuoteRequestRow]:
    return list(session.scalars(select(QuoteRequestRow).order_by(QuoteRequestRow.created_at.desc(), QuoteRequestRow.id)))


def estimates_for_requests(session: Session, request_ids: list[uuid.UUID]) -> list[EstimateDraftRow]:
    """Newest first."""
    if not request_ids:
        return []
    return list(session.scalars(
        select(EstimateDraftRow)
        .where(EstimateDraftRow.quote_request_id.in_(request_ids))
        .order_by(EstimateDraftRow.created_at.desc(), EstimateDraftRow.id)
    ))


def verdicts_for_estimates(session: Session, estimate_ids: list[uuid.UUID]) -> list[JudgeVerdictRow]:
    """Newest first, so the first row seen per estimate is its latest verdict."""
    if not estimate_ids:
        return []
    return list(session.scalars(
        select(JudgeVerdictRow)
        .where(JudgeVerdictRow.estimate_id.in_(estimate_ids))
        .order_by(JudgeVerdictRow.created_at.desc(), JudgeVerdictRow.id)
    ))


def review_items_for_estimates(session: Session, estimate_ids: list[uuid.UUID]) -> list[ReviewItemRow]:
    if not estimate_ids:
        return []
    return list(session.scalars(
        select(ReviewItemRow)
        .where(ReviewItemRow.estimate_id.in_(estimate_ids))
        .order_by(ReviewItemRow.created_at, ReviewItemRow.id)
    ))


def dedupe_verdicts_for_requests(session: Session, request_ids: list[uuid.UUID]) -> list[DedupeVerdictRow]:
    if not request_ids:
        return []
    return list(session.scalars(
        select(DedupeVerdictRow)
        .where(DedupeVerdictRow.quote_request_id.in_(request_ids))
        .order_by(DedupeVerdictRow.created_at, DedupeVerdictRow.id)
    ))
```

- [ ] **Step 6: Write `app/quotes/service.py`**

```python
import uuid
from collections import Counter, defaultdict

from sqlalchemy.orm import Session

from app.estimate.helper import compute_totals
from app.estimate.models import EstimateDraftRow
from app.estimate.schemas import EstimateDraft
from app.intake.repository import get_quote_request
from app.judge.models import JudgeVerdictRow, ReviewItemRow
from app.quotes.repository import (
    dedupe_verdicts_for_requests, estimates_for_requests, list_quote_requests, review_items_for_estimates,
    verdicts_for_estimates,
)
from app.quotes.schemas import (
    DedupeVerdictView, EstimateView, JudgeVerdictView, QuoteDetail, QuoteSummary, ReviewItemView, SkuInfo,
)
from app.reference_data.repository import skus_by_ids

DUPLICATE_VERDICT = "DUPLICATE_OF"
_SINGLE_SKU_KEYS = ("sku_id", "live_sku_id")
_SKU_LIST_KEYS = ("required_part_ids", "missing_required_part_ids")


class QuoteNotFound(Exception):
    pass


def _latest_verdict_by_estimate(verdicts: list[JudgeVerdictRow]) -> dict[uuid.UUID, JudgeVerdictRow]:
    latest: dict[uuid.UUID, JudgeVerdictRow] = {}
    for verdict in verdicts:  # newest first
        latest.setdefault(verdict.estimate_id, verdict)
    return latest


def _group_by_request(estimates: list[EstimateDraftRow]) -> dict[uuid.UUID, list[EstimateDraftRow]]:
    grouped: dict[uuid.UUID, list[EstimateDraftRow]] = defaultdict(list)
    for estimate in estimates:
        grouped[estimate.quote_request_id].append(estimate)
    return grouped


def list_quotes(session: Session) -> list[QuoteSummary]:
    requests = list_quote_requests(session)
    request_ids = [request.id for request in requests]
    by_request = _group_by_request(estimates_for_requests(session, request_ids))
    estimate_ids = [estimate.id for rows in by_request.values() for estimate in rows]
    latest_verdict = _latest_verdict_by_estimate(verdicts_for_estimates(session, estimate_ids))
    open_items = Counter(
        item.estimate_id for item in review_items_for_estimates(session, estimate_ids) if item.status == "open"
    )
    duplicates = {
        verdict.quote_request_id
        for verdict in dedupe_verdicts_for_requests(session, request_ids)
        if verdict.verdict == DUPLICATE_VERDICT
    }

    summaries = []
    for request in requests:
        estimates = by_request.get(request.id, [])
        latest = estimates[0] if estimates else None
        verdict = latest_verdict.get(latest.id) if latest else None
        summaries.append(QuoteSummary(
            quote_request_id=request.id, case_id=request.case_id, customer_id=request.customer_id,
            created_at=request.created_at, estimate_count=len(estimates),
            latest_estimate_status=latest.status if latest else None,
            latest_trusted=verdict.trusted if verdict else None,
            open_review_items=sum(open_items[estimate.id] for estimate in estimates),
            is_duplicate=request.id in duplicates,
        ))
    return summaries


def _collect_sku_ids(node, found: set[str]) -> None:
    """Every SKU id an estimate or a review item's evidence mentions, wherever it is nested."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in _SINGLE_SKU_KEYS and isinstance(value, str):
                found.add(value)
            elif key in _SKU_LIST_KEYS and isinstance(value, list):
                found.update(part for part in value if isinstance(part, str))
            else:
                _collect_sku_ids(value, found)
    elif isinstance(node, list):
        for child in node:
            _collect_sku_ids(child, found)


def _estimate_view(
    estimate: EstimateDraftRow, verdict: JudgeVerdictRow | None, items: list[ReviewItemRow],
) -> EstimateView:
    draft = EstimateDraft.model_validate(estimate.draft) if estimate.draft else None
    return EstimateView(
        estimate_id=estimate.id, status=estimate.status, draft=estimate.draft,
        totals=compute_totals(draft.lines) if draft else None, violations=estimate.violations,
        iterations=estimate.iterations, reason=estimate.reason, created_at=estimate.created_at,
        judge_verdict=None if verdict is None else JudgeVerdictView(
            id=verdict.id, model=verdict.model, dimensions=verdict.dimensions,
            overall_confidence=verdict.overall_confidence, flagged_dimension=verdict.flagged_dimension,
            trusted=verdict.trusted, created_at=verdict.created_at,
        ),
        review_items=[
            ReviewItemView(
                id=item.id, dimension=item.dimension, fact=item.fact, evidence=item.evidence,
                line_index=item.line_index, status=item.status, outcome=item.outcome, correction=item.correction,
                resolved_at=item.resolved_at, created_at=item.created_at,
            )
            for item in items
        ],
    )


def get_quote_detail(session: Session, quote_request_id: uuid.UUID) -> QuoteDetail:
    request = get_quote_request(session, quote_request_id)
    if request is None:
        raise QuoteNotFound(f"quote request {quote_request_id} not found")

    estimates = estimates_for_requests(session, [request.id])
    estimate_ids = [estimate.id for estimate in estimates]
    latest_verdict = _latest_verdict_by_estimate(verdicts_for_estimates(session, estimate_ids))
    items_by_estimate: dict[uuid.UUID, list[ReviewItemRow]] = defaultdict(list)
    for item in review_items_for_estimates(session, estimate_ids):
        items_by_estimate[item.estimate_id].append(item)

    sku_ids: set[str] = set()
    for estimate in estimates:
        _collect_sku_ids(estimate.draft, sku_ids)
        for item in items_by_estimate[estimate.id]:
            _collect_sku_ids(item.evidence, sku_ids)

    return QuoteDetail(
        quote_request_id=request.id, case_id=request.case_id, customer_id=request.customer_id,
        site_id=request.site_id, contract_id=request.contract_id, raw_email_text=request.raw_email_text,
        parsed_json=request.parsed_json, created_at=request.created_at,
        dedupe_verdicts=[
            DedupeVerdictView(
                candidate_quote_request_id=verdict.candidate_quote_request_id, verdict=verdict.verdict,
                content_jaccard=verdict.content_jaccard, style_jaccard=verdict.style_jaccard,
                signals_fired=list(verdict.signals_fired), created_at=verdict.created_at,
            )
            for verdict in dedupe_verdicts_for_requests(session, [request.id])
        ],
        estimates=[
            _estimate_view(estimate, latest_verdict.get(estimate.id), items_by_estimate[estimate.id])
            for estimate in estimates
        ],
        skus={
            sku.sku_id: SkuInfo(name=sku.name, category=sku.category, discontinued=sku.discontinued)
            for sku in skus_by_ids(session, sku_ids)
        },
    )
```

- [ ] **Step 7: Write the API layer**

`backend/api/v1/quotes/response.py`:

```python
import uuid
from datetime import datetime

from pydantic import BaseModel

from app.estimate.schemas import EstimateDraft, Totals, Violation
from app.judge.schemas import DimensionScore


class QuoteSummaryResponse(BaseModel):
    quote_request_id: uuid.UUID
    case_id: str | None
    customer_id: str | None
    created_at: datetime
    estimate_count: int
    latest_estimate_status: str | None
    latest_trusted: bool | None
    open_review_items: int
    is_duplicate: bool


class QuoteSkuInfoResponse(BaseModel):
    name: str
    category: str
    discontinued: bool


class QuoteDedupeVerdictResponse(BaseModel):
    candidate_quote_request_id: uuid.UUID
    verdict: str
    content_jaccard: float
    style_jaccard: float
    signals_fired: list[str]
    created_at: datetime


class QuoteJudgeVerdictResponse(BaseModel):
    id: uuid.UUID
    model: str
    dimensions: list[DimensionScore]
    overall_confidence: float
    flagged_dimension: str
    trusted: bool
    created_at: datetime


class QuoteReviewItemResponse(BaseModel):
    id: uuid.UUID
    dimension: str
    fact: str
    evidence: dict
    line_index: int | None
    status: str
    outcome: str | None
    correction: dict | None
    resolved_at: datetime | None
    created_at: datetime


class QuoteEstimateResponse(BaseModel):
    estimate_id: uuid.UUID
    status: str
    draft: EstimateDraft | None
    totals: Totals | None
    violations: list[Violation]
    iterations: int
    reason: str | None
    created_at: datetime
    judge_verdict: QuoteJudgeVerdictResponse | None
    review_items: list[QuoteReviewItemResponse]


class QuoteDetailResponse(BaseModel):
    quote_request_id: uuid.UUID
    case_id: str | None
    customer_id: str | None
    site_id: str | None
    contract_id: str | None
    raw_email_text: str
    parsed_json: dict
    created_at: datetime
    dedupe_verdicts: list[QuoteDedupeVerdictResponse]
    estimates: list[QuoteEstimateResponse]
    skus: dict[str, QuoteSkuInfoResponse]
```

`backend/api/v1/quotes/route.py`:

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.v1.quotes.response import QuoteDetailResponse, QuoteSummaryResponse
from app.quotes.service import QuoteNotFound, get_quote_detail, list_quotes
from core.db.session import get_session

router = APIRouter(prefix="/v1/quotes", tags=["quotes"])


@router.get("", response_model=list[QuoteSummaryResponse])
def list_all_quotes(session: Session = Depends(get_session)) -> list[QuoteSummaryResponse]:
    return [QuoteSummaryResponse.model_validate(summary, from_attributes=True) for summary in list_quotes(session)]


@router.get("/{quote_request_id}", response_model=QuoteDetailResponse)
def get_quote(quote_request_id: uuid.UUID, session: Session = Depends(get_session)) -> QuoteDetailResponse:
    try:
        detail = get_quote_detail(session, quote_request_id)
    except QuoteNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return QuoteDetailResponse.model_validate(detail, from_attributes=True)
```

In `backend/main.py` add `from api.v1.quotes.route import router as quotes_router` (keep imports alphabetical) and `app.include_router(quotes_router)`.

- [ ] **Step 8: Run to verify pass**

Run: `cd backend && uv run pytest tests/api/v1/test_quotes_route.py -v`
Expected: all pass. If `test_list_uses_a_fixed_number_of_queries` is flaky because `event.listen` rejects a `Connection`, listen on `db_session.get_bind().engine` instead and count only statements on this connection; do not delete the test.

- [ ] **Step 9: Commit**

```bash
git add backend/app/reference_data/repository.py backend/app/quotes backend/api/v1/quotes backend/main.py backend/tests/api/v1/test_quotes_route.py
git commit -m "feat: add read endpoints for quote requests and their estimates"
```

---

## Task 4: Metrics endpoint

**Files:**
- Create: `backend/app/metrics/__init__.py` (empty), `schemas.py`, `repository.py`, `service.py`
- Create: `backend/api/v1/metrics/__init__.py` (empty), `route.py`, `response.py`
- Modify: `backend/main.py`
- Test: `backend/tests/app/metrics/__init__.py` (empty), `backend/tests/app/metrics/test_service.py`, `backend/tests/api/v1/test_metrics_route.py`

**Interfaces:**
- Produces: `MetricCounts(verdicts_total, verdicts_trusted, review_items_resolved, review_items_corrected, requests_compared, requests_duplicate)` and `Metrics(auto_send_rate, correction_rate, duplicate_rate, counts)` dataclasses; `ratio(numerator: int, denominator: int) -> float | None`; `metrics_from_counts(counts: MetricCounts) -> Metrics`; `compute_metrics(session: Session) -> Metrics`.
- Produces: `GET /v1/metrics` -> `MetricsResponse{auto_send_rate: float|null, correction_rate: float|null, duplicate_rate: float|null, counts: MetricCountsResponse}`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/app/metrics/test_service.py`:

```python
from app.metrics.schemas import MetricCounts
from app.metrics.service import metrics_from_counts, ratio


def test_ratio_is_none_not_zero_when_the_denominator_is_zero():
    assert ratio(0, 0) is None
    assert ratio(3, 0) is None


def test_ratio_divides():
    assert ratio(1, 4) == 0.25


def test_empty_counts_give_null_rates():
    metrics = metrics_from_counts(MetricCounts(0, 0, 0, 0, 0, 0))

    assert metrics.auto_send_rate is None
    assert metrics.correction_rate is None
    assert metrics.duplicate_rate is None


def test_rates_follow_the_stated_definitions():
    metrics = metrics_from_counts(MetricCounts(
        verdicts_total=10, verdicts_trusted=7, review_items_resolved=4, review_items_corrected=3,
        requests_compared=5, requests_duplicate=1,
    ))

    assert metrics.auto_send_rate == 0.7
    assert metrics.correction_rate == 0.75
    assert metrics.duplicate_rate == 0.2
```

`backend/tests/api/v1/test_metrics_route.py`:

```python
from fastapi.testclient import TestClient

from app.dedupe.repository import save_verdict
from app.estimate.repository import save_estimate_draft
from app.intake.repository import save_quote_request
from app.judge.repository import save_judge_verdict, save_review_item
from core.db.session import get_session
from main import app


def _counts(session):
    app.dependency_overrides[get_session] = lambda: session
    try:
        return TestClient(app).get("/v1/metrics").json()["counts"]
    finally:
        app.dependency_overrides.clear()


def _request(session):
    return save_quote_request(
        session, raw_email_text="need parts", parsed_json={"resolved_line_items": []},
        content_fingerprint={}, style_fingerprint={},
    )


def _estimate(session, request):
    return save_estimate_draft(
        session, quote_request_id=request.id, status="ready", draft={"lines": []}, violations=[],
        iterations=1, reason=None,
    )


def _verdict(session, estimate, trusted):
    return save_judge_verdict(
        session, estimate_id=estimate.id, model="test-judge", dimensions=[], overall_confidence=0.5,
        flagged_dimension="graph_completion", trusted=trusted,
    )


def test_metrics_counts_grow_by_exactly_the_rows_added(db_session):
    before = _counts(db_session)
    request = _request(db_session)
    estimate = _estimate(db_session, request)
    trusted = _verdict(db_session, estimate, True)
    untrusted = _verdict(db_session, estimate, False)
    approved = save_review_item(
        db_session, judge_verdict_id=untrusted.id, estimate_id=estimate.id, dimension="graph_completion",
        fact="x", evidence={}, line_index=None,
    )
    corrected = save_review_item(
        db_session, judge_verdict_id=untrusted.id, estimate_id=estimate.id, dimension="graph_completion",
        fact="y", evidence={}, line_index=None,
    )
    save_review_item(
        db_session, judge_verdict_id=untrusted.id, estimate_id=estimate.id, dimension="graph_completion",
        fact="still open", evidence={}, line_index=None,
    )
    approved.status, approved.outcome = "approved", "approved"
    corrected.status, corrected.outcome = "corrected", "corrected"
    other = _request(db_session)
    save_verdict(
        db_session, quote_request_id=other.id, candidate_quote_request_id=request.id, verdict="DUPLICATE_OF",
        content_jaccard=1.0, style_jaccard=1.0, signals_fired=[],
    )
    save_verdict(
        db_session, quote_request_id=request.id, candidate_quote_request_id=other.id, verdict="DISTINCT",
        content_jaccard=0.0, style_jaccard=0.1, signals_fired=[],
    )
    db_session.flush()
    assert trusted.trusted is True

    after = _counts(db_session)

    assert after["verdicts_total"] - before["verdicts_total"] == 2
    assert after["verdicts_trusted"] - before["verdicts_trusted"] == 1
    assert after["review_items_resolved"] - before["review_items_resolved"] == 2
    assert after["review_items_corrected"] - before["review_items_corrected"] == 1
    assert after["requests_compared"] - before["requests_compared"] == 2
    assert after["requests_duplicate"] - before["requests_duplicate"] == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/app/metrics tests/api/v1/test_metrics_route.py -v`
Expected: FAIL (modules do not exist).

- [ ] **Step 3: Implement the app layer**

`backend/app/metrics/schemas.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class MetricCounts:
    verdicts_total: int
    verdicts_trusted: int
    review_items_resolved: int
    review_items_corrected: int
    requests_compared: int
    requests_duplicate: int


@dataclass(frozen=True)
class Metrics:
    auto_send_rate: float | None
    correction_rate: float | None
    duplicate_rate: float | None
    counts: MetricCounts
```

`backend/app/metrics/repository.py`:

```python
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.dedupe.models import DedupeVerdictRow
from app.judge.models import JudgeVerdictRow, ReviewItemRow
from app.metrics.schemas import MetricCounts

DUPLICATE_VERDICT = "DUPLICATE_OF"


def _count(session: Session, statement: Select) -> int:
    return session.scalar(statement) or 0


def count_metric_inputs(session: Session) -> MetricCounts:
    distinct_requests = func.count(func.distinct(DedupeVerdictRow.quote_request_id))
    return MetricCounts(
        verdicts_total=_count(session, select(func.count()).select_from(JudgeVerdictRow)),
        verdicts_trusted=_count(
            session, select(func.count()).select_from(JudgeVerdictRow).where(JudgeVerdictRow.trusted.is_(True))
        ),
        review_items_resolved=_count(
            session, select(func.count()).select_from(ReviewItemRow).where(ReviewItemRow.outcome.is_not(None))
        ),
        review_items_corrected=_count(
            session, select(func.count()).select_from(ReviewItemRow).where(ReviewItemRow.outcome == "corrected")
        ),
        requests_compared=_count(session, select(distinct_requests)),
        requests_duplicate=_count(session, select(distinct_requests).where(DedupeVerdictRow.verdict == DUPLICATE_VERDICT)),
    )
```

`backend/app/metrics/service.py`:

```python
from sqlalchemy.orm import Session

from app.metrics.repository import count_metric_inputs
from app.metrics.schemas import MetricCounts, Metrics


def ratio(numerator: int, denominator: int) -> float | None:
    """None, not 0, when nothing has been measured yet, so a dashboard cannot show a real-looking 0%."""
    return numerator / denominator if denominator else None


def metrics_from_counts(counts: MetricCounts) -> Metrics:
    return Metrics(
        auto_send_rate=ratio(counts.verdicts_trusted, counts.verdicts_total),
        correction_rate=ratio(counts.review_items_corrected, counts.review_items_resolved),
        duplicate_rate=ratio(counts.requests_duplicate, counts.requests_compared),
        counts=counts,
    )


def compute_metrics(session: Session) -> Metrics:
    return metrics_from_counts(count_metric_inputs(session))
```

- [ ] **Step 4: Implement the API layer**

`backend/api/v1/metrics/response.py`:

```python
from pydantic import BaseModel


class MetricCountsResponse(BaseModel):
    verdicts_total: int
    verdicts_trusted: int
    review_items_resolved: int
    review_items_corrected: int
    requests_compared: int
    requests_duplicate: int


class MetricsResponse(BaseModel):
    auto_send_rate: float | None
    correction_rate: float | None
    duplicate_rate: float | None
    counts: MetricCountsResponse
```

`backend/api/v1/metrics/route.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.v1.metrics.response import MetricsResponse
from app.metrics.service import compute_metrics
from core.db.session import get_session

router = APIRouter(prefix="/v1/metrics", tags=["metrics"])


@router.get("", response_model=MetricsResponse)
def get_metrics(session: Session = Depends(get_session)) -> MetricsResponse:
    return MetricsResponse.model_validate(compute_metrics(session), from_attributes=True)
```

Register in `backend/main.py`: `from api.v1.metrics.route import router as metrics_router` and `app.include_router(metrics_router)`.

- [ ] **Step 5: Run to verify pass**

Run: `cd backend && uv run pytest tests/app/metrics tests/api/v1/test_metrics_route.py -v`
Expected: all pass.

- [ ] **Step 6: Run the whole backend suite**

Run: `cd backend && uv run pytest -q`
Expected: everything passes (Neo4j and Postgres up: `docker compose up -d` from repo root first).

- [ ] **Step 7: Commit**

```bash
git add backend/app/metrics backend/api/v1/metrics backend/main.py backend/tests
git commit -m "feat: add the metrics endpoint for auto-send, correction and duplicate rates"
```

## Task 5: Load-data refactor and OpenAPI export

**Files:**
- Modify: `backend/scripts/load_data.py:97-124`
- Create: `backend/scripts/export_openapi.py`
- Test: `backend/tests/scripts/test_export_openapi.py`

**Interfaces:**
- Produces: `load_all(session, data_dir: Path = DATA_DIR) -> str` in `scripts/load_data.py`: loads catalog, customers, pricing and structure into `session` (no commit) and returns the one-line summary `run()` prints.
- Produces: `python scripts/export_openapi.py <out_path>` writes `app.openapi()` as JSON.

- [ ] **Step 1: Write the failing test**

`backend/tests/scripts/test_export_openapi.py`:

```python
import json

from export_openapi import write_openapi


def test_write_openapi_emits_the_phase_7_paths(tmp_path):
    out = tmp_path / "openapi.json"

    write_openapi(out)

    paths = json.loads(out.read_text(encoding="utf-8"))["paths"]
    assert "/v1/quotes" in paths
    assert "/v1/quotes/{quote_request_id}" in paths
    assert "/v1/metrics" in paths
    assert "/v1/review" in paths
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/scripts/test_export_openapi.py -v`
Expected: FAIL (`ModuleNotFoundError: export_openapi`).

- [ ] **Step 3: Implement**

`backend/scripts/export_openapi.py`:

```python
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app


def write_openapi(out_path: Path) -> None:
    out_path.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    write_openapi(Path(sys.argv[1]))
```

In `backend/scripts/load_data.py` replace the body of `run` with a `load_all` plus a thinner `run`:

```python
def load_all(session, data_dir: Path = DATA_DIR) -> str:
    catalog = json.loads((data_dir / "catalog.json").read_text(encoding="utf-8"))
    customers = json.loads((data_dir / "customers.json").read_text(encoding="utf-8"))
    pricing = json.loads((data_dir / "pricing.json").read_text(encoding="utf-8"))
    structure = json.loads((data_dir / "structure.json").read_text(encoding="utf-8"))

    load_catalog(session, catalog)
    load_customers(session, customers)
    load_pricing(session, pricing)
    load_structure(session, structure)
    return (
        f"loaded {len(catalog)} SKUs, {len(customers)} customers, "
        f"{len(pricing['history'])} price history rows, "
        f"{len(structure['families'])} families, {len(structure['projects'])} projects"
    )


def run(data_dir: Path = DATA_DIR) -> None:
    settings = Settings()
    engine = make_engine(settings.database_url)
    session = make_session_factory(engine)()
    try:
        summary = load_all(session, data_dir)
        session.commit()
        redacted_url = re.sub(r"//([^:/@]+):[^@]*@", r"//\1:***@", settings.database_url)
        print(f"{summary} into {redacted_url}")
    finally:
        session.close()
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && uv run pytest tests/scripts/test_export_openapi.py tests/test_load_data.py -v`
Expected: all pass (the existing load-data tests still pass).

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/load_data.py backend/scripts/export_openapi.py backend/tests/scripts/test_export_openapi.py
git commit -m "feat: add an OpenAPI export script and a reusable load_all"
```

---

## Task 6: Demo fakes

**Files:**
- Create: `backend/scripts/demo/__init__.py` (empty), `backend/scripts/demo/fakes.py`
- Test: `backend/tests/scripts/test_demo_fakes.py`

**Interfaces:**
- Consumes: `GraphReader.sku_chain/required_parts`, `get_sku`, `get_contract`, `predict_price_for_sku`, `QuoteRequestExtraction`, `AgentTurn`, `ToolCall`, `RawJudgeScore`, `RawDimensionScore`.
- Produces (all in `demo.fakes`):
  - `DemoSetupError(Exception)`.
  - `ScriptedExtractionClient(scenarios: list[dict])` with `extract_quote_request(email_text) -> QuoteRequestExtraction`.
  - `build_draft(session, reader, quote_request, as_of) -> dict`: a guardrail-passing `submit_draft` payload.
  - `blocked_draft(draft: dict) -> dict`: the same draft with the first line's quantity 0.
  - `ScriptedAgentClient(draft: dict)` with `next_turn(messages, tools) -> AgentTurn` (always submits `draft`).
  - `DemoJudgeClient(graph_watch: set[str], contract_watch: set[str])` with `score(evidence, system_prompt) -> RawJudgeScore`.
  - `UnusedEmbedder` with `embed(texts)` raising `DemoSetupError`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/scripts/test_demo_fakes.py`:

```python
import pytest

from app.intake.repository import save_quote_request
from demo.fakes import (
    DemoJudgeClient, DemoSetupError, ScriptedAgentClient, ScriptedExtractionClient, UnusedEmbedder, blocked_draft,
    build_draft,
)
from tests.app.estimate.seed import AS_OF, seed_world


def _request(session, sku_ids, customer_id="CUST-E1", contract_id="CTR-E1"):
    return save_quote_request(
        session, raw_email_text="x",
        parsed_json={"resolved_line_items": [
            {"sku_name_as_written": s, "sku_id": s, "quantity": "1"} for s in sku_ids
        ]},
        content_fingerprint={}, style_fingerprint={}, customer_id=customer_id, contract_id=contract_id,
    )


def test_extraction_reads_the_scenario_ground_truth():
    scenario = {
        "case_id": "sc-1", "customer": {"name": "Zenith Contractors", "contact": "Suresh Iyer"},
        "entities": {"customer_id": "CUST-1", "sku_names": ["Alpha", "Beta"]}, "email_text": "hello",
    }

    result = ScriptedExtractionClient([scenario]).extract_quote_request("hello")

    assert result.customer_name_as_written == "Zenith Contractors"
    assert [i.sku_name_as_written for i in result.line_items] == ["Alpha", "Beta"]
    assert result.raw_text == "hello"


def test_extraction_handles_a_single_sku_scenario():
    scenario = {
        "case_id": "sc-1", "customer": {"name": "Z", "contact": "C"},
        "entities": {"customer_id": "CUST-1", "sku_name": "Alpha"}, "email_text": "hello",
    }

    result = ScriptedExtractionClient([scenario]).extract_quote_request("hello")

    assert [i.sku_name_as_written for i in result.line_items] == ["Alpha"]


def test_draft_adds_required_parts_and_applies_the_covered_contract_discount(db_session, make_reader):
    seed_world(db_session)
    reader = make_reader()
    request = _request(db_session, ["SKU-E-B1"])

    draft = build_draft(db_session, reader, request, AS_OF)

    assert [line["sku_id"] for line in draft["lines"]] == ["SKU-E-B1", "SKU-E-A1"]
    by_sku = {line["sku_id"]: line for line in draft["lines"]}
    assert by_sku["SKU-E-A1"]["discount_pct"] == 10.0
    assert by_sku["SKU-E-B1"]["discount_pct"] == 0.0
    assert draft["contract_id"] == "CTR-E1"
    assert [a["kind"] for a in draft["adjustments"]] == ["added_required"]


def test_draft_substitutes_a_discontinued_sku(db_session, make_reader):
    seed_world(db_session)
    reader = make_reader()
    request = _request(db_session, ["SKU-E-OLD"])

    draft = build_draft(db_session, reader, request, AS_OF)

    assert [line["sku_id"] for line in draft["lines"]] == ["SKU-E-A1"]
    assert draft["adjustments"][0]["kind"] == "substituted"


def test_draft_predicts_the_price_of_a_sku_with_no_list_price(db_session, make_reader):
    seed_world(db_session)
    reader = make_reader()
    request = _request(db_session, ["SKU-E-GAP"], customer_id="CUST-E2", contract_id=None)

    draft = build_draft(db_session, reader, request, AS_OF)

    assert draft["lines"][0]["unit_price"] == 20.0
    assert draft["lines"][0]["price_source"] == "predicted"
    assert draft["contract_id"] is None
    assert draft["lines"][0]["discount_pct"] == 0.0


def test_draft_refuses_a_sku_whose_price_cannot_be_predicted(db_session, make_reader):
    seed_world(db_session)
    reader = make_reader()
    request = _request(db_session, ["SKU-E-LONE"], customer_id="CUST-E2", contract_id=None)

    with pytest.raises(DemoSetupError):
        build_draft(db_session, reader, request, AS_OF)


def test_blocked_draft_zeroes_only_the_first_quantity():
    draft = {"lines": [{"sku_id": "A", "quantity": 1}, {"sku_id": "B", "quantity": 1}], "adjustments": []}

    blocked = blocked_draft(draft)

    assert [line["quantity"] for line in blocked["lines"]] == [0, 1]
    assert draft["lines"][0]["quantity"] == 1


def test_scripted_agent_submits_the_same_draft_every_turn():
    draft = {"customer_id": "CUST-1", "lines": []}
    client = ScriptedAgentClient(draft)

    first = client.next_turn([], [])
    second = client.next_turn([], [])

    assert first.tool_calls[0].name == "submit_draft"
    assert first.tool_calls[0].arguments == draft
    assert second.tool_calls[0].arguments == draft


def _evidence(sku_id, *, price_source="list", required=(), contract_id=None, discount=0.0):
    return {
        "line_index": 0, "sku_id": sku_id, "unit_price": 10.0,
        "price": {"price_source": price_source},
        "contract": {"contract_id": contract_id, "discount_pct": discount},
        "graph": {"required_part_ids": list(required), "missing_required_part_ids": []},
    }


def _scores(judge, evidence):
    return {d.name: d.score for d in judge.score(evidence, "prompt").dimensions}


def test_judge_trusts_clean_evidence():
    scores = _scores(DemoJudgeClient(set(), set()), [_evidence("A")])

    assert min(scores.values()) > 0.8


def test_judge_doubts_a_predicted_price():
    scores = _scores(DemoJudgeClient(set(), set()), [_evidence("A", price_source="predicted")])

    assert scores["price_provenance"] < 0.5


def test_judge_doubts_a_watched_sku_with_no_recorded_required_part():
    judge = DemoJudgeClient({"A"}, set())

    assert _scores(judge, [_evidence("A")])["graph_completion"] < 0.5
    assert _scores(judge, [_evidence("A", required=["B"])])["graph_completion"] > 0.8


def test_judge_doubts_a_watched_contract_line_at_full_price():
    judge = DemoJudgeClient(set(), {"A"})

    assert _scores(judge, [_evidence("A", contract_id="CTR-1")])["contract_discount"] < 0.5
    assert _scores(judge, [_evidence("A", contract_id="CTR-1", discount=10.0)])["contract_discount"] > 0.8
    assert _scores(judge, [_evidence("A")])["contract_discount"] > 0.8


def test_unused_embedder_fails_loudly():
    with pytest.raises(DemoSetupError):
        UnusedEmbedder().embed(["anything"])
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/scripts/test_demo_fakes.py -v`
Expected: FAIL (`ModuleNotFoundError: demo`).

- [ ] **Step 3: Implement `backend/scripts/demo/fakes.py`**

```python
"""Deterministic stand-ins for the three external LLM clients, used only by the demo seed script.

Everything downstream of them is production code: intake resolves names against the real reference data, the
guardrails and graph check the real drafts, and the judge scores evidence built by `build_evidence`. Only the
model calls are replaced, so no network is touched and no API key is needed."""
from datetime import date

from sqlalchemy.orm import Session

from app.estimate.pricing import predict_price_for_sku
from app.graph.reader import GraphReader
from app.intake.models import QuoteRequestRow
from app.intake.schemas import LineItemExtraction, QuoteRequestExtraction
from app.reference_data.models import Contract
from app.reference_data.repository import get_contract, get_sku
from core.llm.anthropic_judge_client import RawDimensionScore, RawJudgeScore
from core.llm.openai_agent_client import AgentTurn, ToolCall

DOUBT_SCORE = 0.2
PRICE_TRUST_SCORE = 0.95
CONTRACT_TRUST_SCORE = 0.95
GRAPH_TRUST_SCORE = 0.9


class DemoSetupError(Exception):
    """The reference data cannot support the scripted scenario."""


class ScriptedExtractionClient:
    """Reads the structured request from the scenario's ground truth instead of asking GPT-4o."""

    def __init__(self, scenarios: list[dict]) -> None:
        self._by_email = {scenario["email_text"]: scenario for scenario in scenarios}

    def extract_quote_request(self, email_text: str) -> QuoteRequestExtraction:
        scenario = self._by_email[email_text]
        entities = scenario["entities"]
        names = entities.get("sku_names") or [entities["sku_name"]]
        return QuoteRequestExtraction(
            customer_name_as_written=scenario["customer"]["name"],
            contact_name_as_written=scenario["customer"]["contact"],
            line_items=[LineItemExtraction(sku_name_as_written=name, quantity="1") for name in names],
            raw_text=email_text,
        )


def _contract_applies(contract: Contract | None, category: str, as_of: date) -> bool:
    return (
        contract is not None
        and category in contract.covered_categories
        and contract.effective_from <= as_of <= contract.effective_to
    )


def _line(session: Session, sku_id: str, contract: Contract | None, as_of: date) -> dict:
    sku = get_sku(session, sku_id)
    if sku.list_price is not None:
        price, source = sku.list_price, "list"
    else:
        prediction = predict_price_for_sku(session, sku)
        if prediction is None:
            raise DemoSetupError(f"{sku_id} has no list price and too few priced peers to predict one")
        price, source = prediction.price, "predicted"
    discount = contract.discount_pct if _contract_applies(contract, sku.category, as_of) else 0.0
    return {"sku_id": sku_id, "quantity": 1, "unit_price": price, "price_source": source, "discount_pct": discount}


def _live_sku_id(reader: GraphReader, sku_id: str) -> str:
    chain = reader.sku_chain(sku_id)
    return chain.live_end.sku_id if chain is not None and chain.live_end is not None else sku_id


def build_draft(session: Session, reader: GraphReader, quote_request: QuoteRequestRow, as_of: date) -> dict:
    """What a correct agent would submit: each requested SKU replaced by its live successor, every required part
    added, list prices where they exist and peer-median predictions where they do not, and the contract discount
    only where the contract covers the category."""
    contract = get_contract(session, quote_request.contract_id) if quote_request.contract_id else None
    requested = [item["sku_id"] for item in quote_request.parsed_json["resolved_line_items"] if item.get("sku_id")]
    pending = list(dict.fromkeys(requested))
    ordered: list[str] = []
    adjustments: list[dict] = []

    while pending:
        sku_id = pending.pop(0)
        live_id = _live_sku_id(reader, sku_id)
        if live_id != sku_id:
            adjustments.append({
                "kind": "substituted", "sku_id": live_id,
                "detail": f"{sku_id} is discontinued; quoted its live replacement {live_id}",
            })
        if live_id in ordered:
            continue
        ordered.append(live_id)
        for part in reader.required_parts(live_id):
            part_live_id = _live_sku_id(reader, part.sku_id)
            if part_live_id not in ordered and part_live_id not in pending:
                adjustments.append({
                    "kind": "added_required", "sku_id": part_live_id, "detail": f"{live_id} requires {part_live_id}",
                })
                pending.append(part_live_id)

    return {
        "customer_id": quote_request.customer_id,
        "contract_id": contract.contract_id if contract is not None else None,
        "lines": [_line(session, sku_id, contract, as_of) for sku_id in ordered],
        "adjustments": adjustments,
    }


def blocked_draft(draft: dict) -> dict:
    """A draft the guardrails reject on every submission (a zero quantity), so the run ends for review."""
    first, *rest = draft["lines"]
    return {**draft, "lines": [{**first, "quantity": 0}, *rest]}


class ScriptedAgentClient:
    """Submits one fixed draft on every turn, standing in for the GPT-4o agent."""

    def __init__(self, draft: dict) -> None:
        self._turn = AgentTurn(
            content=None, tool_calls=[ToolCall(id="call-submit", name="submit_draft", arguments=draft)],
        )

    def next_turn(self, messages: list[dict], tools: list[dict]) -> AgentTurn:
        return self._turn


class DemoJudgeClient:
    """Stands in for the Claude Haiku judge. It doubts price provenance whenever a price was predicted. It doubts
    the graph and contract dimensions only for the SKUs the scenario planted a knowledge gap on, and only while the
    evidence still shows the gap, which is exactly what a reviewer's correction removes."""

    def __init__(self, graph_watch: set[str], contract_watch: set[str]) -> None:
        self._graph_watch = graph_watch
        self._contract_watch = contract_watch

    def score(self, evidence: list[dict], system_prompt: str) -> RawJudgeScore:
        predicted = [line["sku_id"] for line in evidence if line["price"]["price_source"] == "predicted"]
        graph_gap = [
            line["sku_id"] for line in evidence
            if line["sku_id"] in self._graph_watch and not line["graph"]["required_part_ids"]
        ]
        contract_gap = [
            line["sku_id"] for line in evidence
            if line["sku_id"] in self._contract_watch
            and line["contract"]["contract_id"] is not None
            and line["contract"]["discount_pct"] == 0
        ]
        return RawJudgeScore(dimensions=[
            RawDimensionScore(
                name="price_provenance", score=DOUBT_SCORE if predicted else PRICE_TRUST_SCORE,
                rationale=(
                    f"{', '.join(predicted)}: the price is a peer-median prediction, not a reference list price"
                    if predicted else "every price is a reference list price"
                ),
            ),
            RawDimensionScore(
                name="contract_discount", score=DOUBT_SCORE if contract_gap else CONTRACT_TRUST_SCORE,
                rationale=(
                    f"{', '.join(contract_gap)}: a contract customer is quoted at full price; is this category "
                    "really outside the contract?"
                    if contract_gap else "discounts match a covering, active contract, or none were claimed"
                ),
            ),
            RawDimensionScore(
                name="graph_completion", score=DOUBT_SCORE if graph_gap else GRAPH_TRUST_SCORE,
                rationale=(
                    f"{', '.join(graph_gap)} is quoted with no required part recorded in the graph, but it "
                    "usually ships with one"
                    if graph_gap else "live SKUs, and every recorded required part is quoted"
                ),
            ),
        ])


class UnusedEmbedder:
    """The scripted agent never calls a search tool, so nothing should ask for an embedding."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise DemoSetupError("the scripted agent never searches, so nothing should be embedded")
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && uv run pytest tests/scripts/test_demo_fakes.py -v`
Expected: all pass. If `test_draft_adds_required_parts...` fails on line order, the order is B1 first (requested) then A1 (added); fix the implementation, not the test.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/demo backend/tests/scripts/test_demo_fakes.py
git commit -m "feat: add scripted stand-ins for the extraction, agent and judge clients"
```

---

## Task 7: Demo scenario selection, seeding and replay

**Files:**
- Create: `backend/scripts/demo/scenarios.py`, `backend/scripts/demo/seed.py`
- Test: `backend/tests/test_phase7_acceptance.py`

**Interfaces:**
- Consumes: everything from `demo.fakes`; `run_dedupe`, `process_email`, `run_estimate`, `run_judge`, `resolve_review_item`, `consolidate_review_item`, `rebuild_reference_graph`, `GraphReader`, `TracingClient(None)`, `DATASET_AS_OF`.
- Produces (`demo.scenarios`):
  - `DemoCase` frozen dataclass: `role: str`, `scenario: dict`, `expectation: str`, `correction: dict | None = None`, `graph_gap: tuple[str, str] | None = None`, property `case_id`.
  - `select_cases(session, scenarios: list[dict], catalog: list[dict], as_of: date) -> list[DemoCase]` (raises `DemoSetupError` naming a role it cannot fill).
- Produces (`demo.seed`):
  - `plant_gaps(session, cases) -> None`.
  - `seed(session, client, ns, cases, scenarios) -> list[SeededCase]`.
  - `replay(session, client, ns, cases: list[DemoCase] | None = None) -> list[ReplayResult]`.
  - `pending_replays(session) -> list[str]` (case ids `replay` would re-run).
  - `SeededCase(case, quote_request_id, estimate_id, trusted, review_dimension)`, `ReplayResult(case_id, estimate_id, trusted, review_dimension)`.

Roles and expectations: `clean` x2 (`trusted`), `discontinued` (`trusted`), `price_gap` (`flagged:price_provenance`), `graph_gap` (`flagged:graph_completion`), `contract_gap` (`flagged:contract_discount`), `duplicate_a`/`duplicate_b` (`trusted`), `revision_a`/`revision_b` (`trusted`), `blocked` (`guardrail`).

- [ ] **Step 1: Write the failing acceptance test**

`backend/tests/test_phase7_acceptance.py`:

```python
"""Phase 7 done-when, backend half: with the demo dataset seeded, three quotes sit flagged in the queue and one is
blocked by the guardrails; correcting the three and replaying leaves each with a second, clean estimate and no
open review item, and the guardrail-blocked quote untouched.

What is bypassed, deliberately: the three LLM clients (scripted stand-ins in scripts/demo/fakes.py), and the
procrastinate queue (the replay consolidates inline, as the worker would). Everything else is production code,
run against the real Phase 1 dataset loaded into this test's transaction."""
import json

from app.estimate.constant import DATASET_AS_OF
from app.metrics.service import compute_metrics
from app.quotes.service import get_quote_detail, list_quotes
from demo.scenarios import select_cases
from demo.seed import pending_replays, replay, seed
from load_data import DATA_DIR, load_all
from tests.graph_support import build_reader


def _load(name):
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def test_seeded_flags_are_cleared_by_corrections_and_the_replay(db_session, graph_client, graph_ns):
    load_all(db_session)
    build_reader(db_session, graph_client, graph_ns)
    scenarios, catalog = _load("scenarios.json"), _load("catalog.json")
    cases = select_cases(db_session, scenarios, catalog, DATASET_AS_OF)
    corrections_before = compute_metrics(db_session).counts

    seeded = seed(db_session, graph_client, graph_ns, cases, scenarios)

    by_role = {s.case.role: s for s in seeded}
    assert {s.case.role for s in seeded} == {c.role for c in cases}
    assert by_role["price_gap"].review_dimension == "price_provenance"
    assert by_role["graph_gap"].review_dimension == "graph_completion"
    assert by_role["contract_gap"].review_dimension == "contract_discount"
    assert by_role["blocked"].review_dimension == "guardrail"
    assert all(by_role[role].trusted for role in ("clean", "discontinued", "duplicate_b", "revision_b"))
    assert pending_replays(db_session) == []

    replayed = replay(db_session, graph_client, graph_ns, cases)

    assert {r.case_id for r in replayed} == {by_role[r].case.case_id for r in ("price_gap", "graph_gap", "contract_gap")}
    for role in ("price_gap", "graph_gap", "contract_gap"):
        detail = get_quote_detail(db_session, by_role[role].quote_request_id)
        newest, oldest = detail.estimates[0], detail.estimates[-1]
        assert len(detail.estimates) == 2
        assert oldest.judge_verdict.trusted is False
        assert oldest.review_items[0].status == "consolidated"
        assert newest.judge_verdict.trusted is True
        assert newest.review_items == []
    blocked = get_quote_detail(db_session, by_role["blocked"].quote_request_id)
    assert len(blocked.estimates) == 1
    assert blocked.estimates[0].review_items[0].status == "open"

    assert replay(db_session, graph_client, graph_ns) == []
    summaries = {s.quote_request_id: s for s in list_quotes(db_session)}
    assert summaries[by_role["price_gap"].quote_request_id].open_review_items == 0
    corrections_after = compute_metrics(db_session).counts
    assert corrections_after.review_items_corrected - corrections_before.review_items_corrected == 3
```

Delete the unused `_summary` helper before running (it was a stub; the test does not use it).

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/test_phase7_acceptance.py -v`
Expected: FAIL (`ModuleNotFoundError: demo.scenarios`).

- [ ] **Step 3: Implement `backend/scripts/demo/scenarios.py`**

```python
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.estimate.pricing import predict_price_for_sku
from app.intake.resolution import resolve_extraction
from app.reference_data.repository import contracts_for_customer, get_sku, required_sku_ids
from demo.fakes import DemoSetupError, ScriptedExtractionClient

MAX_REPLACEMENT_HOPS = 10
PLANTED_PRICE_MARKUP = 1.1


@dataclass(frozen=True)
class DemoCase:
    role: str
    scenario: dict
    # "trusted", "flagged:<judge dimension>" or "guardrail"
    expectation: str
    # What a reviewer would submit to resolve the flag, in the exact shape POST /v1/review/{id}/resolve takes.
    correction: dict | None = None
    # The (sku_id, required_sku_id) requirement removed from the reference data to plant the knowledge gap.
    graph_gap: tuple[str, str] | None = None

    @property
    def case_id(self) -> str:
        return self.scenario["case_id"]


def _sku_ids(scenario: dict) -> list[str]:
    entities = scenario["entities"]
    return entities.get("sku_ids") or [entities["sku_id"]]


def _resolves(session: Session, scenario: dict) -> bool:
    """Whether intake, run on this scenario, lands on exactly the customer and SKUs the ground truth names."""
    extraction = ScriptedExtractionClient([scenario]).extract_quote_request(scenario["email_text"])
    resolved = resolve_extraction(session, extraction)
    return (
        resolved.customer_id == scenario["entities"]["customer_id"]
        and [item.sku_id for item in resolved.line_items] == _sku_ids(scenario)
    )


def _priced_and_live(session: Session, sku_id: str) -> bool:
    sku = get_sku(session, sku_id)
    return sku is not None and sku.list_price is not None and not sku.discontinued


def _needed(requires: dict[str, list[str]], sku_ids: list[str]) -> list[str]:
    """The SKUs plus every part they transitively require, which is what a correct draft has to quote."""
    found: list[str] = []
    pending = list(sku_ids)
    while pending:
        sku_id = pending.pop(0)
        if sku_id not in found:
            found.append(sku_id)
            pending.extend(requires.get(sku_id, []))
    return found


def _all_priced_and_live(session: Session, requires: dict[str, list[str]], sku_ids: list[str]) -> bool:
    return all(_priced_and_live(session, sku_id) for sku_id in _needed(requires, sku_ids))


def _live_replacement(session: Session, sku_id: str) -> str | None:
    sku = get_sku(session, sku_id)
    for _ in range(MAX_REPLACEMENT_HOPS):
        if sku is None:
            return None
        if not sku.discontinued:
            return sku.sku_id
        sku = get_sku(session, sku.replaced_by) if sku.replaced_by else None
    return None


def _pairs(scenarios: list[dict], scenario_type: str) -> list[tuple[dict, dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for scenario in scenarios:
        if scenario["scenario_type"] == scenario_type:
            grouped[scenario["entities"]["pair_id"]].append(scenario)
    return [tuple(sorted(members, key=lambda s: s["case_id"])) for members in grouped.values() if len(members) == 2]


def select_cases(session: Session, scenarios: list[dict], catalog: list[dict], as_of: date) -> list[DemoCase]:
    """Picks one scenario per demo role from the dataset, reading only reference data. A role that no scenario can
    fill raises DemoSetupError: the demo must not quietly run with a story missing."""
    requires = {sku["sku_id"]: sku["requires"] for sku in catalog}
    by_type: dict[str, list[dict]] = defaultdict(list)
    for scenario in scenarios:
        by_type[scenario["scenario_type"]].append(scenario)
    used: set[str] = set()

    def pick(role: str, candidates: list[dict], accepts) -> dict:
        for scenario in candidates:
            if scenario["case_id"] not in used and _resolves(session, scenario) and accepts(scenario):
                used.add(scenario["case_id"])
                return scenario
        raise DemoSetupError(f"no scenario in the dataset can play the {role!r} role")

    def clean(scenario: dict) -> bool:
        return _all_priced_and_live(session, requires, _sku_ids(scenario))

    def price_gap(scenario: dict) -> bool:
        gaps = [s for s in _sku_ids(scenario) if (sku := get_sku(session, s)) and sku.list_price is None]
        others = [s for s in _sku_ids(scenario) if s not in gaps]
        return (
            len(gaps) == 1 and predict_price_for_sku(session, get_sku(session, gaps[0])) is not None
            and not get_sku(session, gaps[0]).discontinued
            and all(_priced_and_live(session, r) for r in _needed(requires, others))
            and all(_priced_and_live(session, r) for r in requires.get(gaps[0], []))
        )

    def graph_gap(scenario: dict) -> bool:
        sku_id = scenario["entities"]["sku_id"]
        required = requires[sku_id]
        return (
            len(required) == 1 and required_sku_ids(session, sku_id) == required
            and _all_priced_and_live(session, requires, [sku_id])
        )

    def contract_gap(scenario: dict) -> bool:
        entities = scenario["entities"]
        contracts = contracts_for_customer(session, entities["customer_id"])
        if len(contracts) != 1 or contracts[0].contract_id != entities["contract_id"]:
            return False
        contract, sku = contracts[0], get_sku(session, entities["sku_id"])
        return (
            _all_priced_and_live(session, requires, [sku.sku_id])
            and sku.category == entities["sku_category"] and sku.category not in contract.covered_categories
            and contract.discount_pct > 0 and contract.effective_from <= as_of <= contract.effective_to
        )

    def discontinued(scenario: dict) -> bool:
        live_id = _live_replacement(session, scenario["entities"]["sku_id"])
        sku = get_sku(session, scenario["entities"]["sku_id"])
        return sku.discontinued and live_id is not None and _all_priced_and_live(session, requires, [live_id])

    def pair_role(role_a: str, role_b: str, scenario_type: str) -> list[DemoCase]:
        for first, second in _pairs(scenarios, scenario_type):
            if (
                first["case_id"] not in used and second["case_id"] not in used
                and _resolves(session, first) and _resolves(session, second)
                and clean(first) and clean(second)
            ):
                used.update((first["case_id"], second["case_id"]))
                return [DemoCase(role_a, first, "trusted"), DemoCase(role_b, second, "trusted")]
        raise DemoSetupError(f"no {scenario_type} in the dataset can play the {role_a!r} and {role_b!r} roles")

    clean_scenarios = by_type["clean_distinct"]
    first_clean = pick("clean", clean_scenarios, clean)
    second_clean = pick("clean", clean_scenarios, clean)
    swap = pick("discontinued", by_type["discontinued_swap"], discontinued)
    priced = pick("price_gap", clean_scenarios, price_gap)
    gap_sku_id = next(s for s in _sku_ids(priced) if get_sku(session, s).list_price is None)
    predicted = predict_price_for_sku(session, get_sku(session, gap_sku_id)).price
    missing = pick("graph_gap", by_type["missing_required_part"], graph_gap)
    missing_sku_id = missing["entities"]["sku_id"]
    mismatch = pick("contract_gap", by_type["discount_category_mismatch"], contract_gap)
    blocked = pick("blocked", clean_scenarios, clean)

    return [
        DemoCase("clean", first_clean, "trusted"),
        DemoCase("clean", second_clean, "trusted"),
        DemoCase("discontinued", swap, "trusted"),
        DemoCase(
            "price_gap", priced, "flagged:price_provenance",
            correction={"sku_id": gap_sku_id, "corrected_unit_price": round(predicted * PLANTED_PRICE_MARKUP, 2)},
        ),
        DemoCase(
            "graph_gap", missing, "flagged:graph_completion",
            correction={"sku_id": missing_sku_id, "required_sku_id": requires[missing_sku_id][0]},
            graph_gap=(missing_sku_id, requires[missing_sku_id][0]),
        ),
        DemoCase(
            "contract_gap", mismatch, "flagged:contract_discount",
            correction={
                "contract_id": mismatch["entities"]["contract_id"], "category": mismatch["entities"]["sku_category"],
            },
        ),
        *pair_role("duplicate_a", "duplicate_b", "duplicate_pair"),
        *pair_role("revision_a", "revision_b", "revision_pair"),
        DemoCase("blocked", blocked, "guardrail"),
    ]
```

- [ ] **Step 4: Implement `backend/scripts/demo/seed.py`**

```python
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.consolidation.service import consolidate_review_item
from app.dedupe.service import run_dedupe
from app.estimate.constant import DATASET_AS_OF
from app.estimate.service import run_estimate
from app.graph.reader import GraphReader
from app.graph.service import rebuild_reference_graph
from app.intake.models import QuoteRequestRow
from app.intake.service import process_email
from app.judge.service import resolve_review_item, run_judge
from app.quotes.repository import estimates_for_requests, review_items_for_estimates
from app.reference_data.models import SkuRequirement
from core.graph.client import GraphClient
from core.tracing.langfuse_client import TracingClient
from demo.fakes import (
    DemoJudgeClient, DemoSetupError, ScriptedAgentClient, ScriptedExtractionClient, UnusedEmbedder, blocked_draft,
    build_draft,
)
from demo.scenarios import DemoCase

EXPECTED_DEDUPE_VERDICTS = {"duplicate_b": "DUPLICATE_OF", "revision_b": "REVISION_OF"}
RESOLVED_STATUSES = ("corrected", "consolidated")


class DemoExpectationFailed(Exception):
    """A scenario did not behave the way its role promises. The demo dataset or the fakes need attention."""


@dataclass(frozen=True)
class SeededCase:
    case: DemoCase
    quote_request_id: uuid.UUID
    estimate_id: uuid.UUID
    trusted: bool
    review_dimension: str | None


@dataclass(frozen=True)
class ReplayResult:
    case_id: str
    estimate_id: uuid.UUID
    trusted: bool
    review_dimension: str | None


def plant_gaps(session: Session, cases: list[DemoCase]) -> None:
    """Removes the requirement the graph_gap scenario is about, so the graph does not know what the reviewer will
    later tell it. The other gaps already exist in the dataset."""
    for case in cases:
        if case.graph_gap is not None:
            requirement = session.get(SkuRequirement, case.graph_gap)
            if requirement is not None:
                session.delete(requirement)
    session.flush()


def _check(case: DemoCase, status: str, trusted: bool, dimension: str | None, dedupe_verdicts: list[str]) -> None:
    if case.expectation == "trusted":
        ok = status == "ready" and trusted
    elif case.expectation == "guardrail":
        ok = status == "needs_review" and dimension == "guardrail"
    else:
        ok = status == "ready" and not trusted and dimension == case.expectation.split(":", 1)[1]
    wanted = EXPECTED_DEDUPE_VERDICTS.get(case.role)
    if wanted is not None and wanted not in dedupe_verdicts:
        raise DemoExpectationFailed(f"{case.case_id} ({case.role}) expected a {wanted} verdict, got {dedupe_verdicts}")
    if not ok:
        raise DemoExpectationFailed(
            f"{case.case_id} ({case.role}) expected {case.expectation!r} but got status={status!r} "
            f"trusted={trusted} dimension={dimension!r}"
        )


def seed(
    session: Session, client: GraphClient, ns: str, cases: list[DemoCase], scenarios: list[dict],
) -> list[SeededCase]:
    plant_gaps(session, cases)
    rebuild_reference_graph(session, client, ns)
    session.commit()

    reader = GraphReader(client, ns)
    extraction = ScriptedExtractionClient(scenarios)
    judge = DemoJudgeClient(
        graph_watch={c.graph_gap[0] for c in cases if c.graph_gap},
        contract_watch={c.scenario["entities"]["sku_id"] for c in cases if c.role == "contract_gap"},
    )
    tracing = TracingClient(None)

    seeded = []
    for case in cases:
        request = process_email(session, case.scenario["email_text"], extraction, case_id=case.case_id).row
        session.commit()
        dedupe = run_dedupe(session, request.id, tracing)
        session.commit()

        draft = build_draft(session, reader, request, DATASET_AS_OF)
        agent = ScriptedAgentClient(blocked_draft(draft) if case.role == "blocked" else draft)
        estimate = run_estimate(session, request.id, DATASET_AS_OF, agent, reader, UnusedEmbedder(), tracing)
        session.commit()
        judged = run_judge(session, reader, DATASET_AS_OF, estimate.row.id, judge)
        session.commit()

        dimension = judged.review_item.dimension if judged.review_item else None
        _check(case, estimate.result.status, judged.verdict.trusted, dimension, [v.verdict for v in dedupe])
        seeded.append(SeededCase(case, request.id, estimate.row.id, judged.verdict.trusted, dimension))
    return seeded


def _seeded_requests(session: Session) -> list[QuoteRequestRow]:
    return list(session.scalars(
        select(QuoteRequestRow).where(QuoteRequestRow.case_id.is_not(None))
        .order_by(QuoteRequestRow.created_at, QuoteRequestRow.id)
    ))


def _latest_items(session: Session, request: QuoteRequestRow):
    estimates = estimates_for_requests(session, [request.id])
    if not estimates:
        return None, []
    return estimates[0], review_items_for_estimates(session, [estimates[0].id])


def _needs_replay(items) -> bool:
    """A seeded quote whose latest estimate was flagged and has since been resolved, with nothing left open."""
    return (
        bool(items) and not any(item.status == "open" for item in items)
        and any(item.status in RESOLVED_STATUSES for item in items)
    )


def pending_replays(session: Session) -> list[str]:
    return [
        request.case_id for request in _seeded_requests(session)
        if _needs_replay(_latest_items(session, request)[1])
    ]


def _apply_planned_corrections(session: Session, cases: list[DemoCase]) -> None:
    """What a reviewer does in the UI, done in code: resolve each flagged item with the case's correction."""
    planned = {case.case_id: case for case in cases if case.correction is not None}
    for request in _seeded_requests(session):
        case = planned.get(request.case_id)
        if case is None:
            continue
        _, items = _latest_items(session, request)
        for item in items:
            if item.status == "open":
                resolve_review_item(session, item.id, "corrected", case.correction)
        session.commit()


def replay(session: Session, client: GraphClient, ns: str, cases: list[DemoCase] | None = None) -> list[ReplayResult]:
    """Re-runs estimate and judge for every seeded quote whose flag was resolved. Consolidates inline what the
    procrastinate worker would (a no-op for anything the worker already consolidated). With `cases`, first resolves
    each flagged item with the case's planned correction, so no browser is needed."""
    if cases:
        _apply_planned_corrections(session, cases)

    reader = GraphReader(client, ns)
    judge = DemoJudgeClient(graph_watch=set(), contract_watch=set())
    tracing = TracingClient(None)
    results = []
    for request in _seeded_requests(session):
        _, items = _latest_items(session, request)
        if not _needs_replay(items):
            continue
        for item in items:
            if item.status == "corrected":
                consolidate_review_item(session, client, ns, item.id)
        session.commit()

        draft = build_draft(session, reader, request, DATASET_AS_OF)
        estimate = run_estimate(
            session, request.id, DATASET_AS_OF, ScriptedAgentClient(draft), reader, UnusedEmbedder(), tracing,
        )
        session.commit()
        judged = run_judge(session, reader, DATASET_AS_OF, estimate.row.id, judge)
        session.commit()
        results.append(ReplayResult(
            request.case_id, estimate.row.id, judged.verdict.trusted,
            judged.review_item.dimension if judged.review_item else None,
        ))
    return results
```

- [ ] **Step 5: Run to verify pass**

Run: `cd backend && uv run pytest tests/test_phase7_acceptance.py -v`
Expected: PASS. This is the first time the seed runs against the real Phase 1 dataset, so failures here are data findings, not test bugs. Handle them in this order, and never loosen a check to make it pass:
1. `DemoSetupError: no scenario ... can play the 'X' role`: read the scenarios and catalog for that role and fix the predicate in `select_cases` (for example a customer name that fuzzy-matches two customers), adding a comment naming the data fact.
2. `DemoExpectationFailed`: the message names the case, role and what happened. Inspect that estimate's `violations` and `reason`, and fix `build_draft` or the judge fake if it is a fake bug, or `select_cases` if the scenario cannot play the role.
3. A `pending_replays` or replay assertion failing: check the graph sync warnings in the log; a failed best-effort sync leaves the graph stale and the next run returns `needs_review`.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/demo backend/tests/test_phase7_acceptance.py
git commit -m "feat: add the demo scenario selection, seeding and replay"
```

---

## Task 8: The seed_demo CLI

**Files:**
- Create: `backend/scripts/seed_demo.py`
- Test: `backend/tests/scripts/test_seed_demo.py`

**Interfaces:**
- Produces: `python scripts/seed_demo.py [--yes] [--replay]`. Without `--yes` it only prints. Exit code 1 with a message when the reference data or graph is missing, or when the database already holds seeded quotes and `--replay` was not given.
- Produces: `main(argv: list[str] | None = None) -> int` for testing.

- [ ] **Step 1: Write the failing test**

`backend/tests/scripts/test_seed_demo.py`:

```python
import seed_demo


def test_dry_run_and_replay_flags_parse():
    args = seed_demo.parse_args(["--yes", "--replay"])

    assert args.yes is True
    assert args.replay is True
    assert seed_demo.parse_args([]).yes is False
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && uv run pytest tests/scripts/test_seed_demo.py -v`
Expected: FAIL (`ModuleNotFoundError: seed_demo`).

- [ ] **Step 3: Implement `backend/scripts/seed_demo.py`**

```python
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select

from app.estimate.constant import DATASET_AS_OF
from app.intake.models import QuoteRequestRow
from app.reference_data.repository import all_customers
from core.config.settings import Settings
from core.db.session import make_engine, make_session_factory
from core.graph.client import GraphError, get_graph_client
from demo.fakes import DemoSetupError
from demo.scenarios import select_cases
from demo.seed import DemoExpectationFailed, pending_replays, replay, seed

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed the demo quotes through the real services with scripted LLM stand-ins "
        "(dry run unless --yes; --replay re-runs quotes whose flag has been resolved)",
    )
    parser.add_argument("--yes", action="store_true", help="write to the database and the graph")
    parser.add_argument("--replay", action="store_true", help="re-run estimate and judge for resolved quotes")
    return parser.parse_args(argv)


def _load(name: str):
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = Settings()
    session = make_session_factory(make_engine(settings.database_url))()
    try:
        if not all_customers(session):
            print("no reference data: run `python scripts/load_data.py` first", file=sys.stderr)
            return 1
        seeded_count = session.scalar(
            select(func.count()).select_from(QuoteRequestRow).where(QuoteRequestRow.case_id.is_not(None))
        )

        if args.replay:
            pending = pending_replays(session)
            print(f"{len(pending)} seeded quote(s) ready to replay: {', '.join(pending) or 'none'}")
            if not args.yes:
                print("dry run: pass --yes to replay")
                return 0
            client = get_graph_client()
            for result in replay(session, client, settings.graph_namespace):
                verdict = "trusted" if result.trusted else f"flagged ({result.review_dimension})"
                print(f"{result.case_id}: new estimate {result.estimate_id} is {verdict}")
            return 0

        if seeded_count:
            print(
                f"{seeded_count} seeded quote(s) already exist; use --replay after resolving them in the UI",
                file=sys.stderr,
            )
            return 1
        cases = select_cases(session, _load("scenarios.json"), _load("catalog.json"), DATASET_AS_OF)
        for case in cases:
            print(f"{case.role:14} {case.case_id}  expect {case.expectation}")
        if not args.yes:
            print("dry run: pass --yes to seed (this plants a graph gap and writes quotes)")
            return 0
        seeded = seed(session, get_graph_client(), settings.graph_namespace, cases, _load("scenarios.json"))
        print(f"seeded {len(seeded)} quote(s)")
        return 0
    except (DemoSetupError, DemoExpectationFailed, GraphError) as exc:
        print(f"seed failed: {exc}", file=sys.stderr)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && uv run pytest tests/scripts/test_seed_demo.py tests/test_phase7_acceptance.py -v`
Expected: pass.

- [ ] **Step 5: Dry run against the real database**

Run: `cd backend && uv run python scripts/seed_demo.py`
Expected: prints the 11 selected roles and case ids, then `dry run: pass --yes ...`. It writes nothing. If the reference data is not loaded, it says so; run `uv run python scripts/load_data.py` first. Do not run with `--yes` yet; that happens in the end-to-end verification task.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/seed_demo.py backend/tests/scripts/test_seed_demo.py
git commit -m "feat: add the seed_demo command"
```

## Task 9: Frontend scaffold

**Files (all under `frontend/`):**
- Create: `package.json` (via `npm init`), `index.html`, `vite.config.ts`, `tsconfig.json`, `.gitignore`
- Create: `src/main.tsx`, `src/App.tsx`, `src/index.css`, `src/components/AppLayout.tsx`
- Create: `src/test/setup.ts`, `src/test/render.tsx`
- Test: `src/components/AppLayout.test.tsx`

**Interfaces:**
- Produces: `App` (route table under `AppLayout`; later tasks add `<Route>` lines), `AppLayout` (header nav with links to `/`, `/quotes`, `/dashboard`, and an `<Outlet />`).
- Produces (test helpers, `src/test/render.tsx`): `renderWithProviders(ui, { route }?)`, `mockApi(routes: Record<string, (request: Request) => Response | Promise<Response>>)` where keys are `"METHOD /pathname"`, and `json(body, status?)`.

antd 6 API notes (verified against the 6.5.0 docs): `Alert` takes `title` (`message` is deprecated); `Space` uses `orientation` (`direction` is deprecated), so this plan lays out with Tailwind flex/grid instead of `Space`; `Statistic` `valueStyle` is deprecated in favor of `styles.content`; `Card`'s `bodyStyle`/`bordered` are deprecated. Use `Tabs items=`, `Descriptions items=`, `Table columns=`.

- [ ] **Step 1: Create the project and install the latest stable packages**

```bash
mkdir frontend && cd frontend
npm init -y
npm install react react-dom react-router antd @ant-design/icons @ant-design/cssinjs @tanstack/react-query openapi-fetch tailwindcss @tailwindcss/vite
npm install -D vite @vitejs/plugin-react typescript @types/react @types/react-dom @types/node vitest jsdom @testing-library/react @testing-library/user-event @testing-library/jest-dom openapi-typescript
```

Expected: installs cleanly. Record the versions npm resolved (`npm ls --depth=0`) for the README. If a peer-dependency error appears for TypeScript 7 (see the research doc), install the newest TypeScript the toolchain accepts (`npm install -D typescript@<version>`) and note the pin in `frontend/README.md`; do not use `--force`.

- [ ] **Step 2: Write the config files**

`frontend/package.json`: set these fields (keep the `dependencies`/`devDependencies` npm wrote):

```json
{
  "name": "estimate-review-ui",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "test": "vitest run",
    "gen:api": "uv run --project ../backend python ../backend/scripts/export_openapi.py openapi.json && openapi-typescript openapi.json -o src/api/schema.d.ts",
    "check:api": "node scripts/check-api-types.mjs"
  }
}
```

`frontend/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Estimate Review</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`frontend/vite.config.ts`:

```ts
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    css: false,
  },
})
```

`frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noEmit": true,
    "skipLibCheck": true,
    "isolatedModules": true,
    "verbatimModuleSyntax": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "types": ["vite/client", "node"]
  },
  "include": ["src", "scripts", "vite.config.ts"]
}
```

`frontend/.gitignore`:

```
node_modules
dist
openapi.json
*.tsbuildinfo
```

`frontend/src/index.css` (layer order first, so Tailwind's reset sits below antd's styles and utilities sit above them):

```css
@layer theme, base, antd, components, utilities;

@import "tailwindcss";
```

- [ ] **Step 3: Write the test helpers**

`frontend/src/test/setup.ts`:

```ts
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

// jsdom implements neither, and antd's responsive components read both.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
})

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver
```

`frontend/src/test/render.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'

export function renderWithProviders(ui: ReactElement, { route = '/' }: { route?: string } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

type Handler = (request: Request) => Response | Promise<Response>

export const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

/** Replaces fetch, the boundary the API client calls through. Keys are "METHOD /pathname". */
export function mockApi(routes: Record<string, Handler>) {
  const fetchMock = vi.fn(async (input: Request | string | URL) => {
    const request = input instanceof Request ? input : new Request(input)
    const key = `${request.method} ${new URL(request.url).pathname}`
    const handler = routes[key]
    if (!handler) throw new Error(`unmocked request: ${key}`)
    return handler(request)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}
```

- [ ] **Step 4: Write the failing layout test**

`frontend/src/components/AppLayout.test.tsx`:

```tsx
import { screen } from '@testing-library/react'
import { Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '../test/render'
import { AppLayout } from './AppLayout'

describe('AppLayout', () => {
  it('links to the queue, all quotes and the dashboard and renders the routed page', () => {
    renderWithProviders(
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<p>page body</p>} />
        </Route>
      </Routes>,
    )

    expect(screen.getByRole('link', { name: 'Review queue' })).toHaveAttribute('href', '/')
    expect(screen.getByRole('link', { name: 'All quotes' })).toHaveAttribute('href', '/quotes')
    expect(screen.getByRole('link', { name: 'Dashboard' })).toHaveAttribute('href', '/dashboard')
    expect(screen.getByText('page body')).toBeInTheDocument()
  })
})
```

- [ ] **Step 5: Run it to verify it fails**

Run: `cd frontend && npx vitest run`
Expected: FAIL (`Cannot find module './AppLayout'`).

- [ ] **Step 6: Implement the layout, app and entry**

`frontend/src/components/AppLayout.tsx`:

```tsx
import { Layout, Menu } from 'antd'
import { Link, Outlet, useLocation } from 'react-router'

const { Header, Content } = Layout

function selectedKey(pathname: string): string {
  if (pathname.startsWith('/dashboard')) return 'dashboard'
  if (pathname.startsWith('/quotes')) return 'quotes'
  return 'queue'
}

export function AppLayout() {
  const { pathname } = useLocation()
  return (
    <Layout className="min-h-screen">
      <Header className="flex items-center gap-8">
        <span className="text-lg font-semibold text-white">Estimate Review</span>
        <Menu
          theme="dark"
          mode="horizontal"
          selectedKeys={[selectedKey(pathname)]}
          className="flex-1"
          items={[
            { key: 'queue', label: <Link to="/">Review queue</Link> },
            { key: 'quotes', label: <Link to="/quotes">All quotes</Link> },
            { key: 'dashboard', label: <Link to="/dashboard">Dashboard</Link> },
          ]}
        />
      </Header>
      <Content className="mx-auto w-full max-w-6xl p-6">
        <Outlet />
      </Content>
    </Layout>
  )
}
```

`frontend/src/App.tsx`:

```tsx
import { Route, Routes } from 'react-router'
import { AppLayout } from './components/AppLayout'

export function App() {
  return (
    <Routes>
      <Route element={<AppLayout />} />
    </Routes>
  )
}
```

`frontend/src/main.tsx`:

```tsx
import { StyleProvider } from '@ant-design/cssinjs'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ConfigProvider } from 'antd'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { App } from './App'
import './index.css'

const queryClient = new QueryClient()
const root = document.getElementById('root')
if (!root) throw new Error('#root is missing from index.html')

createRoot(root).render(
  <StrictMode>
    <StyleProvider layer>
      <ConfigProvider>
        <QueryClientProvider client={queryClient}>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </QueryClientProvider>
      </ConfigProvider>
    </StyleProvider>
  </StrictMode>,
)
```

- [ ] **Step 7: Run tests and the type check**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: 1 test passes; `tsc` exits 0. If `react-router` does not export `Routes`, `Route`, `Link`, `Outlet`, `useLocation`, `MemoryRouter`, `BrowserRouter`, `useParams` (check `node_modules/react-router/package.json` exports and the package's docs via context7), use the package that does (`react-router-dom`) and change the imports in this and later tasks consistently.

- [ ] **Step 8: Build once to prove the toolchain**

Run: `cd frontend && npm run build`
Expected: `tsc` passes and Vite emits `dist/`. Fix any toolchain error here; later tasks assume `npm run build` works.

- [ ] **Step 9: Commit**

```bash
git add frontend
git commit -m "feat: scaffold the review UI with Vite, React, Tailwind and Ant Design"
```

---

## Task 10: API client, generated types, formatting

**Files (under `frontend/`):**
- Create: `scripts/check-api-types.mjs`, `src/api/schema.d.ts` (generated), `src/api/client.ts`, `src/api/types.ts`, `src/api/queries.ts`, `src/lib/format.ts`
- Test: `src/lib/format.test.ts`

**Interfaces:**
- Consumes: the backend routes from Tasks 1 to 4 and the existing resolve route (path params `review_item_id`, `quote_request_id`).
- Produces (`src/lib/format.ts`): `money(value: number | null | undefined): string`, `percent(value: number | null): string` (`'no data yet'` for null), `dateTime(iso: string): string`, `errorMessage(error: unknown): string`.
- Produces (`src/api/types.ts`): `ReviewItem`, `QuoteSummary`, `QuoteDetail`, `QuoteEstimate`, `QuoteReviewItem`, `QuoteJudgeVerdict`, `QuoteSkuInfo`, `DedupeVerdict`, `Metrics`, `ResolveBody`, `DraftLine`, `ReviewStatus = 'open' | 'resolved' | 'all'`.
- Produces (`src/api/queries.ts`): `ApiError`, `useReviewItems(status)`, `useQuotes()`, `useQuote(id)`, `useMetrics()`, `useResolveReviewItem()` (mutation taking `{ id: string; body: ResolveBody }`, invalidating the `review`, `quotes`, `quote` and `metrics` queries on success).

- [ ] **Step 1: Write the failing test**

`frontend/src/lib/format.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { dateTime, errorMessage, money, percent } from './format'

describe('money', () => {
  it('formats dollars and marks a missing amount', () => {
    expect(money(1234.5)).toBe('$1,234.50')
    expect(money(null)).toBe('n/a')
    expect(money(undefined)).toBe('n/a')
  })
})

describe('percent', () => {
  it('formats a rate to one decimal and says "no data yet" for a null rate', () => {
    expect(percent(0.7)).toBe('70.0%')
    expect(percent(0)).toBe('0.0%')
    expect(percent(null)).toBe('no data yet')
  })
})

describe('dateTime', () => {
  it('renders a timestamp in a short readable form', () => {
    expect(dateTime('2030-01-01T12:05:00')).toMatch(/Jan 1, 2030/)
  })
})

describe('errorMessage', () => {
  it('returns the backend detail string verbatim', () => {
    expect(errorMessage({ detail: 'review item abc is already corrected' })).toBe(
      'review item abc is already corrected',
    )
  })

  it('joins request validation errors', () => {
    expect(errorMessage({ detail: [{ msg: 'field required' }, { msg: 'bad value' }] })).toBe(
      'field required; bad value',
    )
  })

  it('falls back to an Error message, then to a generic sentence', () => {
    expect(errorMessage(new Error('network down'))).toBe('network down')
    expect(errorMessage(undefined)).toBe('The request failed.')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/lib/format.test.ts`
Expected: FAIL (`Cannot find module './format'`).

- [ ] **Step 3: Implement `src/lib/format.ts`**

```ts
const currency = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })

export function money(value: number | null | undefined): string {
  return value === null || value === undefined ? 'n/a' : currency.format(value)
}

export function percent(value: number | null): string {
  return value === null ? 'no data yet' : `${(value * 100).toFixed(1)}%`
}

export function dateTime(iso: string): string {
  return new Date(iso).toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' })
}

/** The backend's `detail` string is the message a reviewer needs (already resolved, bad correction), so it is
 * shown as written. */
export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  if (typeof error === 'object' && error !== null && 'detail' in error) {
    const { detail } = error as { detail: unknown }
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail.map((entry) => (typeof entry?.msg === 'string' ? entry.msg : JSON.stringify(entry))).join('; ')
    }
  }
  return 'The request failed.'
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend && npx vitest run src/lib/format.test.ts`
Expected: pass. (`dateTime` depends on the local timezone only in the time part; the date assertion is stable.)

- [ ] **Step 5: Generate the API types**

Run: `cd frontend && npm run gen:api`
Expected: `src/api/schema.d.ts` is written and contains `"/v1/quotes"`, `"/v1/quotes/{quote_request_id}"`, `"/v1/metrics"`, `"/v1/review"` and `QuoteDetailResponse`. `openapi.json` is gitignored.

- [ ] **Step 6: Write the API layer**

`frontend/src/api/client.ts`:

```ts
import createClient from 'openapi-fetch'
import type { paths } from './schema'

// fetch is looked up per call, not captured at import, so tests can replace globalThis.fetch.
export const api = createClient<paths>({
  baseUrl: import.meta.env.VITE_API_URL ?? 'http://localhost:8000',
  fetch: (request) => globalThis.fetch(request),
})
```

`frontend/src/api/types.ts`:

```ts
import type { components } from './schema'

type Schemas = components['schemas']

export type ReviewItem = Schemas['ReviewItemListResponse']
export type QuoteSummary = Schemas['QuoteSummaryResponse']
export type QuoteDetail = Schemas['QuoteDetailResponse']
export type QuoteEstimate = Schemas['QuoteEstimateResponse']
export type QuoteReviewItem = Schemas['QuoteReviewItemResponse']
export type QuoteJudgeVerdict = Schemas['QuoteJudgeVerdictResponse']
export type QuoteSkuInfo = Schemas['QuoteSkuInfoResponse']
export type DedupeVerdict = Schemas['QuoteDedupeVerdictResponse']
export type Metrics = Schemas['MetricsResponse']
export type ResolveBody = Schemas['ResolveReviewItemRequest']
export type DraftLine = NonNullable<QuoteEstimate['draft']>['lines'][number]

export type ReviewStatus = 'open' | 'resolved' | 'all'
```

`frontend/src/api/queries.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { errorMessage } from '../lib/format'
import { api } from './client'
import type { ResolveBody, ReviewStatus } from './types'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function unwrap<T>(request: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await request
  if (error !== undefined || data === undefined) throw new ApiError(response.status, errorMessage(error))
  return data
}

export const useReviewItems = (status: ReviewStatus) =>
  useQuery({
    queryKey: ['review', status],
    queryFn: () => unwrap(api.GET('/v1/review', { params: { query: { status } } })),
  })

export const useQuotes = () =>
  useQuery({ queryKey: ['quotes'], queryFn: () => unwrap(api.GET('/v1/quotes')) })

export const useQuote = (id: string) =>
  useQuery({
    queryKey: ['quote', id],
    queryFn: () => unwrap(api.GET('/v1/quotes/{quote_request_id}', { params: { path: { quote_request_id: id } } })),
  })

export const useMetrics = () =>
  useQuery({ queryKey: ['metrics'], queryFn: () => unwrap(api.GET('/v1/metrics')) })

export function useResolveReviewItem() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: ResolveBody }) =>
      unwrap(
        api.POST('/v1/review/{review_item_id}/resolve', { params: { path: { review_item_id: id } }, body }),
      ),
    onSuccess: async () => {
      await Promise.all(
        ['review', 'quotes', 'quote', 'metrics'].map((key) => queryClient.invalidateQueries({ queryKey: [key] })),
      )
    },
  })
}
```

`frontend/scripts/check-api-types.mjs`:

```js
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

const dir = mkdtempSync(join(tmpdir(), 'api-types-'))
const spec = join(dir, 'openapi.json')
const generated = join(dir, 'schema.d.ts')
const shell = process.platform === 'win32'

execFileSync(
  'uv',
  ['run', '--project', '../backend', 'python', '../backend/scripts/export_openapi.py', spec],
  { stdio: 'inherit', shell },
)
execFileSync('npx', ['openapi-typescript', spec, '-o', generated], { stdio: 'inherit', shell })

if (readFileSync('src/api/schema.d.ts', 'utf8') !== readFileSync(generated, 'utf8')) {
  console.error('src/api/schema.d.ts is stale: run `npm run gen:api` and commit the result')
  process.exit(1)
}
console.log('api types are current')
```

- [ ] **Step 7: Type check and the drift check**

Run: `cd frontend && npx tsc --noEmit && npm run check:api`
Expected: both pass. If `types.ts` names do not exist in `schema.d.ts` (`grep -n "QuoteDetailResponse" src/api/schema.d.ts`), a backend response class was named differently than Task 3/4 specify; fix the alias to the generated name, not the backend.

- [ ] **Step 8: Commit**

```bash
git add frontend
git commit -m "feat: add the typed API client, query hooks and formatting helpers"
```

---

## Task 11: Correction logic

**Files (under `frontend/`):**
- Create: `src/lib/correction.ts`
- Test: `src/lib/correction.test.ts`

**Interfaces:**
- Produces:
  - `type EvidenceRow = Record<string, unknown>`.
  - `interface CorrectionDraft { skuId: string; price: string; requiredSkuId: string; contractId: string; category: string }`.
  - `type CorrectionResult = { ok: true; correction: Record<string, string | number> } | { ok: false; error: string }`.
  - `buildCorrection(dimension: string, draft: CorrectionDraft): CorrectionResult`, the client-side mirror of `CORRECTION_FIELDS` and `validate_correction` in `backend/app/judge/schemas.py`.
  - `flaggedRows(evidence: Record<string, unknown>): EvidenceRow[]` (the `lines` array of a review item's evidence, `[]` if absent).
  - `flaggedSkuIds(rows: EvidenceRow[]): string[]` (unique `sku_id`s in order).
  - `flaggedContractId(rows: EvidenceRow[]): string | null`.
  - `flaggedCategories(rows: EvidenceRow[], skus: Record<string, { category: string }>): string[]` (unique categories of the flagged SKUs).

- [ ] **Step 1: Write the failing test**

`frontend/src/lib/correction.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import {
  buildCorrection,
  flaggedCategories,
  flaggedContractId,
  flaggedRows,
  flaggedSkuIds,
  type CorrectionDraft,
} from './correction'

const blank: CorrectionDraft = { skuId: 'SKU-1', price: '', requiredSkuId: '', contractId: '', category: '' }

describe('buildCorrection for price_provenance', () => {
  it('accepts a positive decimal price', () => {
    expect(buildCorrection('price_provenance', { ...blank, price: '42.50' })).toEqual({
      ok: true,
      correction: { sku_id: 'SKU-1', corrected_unit_price: 42.5 },
    })
  })

  it.each(['', '  ', '0', '-3', 'NaN', 'Infinity', '1e3', '0x10', '4,5', 'abc'])(
    'rejects %j before any network call',
    (price) => {
      const result = buildCorrection('price_provenance', { ...blank, price })
      expect(result.ok).toBe(false)
    },
  )
})

describe('buildCorrection for graph_completion', () => {
  it('accepts a different required SKU and trims it', () => {
    expect(buildCorrection('graph_completion', { ...blank, requiredSkuId: ' SKU-2 ' })).toEqual({
      ok: true,
      correction: { sku_id: 'SKU-1', required_sku_id: 'SKU-2' },
    })
  })

  it('rejects an empty required SKU', () => {
    expect(buildCorrection('graph_completion', blank)).toEqual({
      ok: false,
      error: 'Enter the SKU id of the required part.',
    })
  })

  it('rejects a SKU that requires itself', () => {
    expect(buildCorrection('graph_completion', { ...blank, requiredSkuId: 'SKU-1' })).toEqual({
      ok: false,
      error: 'A SKU cannot require itself.',
    })
  })
})

describe('buildCorrection for contract_discount', () => {
  it('accepts a contract and category', () => {
    expect(
      buildCorrection('contract_discount', { ...blank, contractId: 'CTR-1', category: 'Cat-A' }),
    ).toEqual({ ok: true, correction: { contract_id: 'CTR-1', category: 'Cat-A' } })
  })

  it('rejects a missing category', () => {
    expect(buildCorrection('contract_discount', { ...blank, contractId: 'CTR-1' }).ok).toBe(false)
  })
})

it('refuses a dimension it has no form for', () => {
  expect(buildCorrection('guardrail', blank)).toEqual({
    ok: false,
    error: 'Dimension guardrail cannot be corrected here.',
  })
})

describe('flagged evidence helpers', () => {
  const evidence = {
    dimension: 'contract_discount',
    lines: [
      { line_index: 0, sku_id: 'SKU-1', contract_id: 'CTR-1' },
      { line_index: 1, sku_id: 'SKU-2', contract_id: 'CTR-1' },
      { line_index: 2, sku_id: 'SKU-1', contract_id: 'CTR-1' },
    ],
  }

  it('reads the flagged rows, SKUs, contract and categories', () => {
    const rows = flaggedRows(evidence)
    expect(flaggedSkuIds(rows)).toEqual(['SKU-1', 'SKU-2'])
    expect(flaggedContractId(rows)).toBe('CTR-1')
    expect(
      flaggedCategories(rows, { 'SKU-1': { category: 'Cat-A' }, 'SKU-2': { category: 'Cat-A' } }),
    ).toEqual(['Cat-A'])
  })

  it('returns empty results for evidence with no lines', () => {
    expect(flaggedRows({})).toEqual([])
    expect(flaggedContractId([])).toBeNull()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/lib/correction.test.ts`
Expected: FAIL (`Cannot find module './correction'`).

- [ ] **Step 3: Implement `src/lib/correction.ts`**

```ts
export type EvidenceRow = Record<string, unknown>

export interface CorrectionDraft {
  skuId: string
  price: string
  requiredSkuId: string
  contractId: string
  category: string
}

export type CorrectionResult =
  | { ok: true; correction: Record<string, string | number> }
  | { ok: false; error: string }

// A plain decimal only: Number() alone would also accept '1e3', '0x10' and 'Infinity'.
const DECIMAL_PRICE = /^\d+(\.\d+)?$/

/** The client-side mirror of `CORRECTION_FIELDS` and `validate_correction` in backend/app/judge/schemas.py. It only
 * saves a round trip; the backend still validates and its message is shown if it disagrees. */
export function buildCorrection(dimension: string, draft: CorrectionDraft): CorrectionResult {
  switch (dimension) {
    case 'price_provenance': {
      const text = draft.price.trim()
      const price = Number(text)
      if (!DECIMAL_PRICE.test(text) || price <= 0) return { ok: false, error: 'Enter a price above zero.' }
      return { ok: true, correction: { sku_id: draft.skuId, corrected_unit_price: price } }
    }
    case 'graph_completion': {
      const required = draft.requiredSkuId.trim()
      if (required === '') return { ok: false, error: 'Enter the SKU id of the required part.' }
      if (required === draft.skuId) return { ok: false, error: 'A SKU cannot require itself.' }
      return { ok: true, correction: { sku_id: draft.skuId, required_sku_id: required } }
    }
    case 'contract_discount': {
      if (draft.contractId === '' || draft.category === '') {
        return { ok: false, error: 'Pick the contract category to confirm.' }
      }
      return { ok: true, correction: { contract_id: draft.contractId, category: draft.category } }
    }
    default:
      return { ok: false, error: `Dimension ${dimension} cannot be corrected here.` }
  }
}

export function flaggedRows(evidence: Record<string, unknown>): EvidenceRow[] {
  const lines = evidence.lines
  return Array.isArray(lines) ? (lines as EvidenceRow[]) : []
}

export function flaggedSkuIds(rows: EvidenceRow[]): string[] {
  const ids = rows.map((row) => row.sku_id).filter((id): id is string => typeof id === 'string')
  return [...new Set(ids)]
}

export function flaggedContractId(rows: EvidenceRow[]): string | null {
  const row = rows.find((candidate) => typeof candidate.contract_id === 'string')
  return row ? (row.contract_id as string) : null
}

export function flaggedCategories(rows: EvidenceRow[], skus: Record<string, { category: string }>): string[] {
  const categories = flaggedSkuIds(rows)
    .map((id) => skus[id]?.category)
    .filter((category): category is string => category !== undefined)
  return [...new Set(categories)]
}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd frontend && npx vitest run src/lib/correction.test.ts`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib
git commit -m "feat: add client-side correction validation mirroring the backend shapes"
```

## Task 12: Display components

**Files (under `frontend/`):**
- Create: `src/lib/dimensions.ts`, `src/test/fixtures.ts`
- Create: `src/components/EvidencePanel.tsx`, `EstimateLinesTable.tsx`, `DedupeVerdicts.tsx`, `JudgePanel.tsx`
- Test: `src/components/EvidencePanel.test.tsx`, `EstimateLinesTable.test.tsx`, `DedupeVerdicts.test.tsx`, `JudgePanel.test.tsx`

**Interfaces:**
- Consumes: `EvidenceRow`, `money`, `percent`, `dateTime`, and the API types from Tasks 10 and 11.
- Produces:
  - `dimensionLabel(dimension: string): string` (`price_provenance` -> `Price source`, `contract_discount` -> `Contract discount`, `graph_completion` -> `Graph completeness`, `guardrail` -> `Guardrail`, anything else -> the raw string).
  - `<EvidencePanel dimension rows skus />`, `<EstimateLinesTable estimate skus />`, `<DedupeVerdicts verdicts />`, `<JudgePanel verdict />`.
  - Test fixtures: `skus`, `reviewItem(overrides?)`, `estimate(overrides?)`, `quoteDetail(overrides?)`.

- [ ] **Step 1: Write the fixtures and the failing tests**

`frontend/src/test/fixtures.ts` (if `tsc` rejects a field because the generated schema differs, change the fixture to the generated type; the fixtures follow the response shapes in Task 3):

```ts
import type { QuoteDetail, QuoteEstimate, QuoteReviewItem, QuoteSkuInfo } from '../api/types'

export const skus: Record<string, QuoteSkuInfo> = {
  'SKU-1': { name: 'Widget', category: 'Cat-A', discontinued: false },
  'SKU-2': { name: 'Widget Mount', category: 'Cat-B', discontinued: false },
}

export function reviewItem(overrides: Partial<QuoteReviewItem> = {}): QuoteReviewItem {
  return {
    id: 'item-1',
    dimension: 'price_provenance',
    fact: 'SKU-1: the price is a peer-median prediction, not a reference list price',
    evidence: {
      dimension: 'price_provenance',
      lines: [
        {
          line_index: 0, sku_id: 'SKU-1', price_source: 'predicted', list_price: null, predicted_price: 20,
          peer_count: 3, low: 10, high: 30,
        },
      ],
    },
    line_index: 0,
    status: 'open',
    outcome: null,
    correction: null,
    resolved_at: null,
    created_at: '2030-01-01T12:00:00',
    ...overrides,
  }
}

export function estimate(overrides: Partial<QuoteEstimate> = {}): QuoteEstimate {
  return {
    estimate_id: 'est-1',
    status: 'ready',
    draft: {
      customer_id: 'CUST-1',
      contract_id: null,
      lines: [
        { sku_id: 'SKU-1', quantity: 2, unit_price: 20, price_source: 'predicted', discount_pct: 0 },
      ],
      adjustments: [],
      flags: [],
    },
    totals: { list_total: 40, discount_total: 0, net_total: 40 },
    violations: [],
    iterations: 1,
    reason: null,
    created_at: '2030-01-01T12:00:00',
    judge_verdict: {
      id: 'verdict-1',
      model: 'test-judge',
      dimensions: [
        { name: 'price_provenance', score: 0.2, rationale: 'price is a prediction', evidence: [] },
        { name: 'contract_discount', score: 0.95, rationale: 'no discount claimed', evidence: [] },
        { name: 'graph_completion', score: 0.9, rationale: 'live SKUs', evidence: [] },
      ],
      overall_confidence: 0.2,
      flagged_dimension: 'price_provenance',
      trusted: false,
      created_at: '2030-01-01T12:01:00',
    },
    review_items: [reviewItem()],
    ...overrides,
  }
}

export function quoteDetail(overrides: Partial<QuoteDetail> = {}): QuoteDetail {
  return {
    quote_request_id: 'q1',
    case_id: 'sc-0001',
    customer_id: 'CUST-1',
    site_id: null,
    contract_id: null,
    raw_email_text: 'Hi, please quote two Widgets.',
    parsed_json: {},
    created_at: '2030-01-01T11:00:00',
    dedupe_verdicts: [],
    estimates: [estimate()],
    skus,
    ...overrides,
  }
}
```

`frontend/src/components/EvidencePanel.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { skus } from '../test/fixtures'
import { EvidencePanel } from './EvidencePanel'

describe('EvidencePanel', () => {
  it('shows a predicted price with its peer basis', () => {
    render(
      <EvidencePanel
        dimension="price_provenance"
        skus={skus}
        rows={[
          { line_index: 0, sku_id: 'SKU-1', price_source: 'predicted', list_price: null, predicted_price: 20, peer_count: 3, low: 10, high: 30 },
        ]}
      />,
    )

    expect(screen.getByText('SKU-1 (Widget)')).toBeInTheDocument()
    expect(screen.getByText('predicted')).toBeInTheDocument()
    expect(screen.getByText('$20.00')).toBeInTheDocument()
    expect(screen.getByText('$10.00 to $30.00')).toBeInTheDocument()
  })

  it('shows contract coverage as not applicable when no discount was claimed', () => {
    render(
      <EvidencePanel
        dimension="contract_discount"
        skus={skus}
        rows={[
          { line_index: 0, sku_id: 'SKU-1', discount_pct: 0, contract_id: 'CTR-1', covered: null, active_on_as_of: null, days_to_expiry: null },
        ]}
      />,
    )

    expect(screen.getByText('CTR-1')).toBeInTheDocument()
    expect(screen.getAllByText('not applicable').length).toBeGreaterThan(0)
  })

  it('lists required parts and marks the missing ones', () => {
    render(
      <EvidencePanel
        dimension="graph_completion"
        skus={skus}
        rows={[
          { line_index: 0, sku_id: 'SKU-1', discontinued: false, live_sku_id: 'SKU-1', required_part_ids: ['SKU-2'], missing_required_part_ids: ['SKU-2'] },
        ]}
      />,
    )

    expect(screen.getByText('Missing from the draft')).toBeInTheDocument()
    expect(screen.getAllByText('SKU-2').length).toBe(2)
  })

  it('says so when no line evidence was stored', () => {
    render(<EvidencePanel dimension="price_provenance" skus={skus} rows={[]} />)

    expect(screen.getByText('No line evidence was stored for this fact.')).toBeInTheDocument()
  })
})
```

`frontend/src/components/EstimateLinesTable.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { estimate, skus } from '../test/fixtures'
import { EstimateLinesTable } from './EstimateLinesTable'

describe('EstimateLinesTable', () => {
  it('shows the reason instead of a table when no draft was produced', () => {
    render(
      <EstimateLinesTable
        estimate={estimate({ draft: null, totals: null, reason: 'guardrail violations persisted after 3 retries' })}
        skus={skus}
      />,
    )

    expect(screen.getByText('guardrail violations persisted after 3 retries')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('shows each line with its price source, line total and the totals', () => {
    render(<EstimateLinesTable estimate={estimate()} skus={skus} />)

    expect(screen.getByText('SKU-1 (Widget)')).toBeInTheDocument()
    expect(screen.getByText('predicted')).toBeInTheDocument()
    expect(screen.getAllByText('$40.00').length).toBeGreaterThan(0)
    expect(screen.getByText('Net total')).toBeInTheDocument()
  })

  it('lists adjustments and guardrail violations', () => {
    const withNotes = estimate()
    withNotes.draft!.adjustments = [{ kind: 'substituted', sku_id: 'SKU-2', detail: 'SKU-9 is discontinued' }]
    withNotes.violations = [{ guardrail: 'price_provenance', line_index: 0, message: 'unit_price does not match' }]

    render(<EstimateLinesTable estimate={withNotes} skus={skus} />)

    expect(screen.getByText(/SKU-9 is discontinued/)).toBeInTheDocument()
    expect(screen.getByText(/unit_price does not match/)).toBeInTheDocument()
  })
})
```

`frontend/src/components/DedupeVerdicts.test.tsx`:

```tsx
import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderWithProviders } from '../test/render'
import { DedupeVerdicts } from './DedupeVerdicts'

describe('DedupeVerdicts', () => {
  it('says so when nothing similar was found', () => {
    renderWithProviders(<DedupeVerdicts verdicts={[]} />)

    expect(screen.getByText('No similar requests were found for this customer.')).toBeInTheDocument()
  })

  it('links each candidate and shows its verdict and similarity', () => {
    renderWithProviders(
      <DedupeVerdicts
        verdicts={[
          {
            candidate_quote_request_id: 'q-other', verdict: 'DUPLICATE_OF', content_jaccard: 1, style_jaccard: 0.5,
            signals_fired: ['identical_sku_set'], created_at: '2030-01-01T12:00:00',
          },
        ]}
      />,
    )

    expect(screen.getByRole('link', { name: 'Open earlier request' })).toHaveAttribute('href', '/quotes/q-other')
    expect(screen.getByText('DUPLICATE_OF')).toBeInTheDocument()
    expect(screen.getByText('100.0%')).toBeInTheDocument()
    expect(screen.getByText('identical_sku_set')).toBeInTheDocument()
  })
})
```

`frontend/src/components/JudgePanel.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { estimate } from '../test/fixtures'
import { JudgePanel } from './JudgePanel'

describe('JudgePanel', () => {
  it('says so when the estimate was never judged', () => {
    render(<JudgePanel verdict={null} />)

    expect(screen.getByText('Not judged yet.')).toBeInTheDocument()
  })

  it('explains the guardrail fast path, where no model ran', () => {
    const verdict = { ...estimate().judge_verdict!, dimensions: [], model: 'none (guardrail fast path)' }

    render(<JudgePanel verdict={verdict} />)

    expect(screen.getByText('The guardrails blocked this draft before the judge ran.')).toBeInTheDocument()
  })

  it('shows each dimension score with its rationale', () => {
    render(<JudgePanel verdict={estimate().judge_verdict} />)

    expect(screen.getByText('price is a prediction')).toBeInTheDocument()
    expect(screen.getByText('Needs review')).toBeInTheDocument()
    expect(screen.getByText('Price source')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/components`
Expected: FAIL (component modules do not exist).

- [ ] **Step 3: Implement `src/lib/dimensions.ts`**

```ts
const LABELS: Record<string, string> = {
  price_provenance: 'Price source',
  contract_discount: 'Contract discount',
  graph_completion: 'Graph completeness',
  guardrail: 'Guardrail',
}

export function dimensionLabel(dimension: string): string {
  return LABELS[dimension] ?? dimension
}
```

- [ ] **Step 4: Implement `EvidencePanel.tsx`**

```tsx
import { Descriptions, Tag } from 'antd'
import type { ReactNode } from 'react'
import type { QuoteSkuInfo } from '../api/types'
import type { EvidenceRow } from '../lib/correction'
import { money } from '../lib/format'

interface Props {
  dimension: string
  rows: EvidenceRow[]
  skus: Record<string, QuoteSkuInfo>
}

// The judge stores these row shapes (see build_evidence in backend/app/judge/evidence.py), so a field can be null
// or absent and each reader below tolerates both.
const asText = (value: unknown): string => (typeof value === 'string' ? value : 'n/a')
const asNumber = (value: unknown): number | null => (typeof value === 'number' ? value : null)
const asList = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === 'string') : []
const yesNo = (value: unknown): string => (value === true ? 'yes' : value === false ? 'no' : 'not applicable')

function skuLabel(id: unknown, skus: Record<string, QuoteSkuInfo>): string {
  if (typeof id !== 'string') return 'unknown SKU'
  const sku = skus[id]
  return sku ? `${id} (${sku.name})` : id
}

function tags(ids: string[], color?: string): ReactNode {
  return ids.length === 0 ? 'none' : ids.map((id) => <Tag key={id} color={color}>{id}</Tag>)
}

function itemsFor(dimension: string, row: EvidenceRow) {
  switch (dimension) {
    case 'price_provenance':
      return [
        {
          key: 'source',
          label: 'Price source',
          children: <Tag color={row.price_source === 'predicted' ? 'orange' : 'green'}>{asText(row.price_source)}</Tag>,
        },
        { key: 'list', label: 'List price', children: money(asNumber(row.list_price)) },
        { key: 'predicted', label: 'Predicted price', children: money(asNumber(row.predicted_price)) },
        { key: 'peers', label: 'Peers', children: asNumber(row.peer_count) ?? 'n/a' },
        {
          key: 'range',
          label: 'Peer range',
          children: `${money(asNumber(row.low))} to ${money(asNumber(row.high))}`,
        },
      ]
    case 'contract_discount':
      return [
        { key: 'contract', label: 'Contract', children: asText(row.contract_id) },
        { key: 'discount', label: 'Discount claimed', children: `${asNumber(row.discount_pct) ?? 0}%` },
        { key: 'covered', label: 'Category covered', children: yesNo(row.covered) },
        { key: 'active', label: 'Active on the quote date', children: yesNo(row.active_on_as_of) },
        { key: 'expiry', label: 'Days to expiry', children: asNumber(row.days_to_expiry) ?? 'not applicable' },
      ]
    case 'graph_completion':
      return [
        { key: 'discontinued', label: 'Discontinued', children: yesNo(row.discontinued) },
        { key: 'live', label: 'Live replacement', children: asText(row.live_sku_id) },
        { key: 'required', label: 'Required parts', children: tags(asList(row.required_part_ids)) },
        { key: 'missing', label: 'Missing from the draft', children: tags(asList(row.missing_required_part_ids), 'red') },
      ]
    default:
      return []
  }
}

export function EvidencePanel({ dimension, rows, skus }: Props) {
  if (rows.length === 0) return <p className="text-gray-500">No line evidence was stored for this fact.</p>
  return (
    <div className="flex flex-col gap-4">
      {rows.map((row) => (
        <Descriptions
          key={`${asText(row.line_index)}-${asText(row.sku_id)}`}
          size="small"
          column={2}
          title={skuLabel(row.sku_id, skus)}
          items={itemsFor(dimension, row)}
        />
      ))}
    </div>
  )
}
```

- [ ] **Step 5: Implement `EstimateLinesTable.tsx`**

```tsx
import { Empty, Table, Tag } from 'antd'
import type { TableProps } from 'antd'
import type { DraftLine, QuoteEstimate, QuoteSkuInfo } from '../api/types'
import { money } from '../lib/format'

interface Props {
  estimate: QuoteEstimate
  skus: Record<string, QuoteSkuInfo>
}

function lineTotal(line: DraftLine): number {
  return (line.quantity ?? 0) * (line.unit_price ?? 0) * (1 - (line.discount_pct ?? 0) / 100)
}

export function EstimateLinesTable({ estimate, skus }: Props) {
  const { draft, totals } = estimate
  if (!draft) return <Empty description={estimate.reason ?? 'No draft was produced for this estimate.'} />

  const columns: TableProps<DraftLine>['columns'] = [
    {
      title: 'SKU',
      render: (_, line) => (line.sku_id && skus[line.sku_id] ? `${line.sku_id} (${skus[line.sku_id].name})` : line.sku_id),
    },
    { title: 'Qty', dataIndex: 'quantity' },
    { title: 'Unit price', render: (_, line) => money(line.unit_price) },
    {
      title: 'Source',
      render: (_, line) => <Tag color={line.price_source === 'predicted' ? 'orange' : 'green'}>{line.price_source}</Tag>,
    },
    { title: 'Discount', render: (_, line) => `${line.discount_pct ?? 0}%` },
    { title: 'Line total', render: (_, line) => money(lineTotal(line)) },
  ]

  return (
    <div className="flex flex-col gap-4">
      <Table<DraftLine>
        size="small"
        pagination={false}
        columns={columns}
        dataSource={draft.lines}
        rowKey={(line, index) => `${line.sku_id}-${index}`}
      />
      {totals && (
        <dl className="flex justify-end gap-8">
          <div><dt className="text-gray-500">List total</dt><dd>{money(totals.list_total)}</dd></div>
          <div><dt className="text-gray-500">Discount</dt><dd>{money(totals.discount_total)}</dd></div>
          <div><dt className="text-gray-500">Net total</dt><dd className="font-semibold">{money(totals.net_total)}</dd></div>
        </dl>
      )}
      {(draft.adjustments ?? []).length > 0 && (
        <ul className="list-disc pl-5">
          {(draft.adjustments ?? []).map((adjustment, index) => (
            <li key={index}>{adjustment.kind}: {adjustment.detail}</li>
          ))}
        </ul>
      )}
      {estimate.violations.length > 0 && (
        <ul className="list-disc pl-5 text-red-700">
          {estimate.violations.map((violation, index) => (
            <li key={index}>{violation.guardrail}: {violation.message}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
```

- [ ] **Step 6: Implement `DedupeVerdicts.tsx` and `JudgePanel.tsx`**

`DedupeVerdicts.tsx`:

```tsx
import { Table, Tag } from 'antd'
import type { TableProps } from 'antd'
import { Link } from 'react-router'
import type { DedupeVerdict } from '../api/types'
import { percent } from '../lib/format'

const VERDICT_COLORS: Record<string, string> = { DUPLICATE_OF: 'red', REVISION_OF: 'gold', DISTINCT: 'default' }

export function DedupeVerdicts({ verdicts }: { verdicts: DedupeVerdict[] }) {
  if (verdicts.length === 0) {
    return <p className="text-gray-500">No similar requests were found for this customer.</p>
  }
  const columns: TableProps<DedupeVerdict>['columns'] = [
    {
      title: 'Compared with',
      render: (_, verdict) => <Link to={`/quotes/${verdict.candidate_quote_request_id}`}>Open earlier request</Link>,
    },
    {
      title: 'Verdict',
      render: (_, verdict) => <Tag color={VERDICT_COLORS[verdict.verdict]}>{verdict.verdict}</Tag>,
    },
    { title: 'Same items', render: (_, verdict) => percent(verdict.content_jaccard) },
    { title: 'Same wording', render: (_, verdict) => percent(verdict.style_jaccard) },
    {
      title: 'Signals',
      render: (_, verdict) => verdict.signals_fired.map((signal) => <Tag key={signal}>{signal}</Tag>),
    },
  ]
  return (
    <Table<DedupeVerdict>
      size="small"
      pagination={false}
      columns={columns}
      dataSource={verdicts}
      rowKey="candidate_quote_request_id"
    />
  )
}
```

`JudgePanel.tsx`:

```tsx
import { Progress, Tag } from 'antd'
import type { QuoteJudgeVerdict } from '../api/types'
import { dimensionLabel } from '../lib/dimensions'

export function JudgePanel({ verdict }: { verdict: QuoteJudgeVerdict | null }) {
  if (verdict === null) return <p className="text-gray-500">Not judged yet.</p>
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <Tag color={verdict.trusted ? 'green' : 'gold'}>{verdict.trusted ? 'Auto-send' : 'Needs review'}</Tag>
        <span className="text-gray-500">
          {verdict.model}, overall confidence {verdict.overall_confidence.toFixed(2)}
        </span>
      </div>
      {verdict.dimensions.length === 0 ? (
        <p>The guardrails blocked this draft before the judge ran.</p>
      ) : (
        verdict.dimensions.map((dimension) => (
          <div key={dimension.name} className="grid grid-cols-[10rem_12rem_1fr] items-center gap-3">
            <span>{dimensionLabel(dimension.name)}</span>
            <Progress percent={Math.round(dimension.score * 100)} size="small" />
            <span className="text-gray-600">{dimension.rationale}</span>
          </div>
        ))
      )}
    </div>
  )
}
```

- [ ] **Step 7: Run tests and type check**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: all pass. The `!` non-null assertions and direct mutation appear only in the test files, where the fixtures guarantee the values; production code has none.

- [ ] **Step 8: Commit**

```bash
git add frontend/src
git commit -m "feat: add evidence, estimate lines, dedupe and judge display components"
```

---

## Task 13: Flagged fact card and correction form

**Files (under `frontend/`):**
- Create: `src/components/CorrectionForm.tsx`, `src/components/FlaggedFactCard.tsx`
- Test: `src/components/FlaggedFactCard.test.tsx`

**Interfaces:**
- Consumes: `buildCorrection`, `flaggedRows`, `flaggedSkuIds`, `flaggedContractId`, `flaggedCategories`, `useResolveReviewItem`, `EvidencePanel`, `dimensionLabel`, `dateTime`.
- Produces:
  - `<CorrectionForm item skus busy onSubmit onCancel />` where `onSubmit(correction: Record<string, string | number>)`.
  - `<FlaggedFactCard item skus />` (`item: QuoteReviewItem`): a container that posts to `POST /v1/review/{id}/resolve`. Approve sends `{ outcome: 'approved' }`; Correct sends `{ outcome: 'corrected', correction }`. States: open, resolved (read-only outcome and correction), guardrail (violation list, no buttons).
  - Constant text `CORRECTION_SAVED = 'Correction saved. It is applied to the reference data in the background.'`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/FlaggedFactCard.test.tsx`:

```tsx
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { json, mockApi, renderWithProviders } from '../test/render'
import { reviewItem, skus } from '../test/fixtures'
import { FlaggedFactCard } from './FlaggedFactCard'

const RESOLVE = 'POST /v1/review/item-1/resolve'
const RESOLVED_OK = { id: 'item-1', status: 'corrected', outcome: 'corrected', correction: null, consolidation_enqueued: true }

function resolveMock(status = 200, body: unknown = RESOLVED_OK) {
  const bodies: unknown[] = []
  mockApi({
    [RESOLVE]: async (request) => {
      bodies.push(await request.json())
      return json(body, status)
    },
    'GET /v1/review': () => json([]),
  })
  return bodies
}

describe('FlaggedFactCard open item', () => {
  it('shows the one fact and the evidence with Approve and Correct actions', () => {
    renderWithProviders(<FlaggedFactCard item={reviewItem()} skus={skus} />)

    expect(screen.getByText(/the price is a peer-median prediction/)).toBeInTheDocument()
    expect(screen.getByText('Predicted price')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve as is' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Correct' })).toBeInTheDocument()
  })

  it('approves without a correction', async () => {
    const bodies = resolveMock(200, { ...RESOLVED_OK, status: 'approved', outcome: 'approved' })
    renderWithProviders(<FlaggedFactCard item={reviewItem()} skus={skus} />)

    await userEvent.click(screen.getByRole('button', { name: 'Approve as is' }))

    await waitFor(() => expect(bodies).toEqual([{ outcome: 'approved' }]))
  })

  it('blocks a bad price before any network call', async () => {
    const bodies = resolveMock()
    renderWithProviders(<FlaggedFactCard item={reviewItem()} skus={skus} />)

    await userEvent.click(screen.getByRole('button', { name: 'Correct' }))
    await userEvent.type(screen.getByLabelText('Correct unit price (USD)'), '0')
    await userEvent.click(screen.getByRole('button', { name: 'Save correction' }))

    expect(screen.getByText('Enter a price above zero.')).toBeInTheDocument()
    expect(bodies).toEqual([])
  })

  it('submits a valid price correction and says it is applied in the background', async () => {
    const bodies = resolveMock()
    renderWithProviders(<FlaggedFactCard item={reviewItem()} skus={skus} />)

    await userEvent.click(screen.getByRole('button', { name: 'Correct' }))
    await userEvent.type(screen.getByLabelText('Correct unit price (USD)'), '42.5')
    await userEvent.click(screen.getByRole('button', { name: 'Save correction' }))

    await waitFor(() =>
      expect(bodies).toEqual([
        { outcome: 'corrected', correction: { sku_id: 'SKU-1', corrected_unit_price: 42.5 } },
      ]),
    )
    expect(
      await screen.findByText('Correction saved. It is applied to the reference data in the background.'),
    ).toBeInTheDocument()
  })

  it('shows the backend detail verbatim when the item was already resolved', async () => {
    resolveMock(409, { detail: "review item item-1 is already 'corrected'" })
    renderWithProviders(<FlaggedFactCard item={reviewItem()} skus={skus} />)

    await userEvent.click(screen.getByRole('button', { name: 'Approve as is' }))

    expect(await screen.findByText("review item item-1 is already 'corrected'")).toBeInTheDocument()
  })

  it('shows the backend detail verbatim when the correction is rejected', async () => {
    resolveMock(422, { detail: "sku_id 'SKU-9' was not flagged by this review item" })
    renderWithProviders(<FlaggedFactCard item={reviewItem()} skus={skus} />)

    await userEvent.click(screen.getByRole('button', { name: 'Correct' }))
    await userEvent.type(screen.getByLabelText('Correct unit price (USD)'), '10')
    await userEvent.click(screen.getByRole('button', { name: 'Save correction' }))

    expect(await screen.findByText("sku_id 'SKU-9' was not flagged by this review item")).toBeInTheDocument()
  })
})

describe('FlaggedFactCard other dimensions', () => {
  it('asks for the required part of a graph_completion item and refuses a self-requirement', async () => {
    const item = reviewItem({
      dimension: 'graph_completion',
      fact: 'SKU-1 is quoted with no required part recorded',
      evidence: {
        dimension: 'graph_completion',
        lines: [
          { line_index: 0, sku_id: 'SKU-1', discontinued: false, live_sku_id: 'SKU-1', required_part_ids: [], missing_required_part_ids: [] },
        ],
      },
    })
    const bodies = resolveMock()
    renderWithProviders(<FlaggedFactCard item={item} skus={skus} />)

    await userEvent.click(screen.getByRole('button', { name: 'Correct' }))
    await userEvent.type(screen.getByLabelText('Required part (SKU id)'), 'SKU-1')
    await userEvent.click(screen.getByRole('button', { name: 'Save correction' }))

    expect(screen.getByText('A SKU cannot require itself.')).toBeInTheDocument()

    await userEvent.clear(screen.getByLabelText('Required part (SKU id)'))
    await userEvent.type(screen.getByLabelText('Required part (SKU id)'), 'SKU-2')
    await userEvent.click(screen.getByRole('button', { name: 'Save correction' }))

    await waitFor(() =>
      expect(bodies).toEqual([
        { outcome: 'corrected', correction: { sku_id: 'SKU-1', required_sku_id: 'SKU-2' } },
      ]),
    )
  })

  it('prefills the contract and category of a contract_discount item', async () => {
    const item = reviewItem({
      dimension: 'contract_discount',
      fact: 'SKU-1: a contract customer is quoted at full price',
      evidence: {
        dimension: 'contract_discount',
        lines: [
          { line_index: 0, sku_id: 'SKU-1', discount_pct: 0, contract_id: 'CTR-1', covered: null, active_on_as_of: null, days_to_expiry: null },
        ],
      },
    })
    const bodies = resolveMock()
    renderWithProviders(<FlaggedFactCard item={item} skus={skus} />)

    await userEvent.click(screen.getByRole('button', { name: 'Correct' }))
    expect(screen.getByText('Confirm that CTR-1 covers Cat-A.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Save correction' }))

    await waitFor(() =>
      expect(bodies).toEqual([
        { outcome: 'corrected', correction: { contract_id: 'CTR-1', category: 'Cat-A' } },
      ]),
    )
  })
})

describe('FlaggedFactCard read-only states', () => {
  it('shows a resolved item as read-only with its outcome and correction', () => {
    const item = reviewItem({
      status: 'consolidated',
      outcome: 'corrected',
      correction: { sku_id: 'SKU-1', corrected_unit_price: 42.5 },
      resolved_at: '2030-01-02T09:00:00',
    })

    renderWithProviders(<FlaggedFactCard item={item} skus={skus} />)

    expect(screen.getByText('Applied to the reference data.')).toBeInTheDocument()
    expect(screen.getByText(/corrected_unit_price/)).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('shows a guardrail item with its violations and no actions', () => {
    const item = reviewItem({
      dimension: 'guardrail',
      fact: 'guardrail violations persisted after 3 retries',
      evidence: { violations: [{ guardrail: 'required_fields', line_index: 0, message: 'line quantity must be a whole number above 0' }] },
    })

    renderWithProviders(<FlaggedFactCard item={item} skus={skus} />)

    expect(screen.getByText('line quantity must be a whole number above 0', { exact: false })).toBeInTheDocument()
    expect(screen.getByText('Guardrail-blocked drafts cannot be resolved from this screen yet.')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/components/FlaggedFactCard.test.tsx`
Expected: FAIL (modules do not exist).

- [ ] **Step 3: Implement `CorrectionForm.tsx`**

```tsx
import { Alert, Button, Input, Select } from 'antd'
import { useState } from 'react'
import type { QuoteReviewItem, QuoteSkuInfo } from '../api/types'
import {
  buildCorrection,
  flaggedCategories,
  flaggedContractId,
  flaggedRows,
  flaggedSkuIds,
  type CorrectionDraft,
} from '../lib/correction'

interface Props {
  item: QuoteReviewItem
  skus: Record<string, QuoteSkuInfo>
  busy: boolean
  onSubmit: (correction: Record<string, string | number>) => void
  onCancel: () => void
}

export function CorrectionForm({ item, skus, busy, onSubmit, onCancel }: Props) {
  const rows = flaggedRows(item.evidence)
  const skuIds = flaggedSkuIds(rows)
  const categories = flaggedCategories(rows, skus)
  const [draft, setDraft] = useState<CorrectionDraft>({
    skuId: skuIds[0] ?? '',
    price: '',
    requiredSkuId: '',
    contractId: flaggedContractId(rows) ?? '',
    category: categories.length === 1 ? categories[0] : '',
  })
  const [error, setError] = useState<string | null>(null)
  const update = (patch: Partial<CorrectionDraft>) => setDraft((current) => ({ ...current, ...patch }))

  function submit() {
    const result = buildCorrection(item.dimension, draft)
    if (!result.ok) {
      setError(result.error)
      return
    }
    setError(null)
    onSubmit(result.correction)
  }

  return (
    <div className="flex flex-col gap-3">
      {(item.dimension === 'price_provenance' || item.dimension === 'graph_completion') &&
        (skuIds.length > 1 ? (
          <Select
            aria-label="SKU"
            value={draft.skuId}
            onChange={(skuId) => update({ skuId })}
            options={skuIds.map((id) => ({ value: id, label: skus[id] ? `${id} (${skus[id].name})` : id }))}
          />
        ) : (
          <p>SKU: {draft.skuId}</p>
        ))}

      {item.dimension === 'price_provenance' && (
        <div className="flex flex-col gap-1">
          <label htmlFor="corrected-price">Correct unit price (USD)</label>
          <Input
            id="corrected-price"
            inputMode="decimal"
            value={draft.price}
            onChange={(event) => update({ price: event.target.value })}
          />
        </div>
      )}

      {item.dimension === 'graph_completion' && (
        <div className="flex flex-col gap-1">
          <label htmlFor="required-sku">Required part (SKU id)</label>
          <Input
            id="required-sku"
            value={draft.requiredSkuId}
            onChange={(event) => update({ requiredSkuId: event.target.value })}
          />
        </div>
      )}

      {item.dimension === 'contract_discount' &&
        (categories.length > 1 ? (
          <Select
            aria-label="Category"
            value={draft.category || undefined}
            onChange={(category) => update({ category })}
            options={categories.map((category) => ({ value: category, label: category }))}
          />
        ) : (
          <p>Confirm that {draft.contractId} covers {draft.category}.</p>
        ))}

      {error && <Alert type="error" title={error} />}
      <div className="flex gap-3">
        <Button type="primary" loading={busy} onClick={submit}>Save correction</Button>
        <Button onClick={onCancel} disabled={busy}>Cancel</Button>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Implement `FlaggedFactCard.tsx`**

```tsx
import { Alert, Button, Card, Tag } from 'antd'
import { useState } from 'react'
import { useResolveReviewItem } from '../api/queries'
import type { QuoteReviewItem, QuoteSkuInfo } from '../api/types'
import { flaggedRows } from '../lib/correction'
import { dimensionLabel } from '../lib/dimensions'
import { dateTime } from '../lib/format'
import { CorrectionForm } from './CorrectionForm'
import { EvidencePanel } from './EvidencePanel'

export const CORRECTION_SAVED = 'Correction saved. It is applied to the reference data in the background.'

interface Props {
  item: QuoteReviewItem
  skus: Record<string, QuoteSkuInfo>
}

interface Violation {
  guardrail?: string
  line_index?: number | null
  message?: string
}

function GuardrailNotice({ item }: { item: QuoteReviewItem }) {
  const violations = Array.isArray(item.evidence.violations) ? (item.evidence.violations as Violation[]) : []
  return (
    <Card title={<>Blocked by guardrails <Tag color="red">{dimensionLabel(item.dimension)}</Tag></>}>
      <div className="flex flex-col gap-3">
        <p className="text-base font-medium">{item.fact}</p>
        {violations.length > 0 && (
          <ul className="list-disc pl-5">
            {violations.map((violation, index) => (
              <li key={index}>
                {violation.line_index != null ? `line ${violation.line_index}: ` : ''}
                {violation.message}
              </li>
            ))}
          </ul>
        )}
        <Alert type="info" title="Guardrail-blocked drafts cannot be resolved from this screen yet." />
      </div>
    </Card>
  )
}

function ResolvedSummary({ item }: { item: QuoteReviewItem }) {
  const message =
    item.status === 'consolidated'
      ? 'Applied to the reference data.'
      : item.status === 'corrected'
        ? CORRECTION_SAVED
        : 'Approved as is.'
  return (
    <Card title={<>Resolved <Tag>{dimensionLabel(item.dimension)}</Tag></>}>
      <div className="flex flex-col gap-3">
        <p className="text-base font-medium">{item.fact}</p>
        <Alert type="success" title={message} />
        {item.correction && <pre className="rounded bg-gray-50 p-3">{JSON.stringify(item.correction, null, 2)}</pre>}
        {item.resolved_at && <p className="text-gray-500">Resolved {dateTime(item.resolved_at)}</p>}
      </div>
    </Card>
  )
}

export function FlaggedFactCard({ item, skus }: Props) {
  const resolve = useResolveReviewItem()
  const [correcting, setCorrecting] = useState(false)

  if (item.dimension === 'guardrail') return <GuardrailNotice item={item} />
  if (item.status !== 'open') return <ResolvedSummary item={item} />

  const saved = resolve.isSuccess && resolve.variables.body.outcome === 'corrected'
  return (
    <Card title={<>Check this <Tag color="gold">{dimensionLabel(item.dimension)}</Tag></>}>
      <div className="flex flex-col gap-4">
        <p className="text-base font-medium">{item.fact}</p>
        <EvidencePanel dimension={item.dimension} rows={flaggedRows(item.evidence)} skus={skus} />
        {resolve.isError && <Alert type="error" title={resolve.error.message} />}
        {saved ? (
          <Alert type="success" title={CORRECTION_SAVED} />
        ) : correcting ? (
          <CorrectionForm
            item={item}
            skus={skus}
            busy={resolve.isPending}
            onCancel={() => setCorrecting(false)}
            onSubmit={(correction) => resolve.mutate({ id: item.id, body: { outcome: 'corrected', correction } })}
          />
        ) : (
          <div className="flex gap-3">
            <Button
              type="primary"
              loading={resolve.isPending}
              onClick={() => resolve.mutate({ id: item.id, body: { outcome: 'approved' } })}
            >
              Approve as is
            </Button>
            <Button onClick={() => setCorrecting(true)}>Correct</Button>
          </div>
        )}
      </div>
    </Card>
  )
}
```

- [ ] **Step 5: Run tests and type check**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: all pass. If `resolve.variables.body.outcome` does not type-check because `variables` can be undefined when idle, narrow with `resolve.variables?.body.outcome`. If `getByLabelText('Correct unit price (USD)')` fails, antd's `Input` did not forward `id`; wrap with `aria-label` instead and drop the `<label>`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "feat: add the flagged fact card and per-dimension correction form"
```

## Task 14: Queue, quotes and quote detail pages

**Files (under `frontend/`):**
- Create: `src/components/EstimateHistory.tsx`, `src/pages/QueuePage.tsx`, `src/pages/QuotesPage.tsx`, `src/pages/QuoteDetailPage.tsx`
- Modify: `src/App.tsx` (routes)
- Test: `src/pages/QueuePage.test.tsx`, `src/pages/QuotesPage.test.tsx`, `src/pages/QuoteDetailPage.test.tsx`

**Interfaces:**
- Consumes: `useReviewItems`, `useQuotes`, `useQuote`, `dimensionLabel`, `dateTime`, `EstimateLinesTable`, `JudgePanel`, `DedupeVerdicts`, `FlaggedFactCard`.
- Produces: routes `/` (`QueuePage`), `/quotes` (`QuotesPage`), `/quotes/:id` (`QuoteDetailPage`). `<EstimateHistory estimates skus />`: tabs, newest first, labelled `Latest estimate` then `Earlier estimate N`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/pages/QueuePage.test.tsx`:

```tsx
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { ReviewItem } from '../api/types'
import { json, mockApi, renderWithProviders } from '../test/render'
import { QueuePage } from './QueuePage'

function queueItem(overrides: Partial<ReviewItem> = {}): ReviewItem {
  return {
    id: 'item-1', estimate_id: 'est-1', quote_request_id: 'q1', dimension: 'price_provenance',
    fact: 'SKU-1: the price is a peer-median prediction', evidence: {}, line_index: 0, status: 'open',
    outcome: null, correction: null, resolved_at: null, created_at: '2030-01-01T12:00:00', ...overrides,
  }
}

describe('QueuePage', () => {
  it('lists open flags with the fact to check and a link to the quote', async () => {
    mockApi({ 'GET /v1/review': () => json([queueItem()]) })

    renderWithProviders(<QueuePage />)

    expect(await screen.findByText('SKU-1: the price is a peer-median prediction')).toBeInTheDocument()
    expect(screen.getByText('Price source')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open quote' })).toHaveAttribute('href', '/quotes/q1')
  })

  it('says the queue is clear when nothing is open', async () => {
    mockApi({ 'GET /v1/review': () => json([]) })

    renderWithProviders(<QueuePage />)

    expect(await screen.findByText('The queue is clear.')).toBeInTheDocument()
  })

  it('asks for resolved items when the filter changes and shows their outcome', async () => {
    mockApi({
      'GET /v1/review': (request) =>
        json(
          new URL(request.url).searchParams.get('status') === 'resolved'
            ? [queueItem({ id: 'item-2', status: 'consolidated', outcome: 'corrected', fact: 'an old fact' })]
            : [],
        ),
    })

    renderWithProviders(<QueuePage />)
    await userEvent.click(await screen.findByText('Resolved'))

    expect(await screen.findByText('an old fact')).toBeInTheDocument()
    expect(screen.getByText('corrected')).toBeInTheDocument()
  })

  it('shows the backend detail when the request fails', async () => {
    mockApi({ 'GET /v1/review': () => json({ detail: 'database unavailable' }, 500) })

    renderWithProviders(<QueuePage />)

    expect(await screen.findByText('database unavailable')).toBeInTheDocument()
  })
})
```

`frontend/src/pages/QuotesPage.test.tsx`:

```tsx
import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { json, mockApi, renderWithProviders } from '../test/render'
import { QuotesPage } from './QuotesPage'

const base = {
  quote_request_id: 'q1', case_id: 'sc-0001', customer_id: 'CUST-1', created_at: '2030-01-01T12:00:00',
  estimate_count: 2, latest_estimate_status: 'ready', latest_trusted: true, open_review_items: 0, is_duplicate: false,
}

describe('QuotesPage', () => {
  it('shows each quote with its latest estimate, judge outcome and duplicate flag', async () => {
    mockApi({
      'GET /v1/quotes': () =>
        json([
          base,
          { ...base, quote_request_id: 'q2', case_id: 'sc-0002', latest_trusted: null, is_duplicate: true },
          { ...base, quote_request_id: 'q3', case_id: 'sc-0003', latest_estimate_status: null, latest_trusted: false, estimate_count: 0 },
        ]),
    })

    renderWithProviders(<QuotesPage />)

    expect(await screen.findByRole('link', { name: 'sc-0001' })).toHaveAttribute('href', '/quotes/q1')
    expect(screen.getByText('Auto-send')).toBeInTheDocument()
    expect(screen.getByText('Not judged')).toBeInTheDocument()
    expect(screen.getByText('duplicate')).toBeInTheDocument()
    expect(screen.getByText('none')).toBeInTheDocument()
  })
})
```

`frontend/src/pages/QuoteDetailPage.test.tsx`:

```tsx
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'
import { estimate, quoteDetail, reviewItem } from '../test/fixtures'
import { json, mockApi, renderWithProviders } from '../test/render'
import { QuoteDetailPage } from './QuoteDetailPage'

function renderDetail() {
  return renderWithProviders(
    <Routes>
      <Route path="/quotes/:id" element={<QuoteDetailPage />} />
    </Routes>,
    { route: '/quotes/q1' },
  )
}

describe('QuoteDetailPage', () => {
  it('shows the email, the dedupe verdicts and the flagged fact of a single estimate', async () => {
    mockApi({
      'GET /v1/quotes/q1': () =>
        json(quoteDetail({
          dedupe_verdicts: [{
            candidate_quote_request_id: 'q0', verdict: 'DUPLICATE_OF', content_jaccard: 1, style_jaccard: 0.9,
            signals_fired: ['identical_sku_set'], created_at: '2030-01-01T11:30:00',
          }],
        })),
    })

    renderDetail()

    expect(await screen.findByText('Hi, please quote two Widgets.')).toBeInTheDocument()
    expect(screen.getByText('DUPLICATE_OF')).toBeInTheDocument()
    expect(screen.getByText(/the price is a peer-median prediction/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve as is' })).toBeInTheDocument()
  })

  it('shows a corrected quote as two estimates: the clean latest one first, the flagged earlier one behind a tab', async () => {
    const earlier = estimate({
      estimate_id: 'est-1',
      review_items: [reviewItem({ status: 'consolidated', outcome: 'corrected', correction: { sku_id: 'SKU-1', corrected_unit_price: 42.5 } })],
    })
    const latest = estimate({
      estimate_id: 'est-2',
      created_at: '2030-01-02T12:00:00',
      draft: { customer_id: 'CUST-1', contract_id: null, lines: [{ sku_id: 'SKU-1', quantity: 2, unit_price: 42.5, price_source: 'list', discount_pct: 0 }], adjustments: [], flags: [] },
      totals: { list_total: 85, discount_total: 0, net_total: 85 },
      judge_verdict: { ...estimate().judge_verdict!, trusted: true, overall_confidence: 0.9 },
      review_items: [],
    })
    mockApi({ 'GET /v1/quotes/q1': () => json(quoteDetail({ estimates: [latest, earlier] })) })

    renderDetail()

    expect(await screen.findByRole('tab', { name: 'Latest estimate' })).toBeInTheDocument()
    expect(screen.getByText('Auto-sent: the judge trusted this estimate, so no reviewer action was needed.')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('tab', { name: 'Earlier estimate 1' }))

    expect(await screen.findByText('Applied to the reference data.')).toBeInTheDocument()
  })

  it('shows a guardrail-blocked estimate with its reason and no actions', async () => {
    const blocked = estimate({
      status: 'needs_review', draft: null, totals: null, reason: 'guardrail violations persisted after 3 retries',
      judge_verdict: { ...estimate().judge_verdict!, dimensions: [], model: 'none (guardrail fast path)', trusted: false },
      review_items: [reviewItem({
        dimension: 'guardrail', fact: 'guardrail violations persisted after 3 retries',
        evidence: { violations: [{ guardrail: 'required_fields', line_index: 0, message: 'line quantity must be a whole number above 0' }] },
      })],
    })
    mockApi({ 'GET /v1/quotes/q1': () => json(quoteDetail({ estimates: [blocked] })) })

    renderDetail()

    expect(await screen.findByText('Guardrail-blocked drafts cannot be resolved from this screen yet.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve as is' })).not.toBeInTheDocument()
  })

  it('says so when no estimate has run yet', async () => {
    mockApi({ 'GET /v1/quotes/q1': () => json(quoteDetail({ estimates: [] })) })

    renderDetail()

    expect(await screen.findByText('No estimate has been run for this quote yet.')).toBeInTheDocument()
  })

  it('shows the backend detail for an unknown quote', async () => {
    mockApi({ 'GET /v1/quotes/q1': () => json({ detail: 'quote request q1 not found' }, 404) })

    renderDetail()

    expect(await screen.findByText('quote request q1 not found')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/pages`
Expected: FAIL (pages do not exist).

- [ ] **Step 3: Implement `EstimateHistory.tsx`**

```tsx
import { Alert, Empty, Tabs, Tag } from 'antd'
import type { QuoteEstimate, QuoteSkuInfo } from '../api/types'
import { dateTime } from '../lib/format'
import { EstimateLinesTable } from './EstimateLinesTable'
import { FlaggedFactCard } from './FlaggedFactCard'
import { JudgePanel } from './JudgePanel'

interface Props {
  estimates: QuoteEstimate[]
  skus: Record<string, QuoteSkuInfo>
}

function EstimatePanel({ estimate, skus }: { estimate: QuoteEstimate; skus: Record<string, QuoteSkuInfo> }) {
  const autoSent = estimate.judge_verdict?.trusted === true && estimate.review_items.length === 0
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <Tag color={estimate.status === 'ready' ? 'green' : 'red'}>{estimate.status}</Tag>
        <span className="text-gray-500">
          {estimate.iterations} submission(s), created {dateTime(estimate.created_at)}
        </span>
      </div>
      {autoSent && (
        <Alert type="success" title="Auto-sent: the judge trusted this estimate, so no reviewer action was needed." />
      )}
      <EstimateLinesTable estimate={estimate} skus={skus} />
      <JudgePanel verdict={estimate.judge_verdict} />
      {estimate.review_items.map((item) => (
        <FlaggedFactCard key={item.id} item={item} skus={skus} />
      ))}
    </div>
  )
}

export function EstimateHistory({ estimates, skus }: Props) {
  if (estimates.length === 0) return <Empty description="No estimate has been run for this quote yet." />
  return (
    <Tabs
      items={estimates.map((estimate, index) => ({
        key: estimate.estimate_id,
        label: index === 0 ? 'Latest estimate' : `Earlier estimate ${estimates.length - index}`,
        children: <EstimatePanel estimate={estimate} skus={skus} />,
      }))}
    />
  )
}
```

- [ ] **Step 4: Implement the pages**

`src/pages/QueuePage.tsx`:

```tsx
import { Alert, Segmented, Spin, Table, Tag } from 'antd'
import type { TableProps } from 'antd'
import { useState } from 'react'
import { Link } from 'react-router'
import { useReviewItems } from '../api/queries'
import type { ReviewItem, ReviewStatus } from '../api/types'
import { dimensionLabel } from '../lib/dimensions'
import { dateTime } from '../lib/format'

const COLUMNS: TableProps<ReviewItem>['columns'] = [
  { title: 'Flag', render: (_, item) => <Tag color="gold">{dimensionLabel(item.dimension)}</Tag> },
  { title: 'Fact to check', dataIndex: 'fact' },
  { title: 'Quote', render: (_, item) => <Link to={`/quotes/${item.quote_request_id}`}>Open quote</Link> },
  { title: 'Raised', render: (_, item) => dateTime(item.created_at) },
  {
    title: 'Status',
    render: (_, item) => (item.status === 'open' ? <Tag color="gold">open</Tag> : <Tag>{item.outcome ?? item.status}</Tag>),
  },
]

export function QueuePage() {
  const [status, setStatus] = useState<ReviewStatus>('open')
  const { data, error, isLoading } = useReviewItems(status)

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold">Review queue</h1>
      <Segmented<ReviewStatus>
        value={status}
        onChange={setStatus}
        options={[
          { label: 'Open', value: 'open' },
          { label: 'Resolved', value: 'resolved' },
          { label: 'All', value: 'all' },
        ]}
      />
      {isLoading && <Spin />}
      {error && <Alert type="error" title={error.message} />}
      {data && (
        <Table<ReviewItem>
          columns={COLUMNS}
          dataSource={data}
          rowKey="id"
          pagination={false}
          locale={{ emptyText: status === 'open' ? 'The queue is clear.' : 'Nothing to show for this filter.' }}
        />
      )}
    </div>
  )
}
```

`src/pages/QuotesPage.tsx`:

```tsx
import { Alert, Spin, Table, Tag } from 'antd'
import type { TableProps } from 'antd'
import { Link } from 'react-router'
import { useQuotes } from '../api/queries'
import type { QuoteSummary } from '../api/types'
import { dateTime } from '../lib/format'

function judgeTag(trusted: boolean | null) {
  if (trusted === null) return <Tag>Not judged</Tag>
  return trusted ? <Tag color="green">Auto-send</Tag> : <Tag color="gold">Needs review</Tag>
}

const COLUMNS: TableProps<QuoteSummary>['columns'] = [
  {
    title: 'Quote',
    render: (_, quote) => (
      <Link to={`/quotes/${quote.quote_request_id}`}>{quote.case_id ?? quote.quote_request_id.slice(0, 8)}</Link>
    ),
  },
  { title: 'Customer', render: (_, quote) => quote.customer_id ?? 'unresolved' },
  {
    title: 'Latest estimate',
    render: (_, quote) =>
      quote.latest_estimate_status ? (
        <Tag color={quote.latest_estimate_status === 'ready' ? 'green' : 'red'}>{quote.latest_estimate_status}</Tag>
      ) : (
        'none'
      ),
  },
  { title: 'Judge', render: (_, quote) => judgeTag(quote.latest_trusted) },
  { title: 'Open flags', dataIndex: 'open_review_items' },
  { title: 'Duplicate', render: (_, quote) => (quote.is_duplicate ? <Tag color="red">duplicate</Tag> : null) },
  { title: 'Received', render: (_, quote) => dateTime(quote.created_at) },
]

export function QuotesPage() {
  const { data, error, isLoading } = useQuotes()
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold">All quotes</h1>
      {isLoading && <Spin />}
      {error && <Alert type="error" title={error.message} />}
      {data && (
        <Table<QuoteSummary>
          columns={COLUMNS}
          dataSource={data}
          rowKey="quote_request_id"
          pagination={false}
          locale={{ emptyText: 'No quotes yet.' }}
        />
      )}
    </div>
  )
}
```

`src/pages/QuoteDetailPage.tsx`:

```tsx
import { Alert, Card, Spin, Tag } from 'antd'
import { useParams } from 'react-router'
import { useQuote } from '../api/queries'
import { DedupeVerdicts } from '../components/DedupeVerdicts'
import { EstimateHistory } from '../components/EstimateHistory'

export function QuoteDetailPage() {
  const { id = '' } = useParams<{ id: string }>()
  const { data, error, isLoading } = useQuote(id)

  if (isLoading) return <Spin />
  if (error) return <Alert type="error" title={error.message} />
  if (!data) return null

  const isDuplicate = data.dedupe_verdicts.some((verdict) => verdict.verdict === 'DUPLICATE_OF')
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-semibold">Quote {data.case_id ?? data.quote_request_id.slice(0, 8)}</h1>
        {isDuplicate && <Tag color="red">duplicate</Tag>}
        <span className="text-gray-500">Customer {data.customer_id ?? 'unresolved'}</span>
      </div>
      <Card title="Customer email">
        <pre className="whitespace-pre-wrap font-sans">{data.raw_email_text}</pre>
      </Card>
      <Card title="Similar requests">
        <DedupeVerdicts verdicts={data.dedupe_verdicts} />
      </Card>
      <Card title="Estimates">
        <EstimateHistory estimates={data.estimates} skus={data.skus} />
      </Card>
    </div>
  )
}
```

- [ ] **Step 5: Wire the routes**

Replace `frontend/src/App.tsx` with:

```tsx
import { Route, Routes } from 'react-router'
import { AppLayout } from './components/AppLayout'
import { QueuePage } from './pages/QueuePage'
import { QuoteDetailPage } from './pages/QuoteDetailPage'
import { QuotesPage } from './pages/QuotesPage'

export function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<QueuePage />} />
        <Route path="quotes" element={<QuotesPage />} />
        <Route path="quotes/:id" element={<QuoteDetailPage />} />
      </Route>
    </Routes>
  )
}
```

- [ ] **Step 6: Run tests and type check**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: all pass. The "Resolved" text in the queue test matches the Segmented option, not a table cell, because the table is empty in the open state.

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "feat: add the queue, all-quotes and quote detail pages"
```

---

## Task 15: Dashboard

**Files (under `frontend/`):**
- Create: `src/pages/DashboardPage.tsx`
- Modify: `src/App.tsx` (route)
- Test: `src/pages/DashboardPage.test.tsx`

**Interfaces:**
- Consumes: `useMetrics`, `percent`.
- Produces: route `/dashboard` (`DashboardPage`): three `Statistic` cards (auto-send, correction, duplicate), each with the stated definition and an "n of m" line; `no data yet` when a rate is `null`.

- [ ] **Step 1: Write the failing test**

`frontend/src/pages/DashboardPage.test.tsx`:

```tsx
import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { json, mockApi, renderWithProviders } from '../test/render'
import { DashboardPage } from './DashboardPage'

const counts = {
  verdicts_total: 10, verdicts_trusted: 7, review_items_resolved: 4, review_items_corrected: 3,
  requests_compared: 5, requests_duplicate: 1,
}

describe('DashboardPage', () => {
  it('shows each rate with the count it was computed from', async () => {
    mockApi({
      'GET /v1/metrics': () => json({ auto_send_rate: 0.7, correction_rate: 0.75, duplicate_rate: 0.2, counts }),
    })

    renderWithProviders(<DashboardPage />)

    expect(await screen.findByText('70.0%')).toBeInTheDocument()
    expect(screen.getByText('7 of 10 judge verdicts were trusted')).toBeInTheDocument()
    expect(screen.getByText('75.0%')).toBeInTheDocument()
    expect(screen.getByText('3 of 4 resolved review items were corrected')).toBeInTheDocument()
    expect(screen.getByText('20.0%')).toBeInTheDocument()
    expect(screen.getByText('1 of 5 compared requests are duplicates')).toBeInTheDocument()
  })

  it('says "no data yet" for a rate with nothing behind it, never 0%', async () => {
    mockApi({
      'GET /v1/metrics': () =>
        json({
          auto_send_rate: null, correction_rate: null, duplicate_rate: null,
          counts: {
            verdicts_total: 0, verdicts_trusted: 0, review_items_resolved: 0, review_items_corrected: 0,
            requests_compared: 0, requests_duplicate: 0,
          },
        }),
    })

    renderWithProviders(<DashboardPage />)

    expect(await screen.findAllByText('no data yet')).toHaveLength(3)
    expect(screen.queryByText('0.0%')).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npx vitest run src/pages/DashboardPage.test.tsx`
Expected: FAIL (`DashboardPage` does not exist).

- [ ] **Step 3: Implement `DashboardPage.tsx`**

```tsx
import { Alert, Card, Spin, Statistic } from 'antd'
import { useMetrics } from '../api/queries'
import { percent } from '../lib/format'

interface RateCardProps {
  title: string
  rate: number | null
  detail: string
  definition: string
}

function RateCard({ title, rate, detail, definition }: RateCardProps) {
  return (
    <Card>
      <Statistic title={title} value={percent(rate)} />
      <p className="mt-2">{detail}</p>
      <p className="mt-1 text-gray-500">{definition}</p>
    </Card>
  )
}

export function DashboardPage() {
  const { data, error, isLoading } = useMetrics()
  if (isLoading) return <Spin />
  if (error) return <Alert type="error" title={error.message} />
  if (!data) return null

  const { counts } = data
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <div className="grid gap-4 md:grid-cols-3">
        <RateCard
          title="Auto-send rate"
          rate={data.auto_send_rate}
          detail={`${counts.verdicts_trusted} of ${counts.verdicts_total} judge verdicts were trusted`}
          definition="Trusted judge verdicts divided by all judge verdicts."
        />
        <RateCard
          title="Correction rate"
          rate={data.correction_rate}
          detail={`${counts.review_items_corrected} of ${counts.review_items_resolved} resolved review items were corrected`}
          definition="Corrected review items divided by resolved review items."
        />
        <RateCard
          title="Duplicate rate"
          rate={data.duplicate_rate}
          detail={`${counts.requests_duplicate} of ${counts.requests_compared} compared requests are duplicates`}
          definition="Requests with a DUPLICATE_OF verdict divided by requests that have any dedupe verdict."
        />
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Add the route**

In `frontend/src/App.tsx` add `import { DashboardPage } from './pages/DashboardPage'` and, inside the layout route, `<Route path="dashboard" element={<DashboardPage />} />`.

- [ ] **Step 5: Run the full frontend suite, type check and build**

Run: `cd frontend && npx vitest run && npx tsc --noEmit && npm run build`
Expected: all pass and `dist/` is emitted.

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "feat: add the dashboard with the three tracked rates"
```

---

## Task 16: End-to-end verification and documentation

**Files:**
- Create: `frontend/README.md`, `docs/interview-prep/phase7-interview.md`
- Modify: `docs/roadmap.md` (Phase 7 status), `docs/superpowers/specs/2026-09-30-phase7-review-ui-design.md` (record what changed during planning), `README.md` only if it lists run steps that now differ

This task runs against the real dev database and graph. Steps 2 and 3 write to them (they plant a graph gap and add quotes), so stop and get the user's go-ahead before running them.

- [ ] **Step 1: Full automated verification**

Run: `cd backend && uv run pytest -q` and `cd frontend && npx vitest run && npx tsc --noEmit && npm run check:api && npm run build`
Expected: all green. Postgres and Neo4j must be up (`docker compose up -d` from the repo root; Neo4j is `neo4j-estimate` on 17687).

- [ ] **Step 2: Prepare the dev database (after the user agrees)**

Run from `backend/`:

```bash
uv run alembic upgrade head
uv run python scripts/load_data.py
uv run python scripts/seed_demo.py
```

Expected: migrations apply (including 0007 for procrastinate), the dataset loads, and the dry run prints 11 roles with case ids and `dry run: pass --yes`.

- [ ] **Step 3: Seed, then start the stack (after the user agrees)**

```bash
cd backend && uv run python scripts/seed_demo.py --yes
cd backend && uv run python main.py            # API on :8000
cd frontend && npm run dev                      # UI on :5173
```

Expected from the seed: `seeded 11 quote(s)`. If it exits with `seed failed:`, the message names the case and role; fix per Task 7 Step 5, do not weaken the check.

- [ ] **Step 4: Walk the done-when in the browser**

Use the `run` skill (or the browser tools) against http://localhost:5173 and check, reporting only what was actually seen:
1. The queue lists 4 open flags: price source, graph completeness, contract discount, and a guardrail item.
2. Opening the price flag shows the quote email, the estimate lines with a `predicted` price, the judge scores, the evidence (peer count and range) and Approve as is / Correct.
3. Opening the guardrail flag shows the violation list and no buttons.
4. Correcting the price flag with a positive number shows "Correction saved. It is applied to the reference data in the background."; submitting a `0` shows the client-side error; the item leaves the Open filter and appears under Resolved.
5. Run `cd backend && uv run python scripts/seed_demo.py --replay --yes`. Expected: it consolidates the correction inline and prints `... new estimate ... is trusted` for that quote.
6. Reload the quote detail: two estimates, the Latest one clean with the auto-sent notice, the Earlier one flagged and marked resolved.
7. The Dashboard shows the three rates with counts; the correction rate is no longer "no data yet".
8. Repeat for the other two correctable flags if time allows; at minimum one full loop must be observed.

If any of these is not observed, say so in the roadmap status and in the final report; do not claim it from the test suite.

- [ ] **Step 5: Write `frontend/README.md`**

It must contain: what the app is (one paragraph); prerequisites (Node 20.19+ or 22.12+, `docker compose up -d`, backend migrated and loaded); run procedure (the commands of Step 3); how to regenerate API types (`npm run gen:api`) and check them (`npm run check:api`); the test and build commands; the resolved versions from `npm ls --depth=0` (and any TypeScript pin, with the reason); the Tailwind + antd layer setup and why; and the known gaps list from the spec's "Deferred gaps".

- [ ] **Step 6: Update the spec with what changed while planning**

In `docs/superpowers/specs/2026-09-30-phase7-review-ui-design.md`, record these changes (edit the relevant sections, no changelog section):
- Review list response also carries `quote_request_id`, `outcome`, `correction`, `resolved_at`.
- Quote detail also carries a `skus` map (name, category, discontinued) for every SKU an estimate or evidence mentions, and per-estimate `totals`; the contract correction form needs the SKU category and the lines table needs names.
- A fourth screen: `All quotes` (`GET /v1/quotes` needs a consumer, and it is the only place clean, auto-sent and duplicate quotes are visible).
- The seed script's `--replay` no longer resolves anything itself. It re-runs estimate and judge for seeded quotes whose flag a reviewer resolved in the UI, consolidating inline what the worker would. Auto-correction lives in `demo.seed.replay(cases=...)` for the acceptance test.
- Demo module names: `scripts/demo/{fakes,scenarios,seed}.py`; scenarios are selected from the dataset by predicates (a scenario that cannot fill a role fails loudly), and the graph gap is planted by deleting one `SkuRequirement` row.
- `Alert` uses `title`, layout uses Tailwind instead of `Space` (antd 6 deprecations).
- The frontend has no ESLint; `tsc --noEmit` is the static gate.

- [ ] **Step 7: Update the roadmap**

In `docs/roadmap.md`, add a `Status:` line under Phase 7 in the same style as Phases 3 to 6: complete (with the spec path), what is built, what was observed in Step 4 and what was not, and known gaps (no pipeline-trigger UI, guardrail items read-only, evidence is a stored snapshot, scripted judge proves plumbing not model judgment, TypeScript pin if any). Use only facts observed in this task.

- [ ] **Step 8: Write the interview prep doc**

Read `docs/interview-prep/phase6-interview.md` and follow its structure and plain-language teaching tone. `docs/interview-prep/phase7-interview.md` must cover: what Phase 7 proves (a correction visibly changes the next quote); why the backend stayed read-only except for one existing write; why the seed drives real services with scripted LLM stand-ins instead of fixture rows; how the UI avoids inventing evidence (stored snapshot); why Tailwind and antd need cascade layers; why types are generated from OpenAPI; what the scripted judge does and does not prove; and the honest gaps. No em dash, no emoji.

- [ ] **Step 9: Commit**

```bash
git add frontend/README.md docs
git commit -m "docs: record Phase 7 verification, spec changes and interview prep"
```

- [ ] **Step 10: Report**

State plainly what was verified and how (test counts, build, the browser walk-through with what was and was not observed), and list any deferred gaps. Suggest the user update their project-status memory to "Phases 1-7 done" only after confirming the browser walk-through passed.





