# Phase 6: LLMOps and Tracing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the loop where a human correcting a judge-flagged estimate becomes a permanent fact the system never gets wrong again, plus Langfuse tracing over every run, and a release gate on the judge's false-auto-send rate.

**Architecture:** A new `POST /v1/review/{review_item_id}/resolve` endpoint records a reviewer's approve/correct decision, always growing a real eval set (`eval_cases`) from production corrections. A `corrected` outcome enqueues a `procrastinate` (ADR-0003) background task that writes the missing reference fact straight into the Postgres table the relevant code guardrail already reads (`Sku.list_price`, a new `SkuRequirement` row, or an appended `Contract.covered_categories` entry), then best-effort syncs the one Neo4j node/edge affected. `scripts/calibrate_judge.py` gains a false-auto-send ceiling check computed from the golden set plus `eval_cases`. A thin `TracingClient` wraps the real Langfuse SDK and no-ops with no configured instance, instrumented at the estimate agent loop, its tool calls, its graph-integrity check, and dedupe's verdict decisions.

**Tech Stack:** FastAPI, SQLAlchemy 2.x (sync), Alembic, `procrastinate` (`PsycopgConnector`), `langfuse` Python SDK, pytest against a real local Postgres (5433) and Neo4j (17687).

**Spec:** `docs/superpowers/specs/2026-09-29-phase6-llmops-tracing-design.md`

## Global Constraints

- Postgres is always host port 5433, never 5432. Neo4j is always host ports 17474/17687, never the defaults.
- No AI attribution in commits. No em dash anywhere (code, comments, docs). No emojis anywhere.
- Tests never assert absolute counts against the shared dev Postgres/Neo4j; every test uses its own uniquely-named rows/namespace and the existing `db_session` (transactional rollback) / `graph_ns` (unique namespace, cleaned up) fixtures.
- No real OpenAI, Anthropic, or Langfuse network calls anywhere in the test suite. `scripts/calibrate_judge.py` stays dry-run-by-default, gated on `--yes`.
- SQLAlchemy sessions run with `autoflush=False` (already the project default via `make_session_factory`); call `session.flush()` explicitly wherever a later read in the same function needs to see an uncommitted write, matching existing repository functions' own comments on this.
- Stage files by explicit path only in any commit; never `git add -A` or `git add .`.
- Layer order is route -> service -> repository -> DB/LLM, per `docs/backend-structure.txt`. Follow this codebase's existing conventions exactly: constructor/`Depends`-injected clients (never a global singleton client), frozen dataclasses for per-run contexts, domain exceptions defined near where they are raised and mapped to HTTP status codes only at the route layer.
- `procrastinate`'s connector is `PsycopgConnector` (async). The worker needs it (a sync connector cannot run a worker); the API opens the same app sync in its lifespan so the sync resolve route can `.defer()`. Superseded the original `SyncPsycopgConnector` choice in the final review fix wave.
- `FALSE_AUTO_SEND_CEILING = 0.05` (5%) is the release gate's ceiling constant.
- `eval_cases.case_id` uses an `"rc-"` prefix (reviewer-corrected); the hand-authored golden set's is `"jg-"`.
- Only `price_provenance`, `graph_completion`, and `contract_discount` review items are resolvable through `POST /v1/review/{id}/resolve`; a `dimension == "guardrail"` (fast-path) review item is rejected, not silently accepted (see Task 7's design note).

## Review Focus

1. **Resolving a `graph_completion` or `contract_discount` correction must not leave the graph looking stale afterward.** `reference_fingerprint()` (in `app/reference_data/repository.py`) includes `SkuRequirement` rows and `Contract.covered_categories`; the stored `GraphMeta.reference_fingerprint` is only rewritten by a full `rebuild_reference_graph`. A best-effort single-edge sync that does not also refresh `GraphMeta` would make `graph_is_current()` return `False` for every estimate run afterward, blocking everything, not just the corrected scenario. Task 3's `sync_requirement`/`sync_contract_coverage` must refresh `GraphMeta` themselves; Task 6's acceptance tests must assert `graph_is_current()` stays `True` after consolidation, not just that the edge/property exists.
2. **Resolving the same review item twice must reject the second call outright**, not double-enqueue a consolidation task or double-write an eval case. Task 7 tests this explicitly.
3. **A correction naming a SKU, required SKU, or contract not actually named in that review item's own stored evidence must be rejected at resolve time**, before it ever reaches the background queue, so a bad correction fails the request instead of silently no-oping in a worker nobody is watching. Task 5/7 tests cover all three dimension shapes.
4. **`TracingClient` with no configured Langfuse instance (`client=None`, the default) must never raise `AttributeError` anywhere it is called** — every instrumented call site (tool dispatch, graph-integrity check, dedupe verdicts, the root trace itself) must run correctly end to end with zero Langfuse configuration, since that is this project's default state. Tasks 4, 10, 11 test the `None` path explicitly, not just the fake-client path.
5. **The false-auto-send ceiling check must actually block writing a new `calibration.json` when breached**, not just print a warning and write anyway. Task 9 tests both sides: a case set that clears the ceiling writes the file, one engineered to breach it does not, and the file's prior contents (if any) are left untouched.

---

## File Structure

New files:
- `backend/migrations/versions/0006_review_resolution_and_eval_cases.py`
- `backend/app/consolidation/__init__.py`, `backend/app/consolidation/service.py`, `backend/app/consolidation/tasks.py`
- `backend/core/tracing/__init__.py`, `backend/core/tracing/langfuse_client.py`
- `backend/api/v1/review/request.py`
- `backend/scripts/run_worker.py`
- `backend/tests/app/consolidation/__init__.py`, `backend/tests/app/consolidation/test_service.py`, `backend/tests/app/consolidation/test_tasks.py`
- `backend/tests/core/test_langfuse_client.py`
- `backend/tests/scripts/__init__.py`, `backend/tests/scripts/test_calibrate_judge.py`
- `backend/tests/api/v1/test_review_resolve_route.py`

Modified files (touched by more than one task; each task below states exactly which lines/functions):
- `backend/app/judge/models.py`, `backend/app/judge/schemas.py`, `backend/app/judge/repository.py`, `backend/app/judge/service.py`, `backend/app/judge/constant.py`, `backend/app/judge/calibration.py`
- `backend/app/reference_data/repository.py`
- `backend/app/graph/service.py`
- `backend/app/estimate/tools.py`, `backend/app/estimate/graph.py`, `backend/app/estimate/service.py`
- `backend/app/dedupe/service.py`
- `backend/api/v1/review/response.py`, `backend/api/v1/review/route.py`, `backend/api/v1/estimate/route.py`, `backend/api/v1/dedupe/route.py`
- `backend/core/config/settings.py`
- `backend/scripts/calibrate_judge.py`
- `backend/tests/graph_support.py` (add optional `trace` param to `make_ctx`)
- `backend/migrations/env.py` (register `app.consolidation` if it grows any SQLAlchemy models — it does not; only `procrastinate`'s own tables, which alembic never manages, so no edit needed there in practice, confirmed in Task 6)
- `backend/pyproject.toml` (`procrastinate`, `langfuse` dependencies)

---

## Task 1: `review_items` resolution columns, `eval_cases` table, migration 0006

**Files:**
- Modify: `backend/app/judge/models.py`
- Create: `backend/migrations/versions/0006_review_resolution_and_eval_cases.py`
- Test: `backend/tests/app/judge/test_repository.py` (extend existing file)

**Interfaces:**
- Produces: `ReviewItemRow.outcome: str | None`, `.correction: dict | None`, `.resolved_at: datetime | None`; `EvalCaseRow(id, source_review_item_id, case_id, label, estimate_status, evidence, created_at)`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/app/judge/test_repository.py -- add at end of file
import uuid as uuid_mod

from app.judge.models import EvalCaseRow


def test_review_item_row_has_resolution_columns(db_session):
    from app.judge.repository import save_judge_verdict, save_review_item

    verdict = save_judge_verdict(
        db_session, estimate_id=uuid_mod.uuid4(), model="m", dimensions=[], overall_confidence=0.1,
        flagged_dimension="price_provenance", trusted=False,
    )
    row = save_review_item(
        db_session, judge_verdict_id=verdict.id, estimate_id=verdict.estimate_id, dimension="price_provenance",
        fact="thin evidence", evidence={"lines": []}, line_index=None,
    )

    assert row.outcome is None
    assert row.correction is None
    assert row.resolved_at is None


def test_eval_case_row_round_trips(db_session):
    row = EvalCaseRow(
        id=uuid_mod.uuid4(), source_review_item_id=None, case_id="rc-0001", label="escalate",
        estimate_status="ready", evidence=[{"line_index": 0, "sku_id": "SKU-X"}],
    )
    db_session.add(row)
    db_session.flush()

    fetched = db_session.get(EvalCaseRow, row.id)
    assert fetched.case_id == "rc-0001"
    assert fetched.label == "escalate"
    assert fetched.evidence == [{"line_index": 0, "sku_id": "SKU-X"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/app/judge/test_repository.py -v -k "resolution_columns or eval_case_row"`
Expected: FAIL — `TypeError` (unexpected keyword `outcome`) or `ImportError: cannot import name 'EvalCaseRow'`.

- [ ] **Step 3: Add the model columns and `EvalCaseRow`**

```python
# backend/app/judge/models.py -- add imports and extend the file
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from core.db.base import Base


class JudgeVerdictRow(Base):
    # ... unchanged, existing class stays as-is ...


class ReviewItemRow(Base):
    __tablename__ = "review_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    judge_verdict_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("judge_verdicts.id"), index=True)
    estimate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("estimate_drafts.id"), index=True)
    dimension: Mapped[str] = mapped_column(Text)
    fact: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONB)
    line_index: Mapped[int | None]
    status: Mapped[str] = mapped_column(Text, server_default=text("'open'"))
    outcome: Mapped[str | None] = mapped_column(Text)
    correction: Mapped[dict | None] = mapped_column(JSONB)
    resolved_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class EvalCaseRow(Base):
    __tablename__ = "eval_cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_review_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("review_items.id"))
    case_id: Mapped[str] = mapped_column(Text, unique=True)
    label: Mapped[str] = mapped_column(Text)
    estimate_status: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
```

Keep `JudgeVerdictRow` exactly as it already is; only `ReviewItemRow` gains the three new columns, and `EvalCaseRow` is new.

- [ ] **Step 4: Write the migration**

```python
# backend/migrations/versions/0006_review_resolution_and_eval_cases.py
"""review resolution columns and eval cases

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-29

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("review_items", sa.Column("outcome", sa.Text(), nullable=True))
    op.add_column("review_items", sa.Column("correction", JSONB(), nullable=True))
    op.add_column("review_items", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "eval_cases",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source_review_item_id", UUID(as_uuid=True), sa.ForeignKey("review_items.id"), nullable=True),
        sa.Column("case_id", sa.Text(), nullable=False, unique=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("estimate_status", sa.Text(), nullable=False),
        sa.Column("evidence", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("eval_cases")
    op.drop_column("review_items", "resolved_at")
    op.drop_column("review_items", "correction")
    op.drop_column("review_items", "outcome")
```

Apply it against the dev database before running any test in this plan:

Run: `cd backend && alembic upgrade head`
Expected: `Running upgrade 0005 -> 0006, review resolution columns and eval cases`

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/app/judge/test_repository.py -v -k "resolution_columns or eval_case_row"`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/judge/models.py backend/migrations/versions/0006_review_resolution_and_eval_cases.py backend/tests/app/judge/test_repository.py
git commit -m "feat: add review resolution columns and eval_cases table"
```

---

## Task 2: reference-data writer functions for consolidation

**Files:**
- Modify: `backend/app/reference_data/repository.py`
- Test: `backend/tests/app/reference_data/test_repository.py`

**Interfaces:**
- Produces: `set_sku_list_price(session, sku_id: str, list_price: float) -> None`; `add_contract_coverage(session, contract_id: str, category: str) -> None`. (`graph_completion` correction reuses the existing `upsert_requirement(session, sku_id=..., required_sku_id=...)`, already idempotent via `session.merge`, no new function needed.)

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/app/reference_data/test_repository.py -- add at end of file
from app.reference_data.models import Contract, Sku
from app.reference_data.repository import add_contract_coverage, set_sku_list_price
from tests.app.estimate.seed import seed_world


def test_set_sku_list_price_updates_the_row(db_session):
    seed_world(db_session)

    set_sku_list_price(db_session, "SKU-E-GAP", 42.50)

    assert db_session.get(Sku, "SKU-E-GAP").list_price == 42.50


def test_add_contract_coverage_appends_a_new_category(db_session):
    seed_world(db_session)

    add_contract_coverage(db_session, "CTR-E1", "Cat-E-B")

    assert db_session.get(Contract, "CTR-E1").covered_categories == ["Cat-E-A", "Cat-E-B"]


def test_add_contract_coverage_is_idempotent(db_session):
    seed_world(db_session)

    add_contract_coverage(db_session, "CTR-E1", "Cat-E-A")

    assert db_session.get(Contract, "CTR-E1").covered_categories == ["Cat-E-A"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/app/reference_data/test_repository.py -v -k "set_sku_list_price or add_contract_coverage"`
Expected: FAIL — `ImportError: cannot import name 'set_sku_list_price'`.

- [ ] **Step 3: Implement**

```python
# backend/app/reference_data/repository.py -- add after get_contract (around line 85)
def set_sku_list_price(session: Session, sku_id: str, list_price: float) -> None:
    sku = session.get(Sku, sku_id)
    sku.list_price = list_price


def add_contract_coverage(session: Session, contract_id: str, category: str) -> None:
    contract = session.get(Contract, contract_id)
    if category not in contract.covered_categories:
        contract.covered_categories = [*contract.covered_categories, category]
```

No explicit `session.flush()` needed in either: these mutate an already-loaded ORM instance's attribute, which SQLAlchemy tracks and flushes at the caller's next flush/commit, same as every other setter-style mutation already in this codebase (e.g. `set_sku_family`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/app/reference_data/test_repository.py -v -k "set_sku_list_price or add_contract_coverage"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/reference_data/repository.py backend/tests/app/reference_data/test_repository.py
git commit -m "feat: add sku price and contract coverage writers for consolidation"
```

---

## Task 3: graph sync functions for consolidated facts

**Files:**
- Modify: `backend/app/graph/service.py`
- Test: `backend/tests/app/graph/test_sync.py`

**Interfaces:**
- Consumes: `merge_nodes`, `merge_edges`, `_edge` (already in this file); `reference_fingerprint` (already imported in this file); `get_sku` (already imported).
- Produces: `sync_sku(session, client, ns, sku_id) -> None`; `sync_requirement(session, client, ns, sku_id, required_sku_id) -> None`; `sync_contract_coverage(session, client, ns, contract_id, category) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/app/graph/test_sync.py -- add at end of file
from app.graph.service import sync_contract_coverage, sync_requirement, sync_sku
from app.reference_data.repository import add_contract_coverage, reference_fingerprint, set_sku_list_price, upsert_requirement


def test_sync_sku_updates_the_price_property(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    set_sku_list_price(db_session, "SKU-E-GAP", 42.5)

    sync_sku(db_session, graph_client, graph_ns, "SKU-E-GAP")

    assert graph_node(graph_client, graph_ns, "SKU-E-GAP")["props"]["list_price"] == 42.5


def test_sync_requirement_adds_the_edge_and_keeps_the_graph_current(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    upsert_requirement(db_session, sku_id="SKU-E-GAP", required_sku_id="SKU-E-A1")
    db_session.flush()

    sync_requirement(db_session, graph_client, graph_ns, "SKU-E-GAP", "SKU-E-A1")

    assert graph_edge_count(graph_client, graph_ns, "SKU-E-GAP", "REQUIRES", "SKU-E-A1") == 1
    from app.graph.reader import GraphReader
    assert GraphReader(graph_client, graph_ns).stored_fingerprint() == reference_fingerprint(db_session)


def test_sync_contract_coverage_adds_the_edge_and_keeps_the_graph_current(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    add_contract_coverage(db_session, "CTR-E1", "Cat-E-B")
    db_session.flush()

    sync_contract_coverage(db_session, graph_client, graph_ns, "CTR-E1", "Cat-E-B")

    assert graph_edge_count(graph_client, graph_ns, "CTR-E1", "COVERS", "Cat-E-B") == 1
    from app.graph.reader import GraphReader
    assert GraphReader(graph_client, graph_ns).stored_fingerprint() == reference_fingerprint(db_session)


def test_sync_contract_coverage_creates_a_brand_new_category_node(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    add_contract_coverage(db_session, "CTR-E1", "Cat-E-NEW")
    db_session.flush()

    sync_contract_coverage(db_session, graph_client, graph_ns, "CTR-E1", "Cat-E-NEW")

    assert graph_node(graph_client, graph_ns, "Cat-E-NEW") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/app/graph/test_sync.py -v -k "sync_sku_updates or sync_requirement_adds or sync_contract_coverage"`
Expected: FAIL — `ImportError: cannot import name 'sync_sku'`.

- [ ] **Step 3: Implement**

```python
# backend/app/graph/service.py -- add after sync_quote (before class GraphRebuildInProgress)
def sync_sku(session: Session, client: GraphClient, ns: str, sku_id: str) -> None:
    sku = get_sku(session, sku_id)
    if sku is None:
        return
    merge_nodes(client, ns, "SKU", [{"id": sku.sku_id, "props": {
        "name": sku.name, "category": sku.category, "list_price": sku.list_price,
        "discontinued": sku.discontinued, "in_stock": sku.in_stock,
    }}])


def _touch_graph_meta(session: Session, client: GraphClient, ns: str) -> None:
    """Corrections to SkuRequirement or Contract.covered_categories change reference_fingerprint(); without this,
    graph_is_current() would see the fact as applied but the graph as stale, and block every future estimate."""
    merge_nodes(client, ns, "GraphMeta", [{"id": ns, "props": {
        "reference_fingerprint": reference_fingerprint(session),
        "built_at": datetime.now(timezone.utc).isoformat(),
    }}])


def sync_requirement(session: Session, client: GraphClient, ns: str, sku_id: str, required_sku_id: str) -> None:
    merge_edges(client, ns, "REQUIRES", "SKU", "SKU", [_edge(sku_id, required_sku_id)])
    _touch_graph_meta(session, client, ns)


def sync_contract_coverage(session: Session, client: GraphClient, ns: str, contract_id: str, category: str) -> None:
    merge_nodes(client, ns, "PricingCategory", [{"id": category, "props": {}}])
    merge_edges(client, ns, "COVERS", "Contract", "PricingCategory", [_edge(contract_id, category)])
    _touch_graph_meta(session, client, ns)
```

`get_sku`, `merge_nodes`, `merge_edges`, `_edge`, `reference_fingerprint`, `datetime`, `timezone` are all already imported at the top of `app/graph/service.py` (used by `rebuild_reference_graph`/`sync_sku`'s neighbors); no new imports needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/app/graph/test_sync.py -v -k "sync_sku_updates or sync_requirement_adds or sync_contract_coverage"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/graph/service.py backend/tests/app/graph/test_sync.py
git commit -m "feat: add single-fact graph syncs for sku price, requirement, and coverage corrections"
```

---

## Task 4: `TracingClient` (Langfuse, no-op by default)

**Files:**
- Create: `backend/core/tracing/__init__.py` (empty), `backend/core/tracing/langfuse_client.py`
- Modify: `backend/core/config/settings.py`
- Modify: `backend/pyproject.toml` (add `langfuse` dependency)
- Test: `backend/tests/core/test_langfuse_client.py`

**Interfaces:**
- Produces: `TraceHandle` (`.span(name, **metadata)` context manager returning a `TraceHandle`; `.update(**metadata)`), `TracingClient(client: Langfuse | None)` (`.trace(name, **metadata)` context manager returning a `TraceHandle`), `get_tracing_client() -> TracingClient` (module-level, mirrors `get_graph_client`).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/core/test_langfuse_client.py
from core.tracing.langfuse_client import TracingClient


def test_a_none_client_makes_every_call_a_true_no_op():
    tracing = TracingClient(None)

    with tracing.trace("estimate_run", estimate_id="e-1") as trace:
        trace.update(output={"status": "ready"})
        with trace.span("tool_call", tool="lookup_customer") as child:
            child.update(output={"matches": []})

    # no exception means every call on a None-backed client was a safe no-op


class FakeObservation:
    def __init__(self, name, metadata):
        self.name = name
        self.metadata = metadata
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)


class FakeSpanContext:
    def __init__(self, client, name, metadata):
        self.client = client
        self.name = name
        self.metadata = metadata

    def __enter__(self):
        obs = FakeObservation(self.name, self.metadata)
        self.client.opened.append(obs)
        return obs

    def __exit__(self, *exc):
        return False


class FakeLangfuseClient:
    """Duck-types the one real Langfuse method TracingClient calls."""

    def __init__(self):
        self.opened = []

    def start_as_current_observation(self, *, name, as_type, metadata=None):
        return FakeSpanContext(self, name, metadata or {})


def test_a_real_client_opens_a_root_trace_and_a_nested_span():
    fake = FakeLangfuseClient()
    tracing = TracingClient(fake)

    with tracing.trace("estimate_run", estimate_id="e-1") as trace:
        with trace.span("tool_call", tool="lookup_customer") as child:
            child.update(output={"matches": []})

    assert [obs.name for obs in fake.opened] == ["estimate_run", "tool_call"]
    assert fake.opened[1].updates == [{"output": {"matches": []}}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/core/test_langfuse_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.tracing'`.

- [ ] **Step 3: Add the dependency**

```toml
# backend/pyproject.toml -- in [project] dependencies, alongside the existing alphabetized list
    "langfuse>=3.0.0",
```

Run: `cd backend && uv sync` (or the project's existing dependency-install command)

- [ ] **Step 4: Implement**

```python
# backend/core/tracing/langfuse_client.py
from functools import lru_cache

from core.config.settings import Settings


class TraceHandle:
    def __init__(self, client, span) -> None:
        self._client = client
        self._span = span

    def span(self, name: str, **metadata) -> "_SpanContext":
        return _SpanContext(self._client, name, metadata)

    def update(self, **metadata) -> None:
        if self._span is not None:
            self._span.update(**metadata)


class _SpanContext:
    def __init__(self, client, name: str, metadata: dict) -> None:
        self._client = client
        self._name = name
        self._metadata = metadata
        self._cm = None

    def __enter__(self) -> TraceHandle:
        if self._client is None:
            return TraceHandle(None, None)
        self._cm = self._client.start_as_current_observation(name=self._name, as_type="span", metadata=self._metadata)
        span = self._cm.__enter__()
        return TraceHandle(self._client, span)

    def __exit__(self, *exc) -> bool:
        if self._cm is not None:
            return bool(self._cm.__exit__(*exc))
        return False


class TracingClient:
    def __init__(self, client) -> None:
        self._client = client

    def trace(self, name: str, **metadata) -> _SpanContext:
        return _SpanContext(self._client, name, metadata)


@lru_cache
def get_tracing_client() -> TracingClient:
    settings = Settings()
    if not settings.langfuse_public_key:
        return TracingClient(None)
    from langfuse import Langfuse

    return TracingClient(Langfuse(
        public_key=settings.langfuse_public_key, secret_key=settings.langfuse_secret_key, host=settings.langfuse_host,
    ))
```

```python
# backend/core/config/settings.py -- add three fields after graph_namespace
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/core/test_langfuse_client.py -v`
Expected: PASS

- [ ] **Step 6: Add commented Langfuse lines to `.env.example`**

```
# backend/.env.example -- append
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=http://localhost:3000
```

- [ ] **Step 7: Commit**

```bash
git add backend/core/tracing/__init__.py backend/core/tracing/langfuse_client.py backend/core/config/settings.py backend/pyproject.toml backend/.env.example backend/tests/core/test_langfuse_client.py backend/uv.lock
git commit -m "feat: add no-op-safe langfuse tracing client"
```

---

## Task 5: eval case construction and correction validation

**Files:**
- Modify: `backend/app/judge/schemas.py`, `backend/app/judge/repository.py`
- Test: `backend/tests/app/judge/test_schemas.py` (new), `backend/tests/app/judge/test_repository.py` (extend)

**Interfaces:**
- Consumes: `ReviewItemRow` (Task 1); `app.reference_data.repository.get_sku` (existing).
- Produces: `RESOLVABLE_DIMENSIONS: frozenset[str]`; `InvalidCorrection(Exception)`; `EvalCase(BaseModel)`; `build_eval_case(row: ReviewItemRow, outcome: str, case_id: str) -> EvalCase`; `validate_correction(session, dimension: str, correction: dict) -> None`; `get_review_item(session, review_item_id) -> ReviewItemRow | None`; `save_eval_case(session, case: EvalCase) -> EvalCaseRow`; `next_eval_case_id(session) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/app/judge/test_schemas.py
import uuid

import pytest

from app.judge.models import ReviewItemRow
from app.judge.schemas import InvalidCorrection, build_eval_case, validate_correction
from tests.app.estimate.seed import seed_world

PRICE_EVIDENCE = {"lines": [{"line_index": 0, "sku_id": "SKU-E-GAP", "price_source": "predicted", "list_price": None}]}
GRAPH_EVIDENCE = {"lines": [{"line_index": 0, "sku_id": "SKU-E-B1", "required_part_ids": [], "missing_required_part_ids": []}]}
CONTRACT_EVIDENCE = {"lines": [{"line_index": 0, "sku_id": "SKU-E-A1", "contract_id": "CTR-E1", "covered": False}]}


def _row(dimension, evidence):
    return ReviewItemRow(
        id=uuid.uuid4(), judge_verdict_id=uuid.uuid4(), estimate_id=uuid.uuid4(), dimension=dimension,
        fact="x", evidence=evidence, line_index=None,
    )


def test_validate_correction_accepts_a_price_correction_naming_a_flagged_sku(db_session):
    seed_world(db_session)
    validate_correction(db_session, "price_provenance", {"sku_id": "SKU-E-GAP", "corrected_unit_price": 42.5})


def test_validate_correction_rejects_a_sku_the_review_item_never_named(db_session):
    seed_world(db_session)
    with pytest.raises(InvalidCorrection):
        validate_correction(db_session, "price_provenance", {"sku_id": "SKU-E-A1", "corrected_unit_price": 42.5},
                             evidence=PRICE_EVIDENCE)


def test_validate_correction_rejects_an_unknown_required_sku(db_session):
    seed_world(db_session)
    with pytest.raises(InvalidCorrection):
        validate_correction(db_session, "graph_completion",
                             {"sku_id": "SKU-E-B1", "required_sku_id": "SKU-NOPE"}, evidence=GRAPH_EVIDENCE)


def test_validate_correction_rejects_a_mismatched_contract_id(db_session):
    seed_world(db_session)
    with pytest.raises(InvalidCorrection):
        validate_correction(db_session, "contract_discount", {"contract_id": "CTR-NOPE", "category": "Cat-E-B"},
                             evidence=CONTRACT_EVIDENCE)


def test_validate_correction_rejects_an_unresolvable_dimension(db_session):
    with pytest.raises(InvalidCorrection):
        validate_correction(db_session, "guardrail", {}, evidence={"violations": []})


def test_build_eval_case_uses_trust_label_for_an_approved_outcome():
    row = _row("price_provenance", PRICE_EVIDENCE)
    case = build_eval_case(row, "approved", "rc-0001")
    assert case.label == "trust"
    assert case.estimate_status == "ready"
    assert case.evidence == PRICE_EVIDENCE["lines"]
    assert case.source_review_item_id == row.id


def test_build_eval_case_uses_escalate_label_for_a_corrected_outcome():
    row = _row("graph_completion", GRAPH_EVIDENCE)
    case = build_eval_case(row, "corrected", "rc-0002")
    assert case.label == "escalate"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/app/judge/test_schemas.py -v`
Expected: FAIL — `ImportError: cannot import name 'validate_correction'`.

- [ ] **Step 3: Implement**

```python
# backend/app/judge/schemas.py -- add imports and append to the existing file
import uuid
from typing import Literal

from pydantic import BaseModel

from app.judge.models import ReviewItemRow
from app.reference_data.repository import get_sku

DimensionName = Literal["contract_discount", "graph_completion", "price_provenance"]
RESOLVABLE_DIMENSIONS = frozenset({"price_provenance", "graph_completion", "contract_discount"})


class DimensionScore(BaseModel):
    # ... unchanged ...


class JudgeVerdict(BaseModel):
    # ... unchanged ...


class ReviewItem(BaseModel):
    # ... unchanged ...


class InvalidCorrection(Exception):
    pass


class EvalCase(BaseModel):
    case_id: str
    label: Literal["trust", "escalate"]
    estimate_status: str
    evidence: list[dict]
    source_review_item_id: uuid.UUID


def build_eval_case(row: ReviewItemRow, outcome: str, case_id: str) -> EvalCase:
    return EvalCase(
        case_id=case_id, label="trust" if outcome == "approved" else "escalate",
        estimate_status="ready", evidence=row.evidence["lines"], source_review_item_id=row.id,
    )


def validate_correction(session, dimension: str, correction: dict, evidence: dict | None = None) -> None:
    if dimension not in RESOLVABLE_DIMENSIONS:
        raise InvalidCorrection(f"dimension {dimension!r} has no consolidation handler")
    lines = (evidence or {}).get("lines", [])
    line_sku_ids = {line["sku_id"] for line in lines}

    if dimension == "price_provenance":
        if correction.get("sku_id") not in line_sku_ids:
            raise InvalidCorrection(f"sku_id {correction.get('sku_id')!r} was not flagged by this review item")
    elif dimension == "graph_completion":
        if correction.get("sku_id") not in line_sku_ids:
            raise InvalidCorrection(f"sku_id {correction.get('sku_id')!r} was not flagged by this review item")
        if get_sku(session, correction.get("required_sku_id")) is None:
            raise InvalidCorrection(f"required_sku_id {correction.get('required_sku_id')!r} is not a known SKU")
    elif dimension == "contract_discount":
        contract_ids = {line.get("contract_id") for line in lines}
        if correction.get("contract_id") not in contract_ids:
            raise InvalidCorrection(f"contract_id {correction.get('contract_id')!r} was not flagged by this review item")
```

Note: `validate_correction`'s `evidence` parameter is keyword-only-by-convention here for the direct unit tests above (tests pass it explicitly); Task 7's `resolve_review_item` always calls it as `validate_correction(session, row.dimension, correction, row.evidence)`, reading the review item's own stored evidence, never caller-supplied evidence. The first test (`test_validate_correction_accepts_a_price_correction_naming_a_flagged_sku`) omits `evidence` to prove the "unresolvable dimension" and "empty evidence" branches degrade safely (`lines = []`, so `line_sku_ids` is empty) — wait, this test asserts no exception is raised for `SKU-E-GAP` when `evidence` defaults to `None`, which would make `line_sku_ids` empty and correctly raise. Fix: this test must pass `evidence=PRICE_EVIDENCE` too. Correct it:

```python
def test_validate_correction_accepts_a_price_correction_naming_a_flagged_sku(db_session):
    seed_world(db_session)
    validate_correction(db_session, "price_provenance", {"sku_id": "SKU-E-GAP", "corrected_unit_price": 42.5},
                         evidence=PRICE_EVIDENCE)
```

```python
# backend/app/judge/repository.py -- add imports and functions
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.judge.models import EvalCaseRow, JudgeVerdictRow, ReviewItemRow
from app.judge.schemas import EvalCase

# ... existing save_judge_verdict, save_review_item, get_judge_verdict, list_open_review_items unchanged ...


def get_review_item(session: Session, review_item_id: uuid.UUID) -> ReviewItemRow | None:
    return session.get(ReviewItemRow, review_item_id)


def next_eval_case_id(session: Session) -> str:
    count = session.scalar(select(func.count()).select_from(EvalCaseRow))
    return f"rc-{count + 1:04d}"


def save_eval_case(session: Session, case: EvalCase) -> EvalCaseRow:
    row = EvalCaseRow(
        id=uuid.uuid4(), source_review_item_id=case.source_review_item_id, case_id=case.case_id, label=case.label,
        estimate_status=case.estimate_status, evidence=case.evidence,
    )
    session.add(row)
    session.flush()
    return row
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/app/judge/test_schemas.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/judge/schemas.py backend/app/judge/repository.py backend/tests/app/judge/test_schemas.py
git commit -m "feat: add eval case construction and per-dimension correction validation"
```

---

## Task 6: consolidation module and worker entrypoint

**Files:**
- Create: `backend/app/consolidation/__init__.py`, `backend/app/consolidation/service.py`, `backend/app/consolidation/tasks.py`, `backend/scripts/run_worker.py`
- Test: `backend/tests/app/consolidation/__init__.py`, `backend/tests/app/consolidation/test_service.py`, `backend/tests/app/consolidation/test_tasks.py`
- Modify: `backend/pyproject.toml` (add `procrastinate` dependency)

**Interfaces:**
- Consumes: `app.judge.repository.get_review_item` (Task 5); `app.reference_data.repository.set_sku_list_price`, `add_contract_coverage`, `upsert_requirement` (Task 2, existing); `app.graph.service.sync_sku`, `sync_requirement`, `sync_contract_coverage`, `sync_best_effort` (Task 3, existing).
- Produces: `consolidate_review_item(session, client, ns, review_item_id: uuid.UUID) -> None`; `app.consolidation.tasks.app` (the `procrastinate.App`); `app.consolidation.tasks.consolidate_review_item_task` (the deferred task, callable with `.defer(review_item_id: str)`).

- [ ] **Step 1: Write the failing tests (pure service logic first)**

```python
# backend/tests/app/consolidation/test_service.py
import uuid

import pytest

from app.consolidation.service import consolidate_review_item
from app.judge.models import EvalCaseRow, JudgeVerdictRow, ReviewItemRow
from app.reference_data.models import Contract, Sku, SkuRequirement
from app.reference_data.repository import reference_fingerprint
from tests.app.estimate.seed import seed_world
from tests.graph_support import graph_edge_count, graph_node


def _corrected_review_item(session, dimension, correction, evidence):
    verdict = JudgeVerdictRow(
        id=uuid.uuid4(), estimate_id=uuid.uuid4(), model="m", dimensions=[], overall_confidence=0.1,
        flagged_dimension=dimension, trusted=False,
    )
    session.add(verdict)
    session.flush()
    row = ReviewItemRow(
        id=uuid.uuid4(), judge_verdict_id=verdict.id, estimate_id=verdict.estimate_id, dimension=dimension,
        fact="x", evidence=evidence, line_index=None, status="corrected", outcome="corrected", correction=correction,
    )
    session.add(row)
    session.flush()
    return row


def _world(db_session, make_reader):
    seed_world(db_session)
    return make_reader()


def test_price_provenance_handler_sets_list_price_and_syncs_the_graph(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    row = _corrected_review_item(
        db_session, "price_provenance", {"sku_id": "SKU-E-GAP", "corrected_unit_price": 42.5},
        {"lines": [{"line_index": 0, "sku_id": "SKU-E-GAP"}]},
    )

    consolidate_review_item(db_session, graph_client, graph_ns, row.id)

    assert db_session.get(Sku, "SKU-E-GAP").list_price == 42.5
    assert graph_node(graph_client, graph_ns, "SKU-E-GAP")["props"]["list_price"] == 42.5
    assert db_session.get(ReviewItemRow, row.id).status == "consolidated"


def test_graph_completion_handler_adds_requirement_and_keeps_graph_current(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    row = _corrected_review_item(
        db_session, "graph_completion", {"sku_id": "SKU-E-GAP", "required_sku_id": "SKU-E-A1"},
        {"lines": [{"line_index": 0, "sku_id": "SKU-E-GAP"}]},
    )

    consolidate_review_item(db_session, graph_client, graph_ns, row.id)

    assert db_session.get(SkuRequirement, ("SKU-E-GAP", "SKU-E-A1")) is not None
    assert graph_edge_count(graph_client, graph_ns, "SKU-E-GAP", "REQUIRES", "SKU-E-A1") == 1
    from app.graph.reader import GraphReader
    assert GraphReader(graph_client, graph_ns).stored_fingerprint() == reference_fingerprint(db_session)


def test_graph_completion_handler_is_idempotent_on_a_second_run(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    row = _corrected_review_item(
        db_session, "graph_completion", {"sku_id": "SKU-E-GAP", "required_sku_id": "SKU-E-A1"},
        {"lines": [{"line_index": 0, "sku_id": "SKU-E-GAP"}]},
    )
    consolidate_review_item(db_session, graph_client, graph_ns, row.id)
    db_session.get(ReviewItemRow, row.id).status = "corrected"
    db_session.flush()

    consolidate_review_item(db_session, graph_client, graph_ns, row.id)

    assert graph_edge_count(graph_client, graph_ns, "SKU-E-GAP", "REQUIRES", "SKU-E-A1") == 1


def test_contract_discount_handler_adds_coverage_and_keeps_graph_current(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    row = _corrected_review_item(
        db_session, "contract_discount", {"contract_id": "CTR-E1", "category": "Cat-E-B"},
        {"lines": [{"line_index": 0, "sku_id": "SKU-E-B1", "contract_id": "CTR-E1"}]},
    )

    consolidate_review_item(db_session, graph_client, graph_ns, row.id)

    assert db_session.get(Contract, "CTR-E1").covered_categories == ["Cat-E-A", "Cat-E-B"]
    assert graph_edge_count(graph_client, graph_ns, "CTR-E1", "COVERS", "Cat-E-B") == 1
    from app.graph.reader import GraphReader
    assert GraphReader(graph_client, graph_ns).stored_fingerprint() == reference_fingerprint(db_session)


def test_consolidate_review_item_rejects_a_row_not_in_corrected_status(db_session, graph_client, graph_ns):
    seed_world(db_session)
    verdict = JudgeVerdictRow(
        id=uuid.uuid4(), estimate_id=uuid.uuid4(), model="m", dimensions=[], overall_confidence=0.9,
        flagged_dimension="price_provenance", trusted=True,
    )
    db_session.add(verdict)
    db_session.flush()
    row = ReviewItemRow(
        id=uuid.uuid4(), judge_verdict_id=verdict.id, estimate_id=verdict.estimate_id, dimension="price_provenance",
        fact="x", evidence={"lines": []}, line_index=None, status="open",
    )
    db_session.add(row)
    db_session.flush()

    with pytest.raises(ValueError):
        consolidate_review_item(db_session, graph_client, graph_ns, row.id)
```

```python
# backend/tests/app/consolidation/test_tasks.py
from procrastinate import testing

from app.consolidation.tasks import app, consolidate_review_item_task


def test_deferring_enqueues_a_job_with_the_review_item_id():
    in_memory = testing.InMemoryConnector()
    with app.replace_connector(in_memory) as scoped_app:
        consolidate_review_item_task.defer(review_item_id="11111111-1111-1111-1111-111111111111")

        jobs = list(scoped_app.connector.jobs.values())
        assert len(jobs) == 1
        assert jobs[0]["task_name"] == "consolidate_review_item"
        # The job row's argument field is named task_kwargs per procrastinate's own reference docs, but this
        # asserts on its content rather than guessing the exact dict key, so it stays correct either way.
        assert "11111111-1111-1111-1111-111111111111" in str(jobs[0])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/app/consolidation/ -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.consolidation'`.

- [ ] **Step 3: Add the dependency**

```toml
# backend/pyproject.toml -- in [project] dependencies
    "procrastinate>=3.0.0",
```

Run: `cd backend && uv sync`

- [ ] **Step 4: Implement the pure consolidation logic**

```python
# backend/app/consolidation/service.py
import uuid

from sqlalchemy.orm import Session

from app.graph.service import sync_best_effort, sync_contract_coverage, sync_requirement, sync_sku
from app.judge.repository import get_review_item
from app.reference_data.repository import add_contract_coverage, set_sku_list_price, upsert_requirement
from core.graph.client import GraphClient


def _consolidate_price_provenance(session: Session, client: GraphClient, ns: str, correction: dict) -> None:
    sku_id = correction["sku_id"]
    set_sku_list_price(session, sku_id, correction["corrected_unit_price"])
    sync_best_effort("sku price correction", sync_sku, session, client, ns, sku_id)


def _consolidate_graph_completion(session: Session, client: GraphClient, ns: str, correction: dict) -> None:
    sku_id, required_sku_id = correction["sku_id"], correction["required_sku_id"]
    upsert_requirement(session, sku_id=sku_id, required_sku_id=required_sku_id)
    sync_best_effort("sku requirement correction", sync_requirement, session, client, ns, sku_id, required_sku_id)


def _consolidate_contract_discount(session: Session, client: GraphClient, ns: str, correction: dict) -> None:
    contract_id, category = correction["contract_id"], correction["category"]
    add_contract_coverage(session, contract_id, category)
    sync_best_effort("contract coverage correction", sync_contract_coverage, session, client, ns, contract_id, category)


_HANDLERS = {
    "price_provenance": _consolidate_price_provenance,
    "graph_completion": _consolidate_graph_completion,
    "contract_discount": _consolidate_contract_discount,
}


def consolidate_review_item(session: Session, client: GraphClient, ns: str, review_item_id: uuid.UUID) -> None:
    row = get_review_item(session, review_item_id)
    if row is None:
        raise ValueError(f"review item {review_item_id} not found")
    if row.status != "corrected":
        raise ValueError(f"review item {review_item_id} is {row.status!r}, expected 'corrected'")

    handler = _HANDLERS.get(row.dimension)
    if handler is None:
        raise ValueError(f"no consolidation handler for dimension {row.dimension!r}")
    handler(session, client, ns, row.correction)

    row.status = "consolidated"
    session.flush()
```

- [ ] **Step 5: Implement the procrastinate task wrapper**

```python
# backend/app/consolidation/tasks.py
import uuid

import procrastinate

from app.consolidation.service import consolidate_review_item
from core.config.settings import Settings
from core.db.session import make_engine, make_session_factory
from core.graph.client import get_graph_client, get_graph_namespace


def _conninfo(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://")


app = procrastinate.App(connector=procrastinate.SyncPsycopgConnector(conninfo=_conninfo(Settings().database_url)))


@app.task(name="consolidate_review_item")
def consolidate_review_item_task(review_item_id: str) -> None:
    session = make_session_factory(make_engine(Settings().database_url))()
    try:
        consolidate_review_item(session, get_graph_client(), get_graph_namespace(), uuid.UUID(review_item_id))
        session.commit()
    finally:
        session.close()
```

```python
# backend/app/consolidation/__init__.py
```
(empty file, matches every other `app/*/` package)

- [ ] **Step 6: Write the worker entrypoint**

```python
# backend/scripts/run_worker.py
"""Runs the procrastinate worker that executes deferred consolidation jobs. A long-running process, started
manually (`python run_worker.py`), never by the test suite or by any request-serving process."""
from app.consolidation.tasks import app


def main() -> None:
    with app.open():
        app.run_worker()


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && pytest tests/app/consolidation/ -v`
Expected: PASS (all 6 tests)

- [ ] **Step 8: Commit**

```bash
git add backend/app/consolidation/ backend/scripts/run_worker.py backend/tests/app/consolidation/ backend/pyproject.toml backend/uv.lock
git commit -m "feat: add consolidation task with per-dimension correction handlers"
```

---

## Task 7: `resolve_review_item` service function

**Files:**
- Modify: `backend/app/judge/service.py`
- Test: `backend/tests/app/judge/test_service.py`

**Interfaces:**
- Consumes: `app.judge.repository.get_review_item`, `next_eval_case_id`, `save_eval_case` (Task 5); `app.judge.schemas.RESOLVABLE_DIMENSIONS`, `InvalidCorrection`, `build_eval_case`, `validate_correction` (Task 5); `app.consolidation.tasks.consolidate_review_item_task` (Task 6).
- Produces: `ReviewItemNotFound(Exception)`; `ReviewItemAlreadyResolved(Exception)`; `ReviewItemNotResolvable(Exception)`; `resolve_review_item(session, review_item_id: uuid.UUID, outcome: str, correction: dict | None) -> ReviewItemResolution` where `ReviewItemResolution` is a `@dataclass` with `row: ReviewItemRow`, `eval_case: EvalCase`, `consolidation_enqueued: bool`.

Design note (see spec decision on fast-path items): a `dimension == "guardrail"` review item (created when a `needs_review` draft short-circuits the judge, per Phase 5) is never resolvable here — its `evidence` shape (`{"violations": [...]}`) does not carry the per-line shape the eval set and consolidation handlers require, and a human "approving" a deterministic guardrail rejection is a different, unsupported class of action. `resolve_review_item` raises `ReviewItemNotResolvable` for it, for both `approved` and `corrected` outcomes.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/app/judge/test_service.py -- add at end of file
import uuid

import pytest
from procrastinate import testing

from app.consolidation.tasks import app as consolidation_app
from app.judge.models import ReviewItemRow
from app.judge.repository import save_judge_verdict, save_review_item
from app.judge.service import (
    InvalidCorrection, ReviewItemAlreadyResolved, ReviewItemNotFound, ReviewItemNotResolvable, resolve_review_item,
)
from tests.app.estimate.seed import seed_world

PRICE_EVIDENCE = {"lines": [{"line_index": 0, "sku_id": "SKU-E-GAP", "price_source": "predicted"}]}


def _open_review_item(session, dimension="price_provenance", evidence=None, fact="thin evidence"):
    verdict = save_judge_verdict(
        session, estimate_id=uuid.uuid4(), model="m", dimensions=[], overall_confidence=0.1,
        flagged_dimension=dimension, trusted=False,
    )
    return save_review_item(
        session, judge_verdict_id=verdict.id, estimate_id=verdict.estimate_id, dimension=dimension, fact=fact,
        evidence=evidence or PRICE_EVIDENCE, line_index=None,
    )


def test_resolve_review_item_returns_404_equivalent_for_an_unknown_id(db_session):
    with pytest.raises(ReviewItemNotFound):
        resolve_review_item(db_session, uuid.uuid4(), "approved", None)


def test_approving_records_the_outcome_and_a_trust_eval_case_with_no_task_enqueued(db_session):
    seed_world(db_session)
    row = _open_review_item(db_session)
    in_memory = testing.InMemoryConnector()
    with consolidation_app.replace_connector(in_memory):
        result = resolve_review_item(db_session, row.id, "approved", None)

    assert result.row.status == "approved"
    assert result.row.outcome == "approved"
    assert result.eval_case.label == "trust"
    assert result.consolidation_enqueued is False
    assert in_memory.jobs == {}


def test_correcting_records_the_outcome_and_an_escalate_eval_case_and_enqueues_consolidation(db_session):
    seed_world(db_session)
    row = _open_review_item(db_session)
    correction = {"sku_id": "SKU-E-GAP", "corrected_unit_price": 42.5}
    in_memory = testing.InMemoryConnector()
    with consolidation_app.replace_connector(in_memory):
        result = resolve_review_item(db_session, row.id, "corrected", correction)

    assert result.row.status == "corrected"
    assert result.row.correction == correction
    assert result.eval_case.label == "escalate"
    assert result.consolidation_enqueued is True
    assert len(in_memory.jobs) == 1
    assert str(row.id) in str(list(in_memory.jobs.values())[0])


def test_resolving_an_already_resolved_item_is_rejected(db_session):
    seed_world(db_session)
    row = _open_review_item(db_session)
    in_memory = testing.InMemoryConnector()
    with consolidation_app.replace_connector(in_memory):
        resolve_review_item(db_session, row.id, "approved", None)
        with pytest.raises(ReviewItemAlreadyResolved):
            resolve_review_item(db_session, row.id, "approved", None)


def test_correcting_with_a_sku_the_review_item_never_named_is_rejected(db_session):
    seed_world(db_session)
    row = _open_review_item(db_session)
    with pytest.raises(InvalidCorrection):
        resolve_review_item(db_session, row.id, "corrected", {"sku_id": "SKU-E-A1", "corrected_unit_price": 1.0})


def test_a_guardrail_fast_path_review_item_is_not_resolvable(db_session):
    seed_world(db_session)
    row = _open_review_item(db_session, dimension="guardrail", evidence={"violations": ["blocked"]}, fact="blocked")
    with pytest.raises(ReviewItemNotResolvable):
        resolve_review_item(db_session, row.id, "approved", None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/app/judge/test_service.py -v -k resolve_review_item or approving or correcting or already_resolved or fast_path`
Expected: FAIL — `ImportError: cannot import name 'resolve_review_item'`.

- [ ] **Step 3: Implement**

```python
# backend/app/judge/service.py -- add imports and append to the existing file
from dataclasses import dataclass
from datetime import datetime, timezone

from app.judge.models import ReviewItemRow
from app.judge.repository import get_review_item, next_eval_case_id, save_eval_case
from app.judge.schemas import RESOLVABLE_DIMENSIONS, EvalCase, InvalidCorrection, build_eval_case, validate_correction


class ReviewItemNotFound(Exception):
    pass


class ReviewItemAlreadyResolved(Exception):
    pass


class ReviewItemNotResolvable(Exception):
    pass


@dataclass
class ReviewItemResolution:
    row: ReviewItemRow
    eval_case: EvalCase
    consolidation_enqueued: bool


def resolve_review_item(session, review_item_id, outcome: str, correction: dict | None) -> ReviewItemResolution:
    row = get_review_item(session, review_item_id)
    if row is None:
        raise ReviewItemNotFound(f"review item {review_item_id} not found")
    if row.status != "open":
        raise ReviewItemAlreadyResolved(f"review item {review_item_id} is already {row.status!r}")
    if row.dimension not in RESOLVABLE_DIMENSIONS:
        raise ReviewItemNotResolvable(f"dimension {row.dimension!r} is not resolvable through this endpoint")
    if outcome == "corrected":
        validate_correction(session, row.dimension, correction, row.evidence)

    row.status = outcome
    row.outcome = outcome
    row.correction = correction if outcome == "corrected" else None
    row.resolved_at = datetime.now(timezone.utc)
    session.flush()

    case = build_eval_case(row, outcome, next_eval_case_id(session))
    save_eval_case(session, case)

    consolidation_enqueued = False
    if outcome == "corrected":
        from app.consolidation.tasks import consolidate_review_item_task

        consolidate_review_item_task.defer(review_item_id=str(row.id))
        consolidation_enqueued = True

    return ReviewItemResolution(row=row, eval_case=case, consolidation_enqueued=consolidation_enqueued)
```

The `import` of `app.consolidation.tasks` is deferred inside the function (not at module top) specifically so importing `app.judge.service` (which many existing tests already do) never has to build a `procrastinate.App`/`SyncPsycopgConnector` unless a test actually exercises the `corrected` path.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/app/judge/test_service.py -v`
Expected: PASS (existing judge service tests plus the new ones)

- [ ] **Step 5: Commit**

```bash
git add backend/app/judge/service.py backend/tests/app/judge/test_service.py
git commit -m "feat: add resolve_review_item service function"
```

---

## Task 8: `POST /v1/review/{review_item_id}/resolve` route

**Files:**
- Create: `backend/api/v1/review/request.py`
- Modify: `backend/api/v1/review/response.py`, `backend/api/v1/review/route.py`
- Test: `backend/tests/api/v1/test_review_resolve_route.py`

**Interfaces:**
- Consumes: `app.judge.service.resolve_review_item`, `ReviewItemNotFound`, `ReviewItemAlreadyResolved`, `ReviewItemNotResolvable` (Task 7); `app.judge.schemas.InvalidCorrection` (Task 5).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/api/v1/test_review_resolve_route.py
import uuid

from fastapi.testclient import TestClient
from procrastinate import testing

from app.consolidation.tasks import app as consolidation_app
from app.judge.repository import save_judge_verdict, save_review_item
from core.db.session import get_session
from main import app
from tests.app.estimate.seed import seed_world

PRICE_EVIDENCE = {"lines": [{"line_index": 0, "sku_id": "SKU-E-GAP", "price_source": "predicted"}]}


def _open_review_item(session):
    verdict = save_judge_verdict(
        session, estimate_id=uuid.uuid4(), model="m", dimensions=[], overall_confidence=0.1,
        flagged_dimension="price_provenance", trusted=False,
    )
    return save_review_item(
        session, judge_verdict_id=verdict.id, estimate_id=verdict.estimate_id, dimension="price_provenance",
        fact="thin evidence", evidence=PRICE_EVIDENCE, line_index=None,
    )


def _post(session, review_item_id, body):
    app.dependency_overrides[get_session] = lambda: session
    in_memory = testing.InMemoryConnector()
    try:
        with consolidation_app.replace_connector(in_memory):
            return TestClient(app).post(f"/v1/review/{review_item_id}/resolve", json=body)
    finally:
        app.dependency_overrides.clear()


def test_resolve_returns_404_for_an_unknown_review_item(db_session):
    response = _post(db_session, uuid.uuid4(), {"outcome": "approved"})
    assert response.status_code == 404


def test_resolve_approve_returns_200_with_no_consolidation(db_session):
    seed_world(db_session)
    row = _open_review_item(db_session)

    response = _post(db_session, row.id, {"outcome": "approved"})

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "approved"
    assert body["consolidation_enqueued"] is False


def test_resolve_corrected_returns_200_and_enqueues_consolidation(db_session):
    seed_world(db_session)
    row = _open_review_item(db_session)

    response = _post(db_session, row.id, {
        "outcome": "corrected", "correction": {"sku_id": "SKU-E-GAP", "corrected_unit_price": 42.5},
    })

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "corrected"
    assert body["consolidation_enqueued"] is True


def test_resolve_rejects_an_invalid_correction_with_422(db_session):
    seed_world(db_session)
    row = _open_review_item(db_session)

    response = _post(db_session, row.id, {
        "outcome": "corrected", "correction": {"sku_id": "SKU-E-A1", "corrected_unit_price": 1.0},
    })

    assert response.status_code == 422


def test_resolve_rejects_an_already_resolved_item_with_409(db_session):
    seed_world(db_session)
    row = _open_review_item(db_session)
    _post(db_session, row.id, {"outcome": "approved"})

    response = _post(db_session, row.id, {"outcome": "approved"})

    assert response.status_code == 409
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/api/v1/test_review_resolve_route.py -v`
Expected: FAIL — 404 for every request (route does not exist yet).

- [ ] **Step 3: Implement**

```python
# backend/api/v1/review/request.py
from typing import Literal

from pydantic import BaseModel


class ResolveReviewItemRequest(BaseModel):
    outcome: Literal["approved", "corrected"]
    correction: dict | None = None
```

```python
# backend/api/v1/review/response.py -- add after ReviewItemListResponse
class ResolveReviewItemResponse(BaseModel):
    id: uuid.UUID
    status: str
    outcome: str
    correction: dict | None
    consolidation_enqueued: bool
```

```python
# backend/api/v1/review/route.py -- full file
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.v1.review.request import ResolveReviewItemRequest
from api.v1.review.response import ResolveReviewItemResponse, ReviewItemListResponse
from app.judge.repository import list_open_review_items
from app.judge.schemas import InvalidCorrection
from app.judge.service import ReviewItemAlreadyResolved, ReviewItemNotFound, ReviewItemNotResolvable, resolve_review_item
from core.db.session import get_session

router = APIRouter(prefix="/v1/review", tags=["review"])


@router.get("", response_model=list[ReviewItemListResponse])
def list_review_items(session: Session = Depends(get_session)) -> list[ReviewItemListResponse]:
    return [
        ReviewItemListResponse(
            id=item.id, estimate_id=item.estimate_id, dimension=item.dimension, fact=item.fact,
            evidence=item.evidence, line_index=item.line_index, status=item.status, created_at=item.created_at,
        )
        for item in list_open_review_items(session)
    ]


@router.post("/{review_item_id}/resolve", response_model=ResolveReviewItemResponse)
def resolve(
    review_item_id: uuid.UUID, body: ResolveReviewItemRequest, session: Session = Depends(get_session),
) -> ResolveReviewItemResponse:
    try:
        result = resolve_review_item(session, review_item_id, body.outcome, body.correction)
    except ReviewItemNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ReviewItemAlreadyResolved as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ReviewItemNotResolvable as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidCorrection as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    session.commit()
    return ResolveReviewItemResponse(
        id=result.row.id, status=result.row.status, outcome=result.row.outcome, correction=result.row.correction,
        consolidation_enqueued=result.consolidation_enqueued,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/api/v1/test_review_resolve_route.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/api/v1/review/request.py backend/api/v1/review/response.py backend/api/v1/review/route.py backend/tests/api/v1/test_review_resolve_route.py
git commit -m "feat: add review item resolve endpoint"
```

---

## Task 9: `scripts/calibrate_judge.py` false-auto-send release gate

**Files:**
- Modify: `backend/app/judge/calibration.py`, `backend/app/judge/constant.py`, `backend/scripts/calibrate_judge.py`
- Test: `backend/tests/app/judge/test_calibration.py` (extend), `backend/tests/data_gen/test_judge_golden_set.py` (leave as-is unless it breaks), plus new `backend/tests/scripts/__init__.py` and `backend/tests/scripts/test_calibrate_judge.py`

**Interfaces:**
- Produces: `CalibrationResult.pairs: list[tuple[bool, bool]]` (new field); `false_auto_send_rate(pairs: list[tuple[bool, bool]]) -> float`; `FALSE_AUTO_SEND_CEILING = 0.05` in `app/judge/constant.py`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/app/judge/test_calibration.py -- add at end of file
from app.judge.calibration import false_auto_send_rate


def test_false_auto_send_rate_counts_only_wrongly_trusted_cases():
    pairs = [(True, True), (True, False), (False, False), (False, True)]
    assert false_auto_send_rate(pairs) == 0.25


def test_false_auto_send_rate_is_zero_when_nothing_is_wrongly_trusted():
    assert false_auto_send_rate([(True, True), (False, False)]) == 0.0


def test_calibrate_result_carries_the_winning_pairs():
    from app.judge.calibration import calibrate

    result = calibrate(scores=[0.9, 0.9, 0.2], labels=[True, True, False], acceptable_kappa=0.6)
    assert result is not None
    assert len(result.pairs) == 3
```

```python
# backend/tests/scripts/test_calibrate_judge.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from core.llm.anthropic_judge_client import RawDimensionScore, RawJudgeScore
from scripts.calibrate_judge import CeilingBreached, NoAcceptableThreshold, run_calibration


class QueuedJudgeClient:
    """Returns one scripted overall score per call, in call order (every dimension gets the same score, so
    rollup's min() is that score exactly). Lets a test control exactly which case gets which confidence."""

    def __init__(self, scores: list[float]) -> None:
        self._scores = iter(scores)

    def score(self, evidence, system_prompt):
        s = next(self._scores)
        return RawJudgeScore(dimensions=[
            RawDimensionScore(name="price_provenance", score=s, rationale="r"),
            RawDimensionScore(name="contract_discount", score=s, rationale="r"),
            RawDimensionScore(name="graph_completion", score=s, rationale="r"),
        ])


def _case(case_id: str, label: str) -> dict:
    return {
        "case_id": case_id, "label": label, "estimate_status": "ready",
        "evidence": [{
            "line_index": 0, "sku_id": "SKU-X", "unit_price": 10.0,
            "price": {"price_source": "list", "list_price": 10.0, "predicted_price": None, "peer_count": None,
                      "low": None, "high": None},
            "contract": {"discount_pct": 0.0, "contract_id": None, "covered": None, "active_on_as_of": None,
                         "days_to_expiry": None},
            "graph": {"discontinued": False, "live_sku_id": "SKU-X", "required_part_ids": [],
                      "missing_required_part_ids": []},
        }],
    }


def _cases(breach: bool) -> list[dict]:
    """5 cases scored 0.9 (4 labeled trust, 1 labeled escalate if breach else trust) + 5 cases scored 0.2
    (labeled escalate). Hand-verified: at threshold 0.9 this gives kappa 0.8 (clears 0.6) with a
    false-auto-send rate of 0.1 (breach, ceiling 0.05) when the 5th case is mislabeled, or 0.0 (no breach)
    when it agrees. Threshold 0.2 always scores kappa 0 (every case predicted trust), so calibrate() must
    pick 0.9, the only clearing candidate, in both variants."""
    fifth_label = "escalate" if breach else "trust"
    return (
        [_case(f"c{i}", "trust") for i in range(1, 5)] + [_case("c5", fifth_label)]
        + [_case(f"c{i}", "escalate") for i in range(6, 11)]
    )


def _scores() -> list[float]:
    return [0.9] * 5 + [0.2] * 5


def test_run_calibration_raises_ceiling_breached_when_the_gate_fails():
    with pytest.raises(CeilingBreached) as exc_info:
        run_calibration(_cases(breach=True), QueuedJudgeClient(_scores()), golden_set_size=10, eval_case_count=0)

    assert exc_info.value.rate == pytest.approx(0.1)
    assert exc_info.value.wrong_case_ids == ["c5"]


def test_run_calibration_returns_a_payload_when_the_gate_clears():
    payload = run_calibration(_cases(breach=False), QueuedJudgeClient(_scores()), golden_set_size=10, eval_case_count=0)

    assert payload["threshold"] == 0.9
    assert payload["kappa"] == pytest.approx(1.0)
    assert payload["false_auto_send_rate"] == 0.0


def test_run_calibration_raises_no_acceptable_threshold_when_kappa_never_clears():
    cases = [_case("c1", "trust"), _case("c2", "escalate")]
    with pytest.raises(NoAcceptableThreshold):
        run_calibration(cases, QueuedJudgeClient([0.5, 0.5]), golden_set_size=2, eval_case_count=0)


def test_dry_run_prints_and_returns_before_scoring_anything(capsys, monkeypatch):
    """main()'s no-`--yes` branch returns before it would ever call run_calibration or touch CALIBRATION_PATH."""
    monkeypatch.setattr(sys, "argv", ["calibrate_judge.py"])

    from scripts import calibrate_judge

    calibrate_judge.main()

    assert "dry run" in capsys.readouterr().out
```

`RawDimensionScore`/`RawJudgeScore` already exist in `core/llm/anthropic_judge_client.py` (Phase 5), used the same way `ScriptedJudgeClient` in `tests/app/judge/fakes.py` already uses them.

The two-case `NoAcceptableThreshold` scenario is hand-verified the same way: scores `[0.5, 0.5]` (one candidate threshold, 0.5), labels `[True, False]` — `rate_a=1.0` (both predicted trust), `agree=0.5`, `expected=1*0.5+0*0.5=0.5`, `kappa=(0.5-0.5)/(1-0.5)=0`, below `KAPPA_ACCEPTABLE=0.6`, so `calibrate()` returns `None`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/app/judge/test_calibration.py tests/scripts/test_calibrate_judge.py -v`
Expected: FAIL — `ImportError: cannot import name 'false_auto_send_rate'` (and `ImportError: cannot import name 'run_calibration'` for the scripts tests).

- [ ] **Step 3: Implement**

```python
# backend/app/judge/calibration.py -- full file
from dataclasses import dataclass, field

from app.judge.scoring import gate


@dataclass(frozen=True)
class CalibrationResult:
    threshold: float
    kappa: float
    pairs: list[tuple[bool, bool]] = field(default_factory=list)


def cohens_kappa(pairs: list[tuple[bool, bool]]) -> float:
    """Standard 2x2 Cohen's kappa between two boolean raters (here: judge-trusts vs. human-trusts)."""
    n = len(pairs)
    if n == 0:
        return 0.0
    agree = sum(1 for a, b in pairs if a == b) / n
    rate_a = sum(1 for a, _ in pairs if a) / n
    rate_b = sum(1 for _, b in pairs if b) / n
    expected = rate_a * rate_b + (1 - rate_a) * (1 - rate_b)
    if expected == 1.0:
        return 1.0 if agree == 1.0 else 0.0
    return (agree - expected) / (1 - expected)


def false_auto_send_rate(pairs: list[tuple[bool, bool]]) -> float:
    """Fraction of cases the judge would auto-send (trust) that a human actually labeled wrong."""
    if not pairs:
        return 0.0
    return sum(1 for trust, human in pairs if trust and not human) / len(pairs)


def calibrate(scores: list[float], labels: list[bool], acceptable_kappa: float) -> CalibrationResult | None:
    """Sweeps every observed confidence score as a candidate threshold and returns the LOWEST one whose
    kappa against the golden set's human labels still clears acceptable_kappa: the lowest threshold
    maximizes how much gets auto-trusted (coverage) without dropping below the agreement bar. Returns
    None when no candidate clears it, per the research: a low kappa means fix the rubric, not ship a
    threshold that failed its own check."""
    best = None
    for candidate in sorted(set(scores)):
        pairs = [(gate(score, candidate), label) for score, label in zip(scores, labels)]
        kappa = cohens_kappa(pairs)
        if kappa >= acceptable_kappa and (best is None or candidate < best.threshold):
            best = CalibrationResult(threshold=candidate, kappa=kappa, pairs=pairs)
    return best
```

```python
# backend/app/judge/constant.py -- full file
from pathlib import Path

DEFAULT_CONFIDENCE_THRESHOLD = 0.8
KAPPA_ACCEPTABLE = 0.6
FALSE_AUTO_SEND_CEILING = 0.05
CALIBRATION_PATH = Path(__file__).resolve().parents[2] / "data" / "judge_calibration.json"
```

```python
# backend/scripts/calibrate_judge.py -- full file
import argparse
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from anthropic import Anthropic
from sqlalchemy import select

from app.judge.calibration import calibrate, false_auto_send_rate
from app.judge.constant import CALIBRATION_PATH, FALSE_AUTO_SEND_CEILING, KAPPA_ACCEPTABLE
from app.judge.evidence import ContractEvidence, GraphEvidence, LineEvidence, PriceEvidence
from app.judge.models import EvalCaseRow
from app.judge.prompts import JUDGE_SYSTEM_PROMPT
from app.judge.scoring import ScoredDimension, rollup
from core.config.settings import Settings
from core.db.session import make_engine, make_session_factory
from core.llm.anthropic_judge_client import AnthropicJudgeClient

GOLDEN_SET_PATH = Path(__file__).resolve().parent.parent / "data" / "judge_golden_set.json"


def _line_evidence_from_dict(d: dict) -> LineEvidence:
    return LineEvidence(
        line_index=d["line_index"], sku_id=d["sku_id"], unit_price=d["unit_price"],
        price=PriceEvidence(**d["price"]), contract=ContractEvidence(**d["contract"]), graph=GraphEvidence(**d["graph"]),
    )


def _load_eval_cases() -> list[dict]:
    session = make_session_factory(make_engine(Settings().database_url))()
    try:
        rows = session.scalars(select(EvalCaseRow)).all()
        return [
            {
                "case_id": row.case_id, "label": row.label, "estimate_status": row.estimate_status,
                "evidence": [{"line_index": e.get("line_index", 0), "sku_id": e["sku_id"], **_line_defaults(e)} for e in row.evidence],
            }
            for row in rows
        ]
    finally:
        session.close()


def _line_defaults(e: dict) -> dict:
    """Reviewer-corrected eval cases carry the flat per-line evidence dict app/judge/service.py's
    _dimension_evidence() produces, not the golden set's nested price/contract/graph shape. Normalize it here so
    _line_evidence_from_dict() can consume both."""
    return {
        "unit_price": e.get("unit_price", 0.0),
        "price": {"price_source": e.get("price_source", "list"), "list_price": e.get("list_price"),
                   "predicted_price": e.get("predicted_price"), "peer_count": e.get("peer_count"),
                   "low": e.get("low"), "high": e.get("high")},
        "contract": {"discount_pct": e.get("discount_pct", 0.0), "contract_id": e.get("contract_id"),
                     "covered": e.get("covered"), "active_on_as_of": e.get("active_on_as_of"),
                     "days_to_expiry": e.get("days_to_expiry")},
        "graph": {"discontinued": e.get("discontinued", False), "live_sku_id": e.get("live_sku_id"),
                  "required_part_ids": e.get("required_part_ids", []),
                  "missing_required_part_ids": e.get("missing_required_part_ids", [])},
    }


class NoAcceptableThreshold(Exception):
    pass


class CeilingBreached(Exception):
    def __init__(self, rate: float, wrong_case_ids: list[str]) -> None:
        super().__init__(f"false-auto-send rate {rate:.3f} exceeds ceiling {FALSE_AUTO_SEND_CEILING}")
        self.rate = rate
        self.wrong_case_ids = wrong_case_ids


def run_calibration(cases: list[dict], client: AnthropicJudgeClient, golden_set_size: int, eval_case_count: int) -> dict:
    """Scores every 'ready' case, calibrates a threshold, and checks the false-auto-send release gate. Returns
    the payload to write to CALIBRATION_PATH. Raises NoAcceptableThreshold or CeilingBreached instead of writing
    anything when either check fails, so a caller can never accidentally persist a threshold that failed its own
    gate."""
    fast_path_cases = [c for c in cases if c["estimate_status"] != "ready"]
    for case in fast_path_cases:
        assert case["label"] == "escalate", (
            f"fast-path case {case['case_id']} must be labeled escalate, got {case['label']!r}"
        )

    ready_cases = [c for c in cases if c["estimate_status"] == "ready"]
    scores: list[float] = []
    labels: list[bool] = []
    for case in ready_cases:
        labels.append(case["label"] == "trust")
        lines = [_line_evidence_from_dict(d) for d in case["evidence"]]
        raw = client.score([asdict(line) for line in lines], JUDGE_SYSTEM_PROMPT)
        scored = [ScoredDimension(name=d.name, score=d.score, rationale=d.rationale) for d in raw.dimensions]
        overall, _ = rollup(scored)
        scores.append(overall)

    result = calibrate(scores, labels, KAPPA_ACCEPTABLE)
    if result is None:
        raise NoAcceptableThreshold(f"no threshold clears kappa >= {KAPPA_ACCEPTABLE}")

    rate = false_auto_send_rate(result.pairs)
    if rate > FALSE_AUTO_SEND_CEILING:
        wrong_case_ids = [c["case_id"] for c, (trust, human) in zip(ready_cases, result.pairs) if trust and not human]
        raise CeilingBreached(rate, wrong_case_ids)

    return {
        "threshold": result.threshold, "kappa": result.kappa, "golden_set_size": golden_set_size,
        "eval_case_count": eval_case_count, "false_auto_send_rate": rate, "computed_at": date.today().isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate the judge's confidence threshold (dry run unless --yes)")
    parser.add_argument("--yes", action="store_true", help="actually call the Anthropic API (costs money)")
    args = parser.parse_args()

    golden_cases = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))
    eval_cases = _load_eval_cases()
    cases = golden_cases + eval_cases
    ready_count = len([c for c in cases if c["estimate_status"] == "ready"])
    print(f"{len(cases)} cases total ({len(golden_cases)} golden set, {len(eval_cases)} reviewer-corrected), "
          f"{ready_count} to score")
    print(f"estimated tokens: about {ready_count * 400} across {ready_count} calls to claude-haiku-4-5")
    if not args.yes:
        print("dry run: pass --yes to call the API")
        return

    settings = Settings()
    client = AnthropicJudgeClient(client=Anthropic(api_key=settings.anthropic_api_key))
    try:
        payload = run_calibration(cases, client, len(golden_cases), len(eval_cases))
    except NoAcceptableThreshold as exc:
        print(str(exc))
        sys.exit(1)
    except CeilingBreached as exc:
        print(f"release gate failed: {exc}")
        print("these cases would auto-send wrongly at this threshold:")
        for case_id in exc.wrong_case_ids:
            print(f"  {case_id}")
        sys.exit(1)

    CALIBRATION_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote threshold {payload['threshold']} (kappa {payload['kappa']:.2f}, "
        f"false-auto-send {payload['false_auto_send_rate']:.3f}) to {CALIBRATION_PATH}"
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/app/judge/test_calibration.py tests/scripts/test_calibrate_judge.py tests/data_gen/test_judge_golden_set.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/judge/calibration.py backend/app/judge/constant.py backend/scripts/calibrate_judge.py backend/tests/app/judge/test_calibration.py backend/tests/scripts/
git commit -m "feat: add false-auto-send release gate to judge calibration"
```

---

## Task 10: Langfuse tracing in the estimate agent loop

**Files:**
- Modify: `backend/app/estimate/tools.py`, `backend/app/estimate/graph.py`, `backend/app/estimate/service.py`, `backend/api/v1/estimate/route.py`, `backend/tests/graph_support.py`
- Test: `backend/tests/app/estimate/test_graph_tools.py` (extend), `backend/tests/app/estimate/test_service.py` (extend if it exists, else `backend/tests/app/estimate/test_graph.py`)

**Interfaces:**
- Consumes: `core.tracing.langfuse_client.TracingClient`, `TraceHandle`, `get_tracing_client` (Task 4).
- Produces: `ToolContext.trace: TraceHandle` (new field, defaulted); `run_estimate(..., tracing: TracingClient)` (new required parameter).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/app/estimate/test_graph_tools.py -- add at end of file
from core.tracing.langfuse_client import TraceHandle


class RecordingTraceHandle:
    def __init__(self):
        self.opened = []

    def span(self, name, **metadata):
        self.opened.append((name, metadata))
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def update(self, **metadata):
        pass


def test_handle_tool_opens_a_span_named_after_the_tool(db_session, make_reader):
    make_reader()
    trace = RecordingTraceHandle()
    ctx = _ctx(db_session, make_reader, trace=trace)

    handle_tool(ctx, "check_stock", {"sku_id": "SKU-E-A1"})

    assert trace.opened == [("tool_call", {"tool": "check_stock"})]


def test_tool_context_defaults_to_a_no_op_trace_handle():
    from app.estimate.tools import ToolContext

    ctx = ToolContext(session=None, as_of=None, graph=None, knowledge=None, request_customer_id=None, request_sku_ids=())
    assert isinstance(ctx.trace, TraceHandle)
```

(`_ctx` is this test file's existing helper for building a `ToolContext`; update its signature in Step 3 below to accept an optional `trace` kwarg, forwarded to `make_ctx`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/app/estimate/test_graph_tools.py -v -k "opens_a_span or defaults_to_a_no_op"`
Expected: FAIL — `TypeError: handle_tool() ... ctx.trace` (attribute does not exist) or `_ctx() got an unexpected keyword argument 'trace'`.

- [ ] **Step 3: Implement**

```python
# backend/app/estimate/tools.py -- modify imports and ToolContext, modify handle_tool
from dataclasses import dataclass, field
...
from core.tracing.langfuse_client import TraceHandle


@dataclass(frozen=True)
class ToolContext:
    session: Session
    as_of: date
    graph: GraphReader
    knowledge: KnowledgeService
    request_customer_id: str | None
    request_sku_ids: tuple[str, ...]
    trace: TraceHandle = field(default_factory=lambda: TraceHandle(None, None))
```

```python
# backend/app/estimate/tools.py -- modify handle_tool
def handle_tool(ctx: ToolContext, name: str, arguments: dict) -> dict:
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return {"error": f"unknown tool {name}"}
    try:
        inspect.signature(handler).bind(ctx, **arguments)
    except TypeError as exc:
        return {"error": f"bad arguments for {name}: {exc}"}
    for arg_name, value in arguments.items():
        if not isinstance(value, str):
            return {"error": f"bad arguments for {name}: {arg_name} must be a string"}
    with ctx.trace.span("tool_call", tool=name) as span:
        result = handler(ctx, **arguments)
        span.update(output=result)
        return result
```

```python
# backend/app/estimate/graph.py -- modify guardrails_node's graph_check line
            graph_check = check_graph_integrity(ctx.graph, draft, ctx.request_sku_ids)
```
becomes
```python
            with ctx.trace.span("graph_integrity_check") as span:
                graph_check = check_graph_integrity(ctx.graph, draft, ctx.request_sku_ids)
                span.update(output={
                    "violation_count": len(graph_check.violations), "unreplaceable": graph_check.unreplaceable,
                })
```

```python
# backend/app/estimate/service.py -- modify run_estimate's signature and body
from core.tracing.langfuse_client import TracingClient


def run_estimate(
    session: Session, quote_request_id: uuid.UUID, as_of: date, llm_client, graph: GraphReader, embedder: Embedder,
    tracing: TracingClient,
) -> EstimateRunResult:
    quote_request = get_quote_request(session, quote_request_id)
    if quote_request is None:
        raise QuoteRequestNotFound(f"quote request {quote_request_id} not found")

    with tracing.trace("estimate_run", quote_request_id=str(quote_request_id)) as trace:
        ctx = ToolContext(
            session=session, as_of=as_of, graph=graph,
            knowledge=KnowledgeService(session=session, graph=graph, embedder=embedder),
            request_customer_id=quote_request.customer_id, request_sku_ids=_request_sku_ids(quote_request),
            trace=trace,
        )
        state = run_agent(llm_client, ctx, build_request_message(quote_request, as_of))

        draft = state["last_draft"]
        result = EstimateResult(
            status=state["status"], as_of=as_of, draft=draft,
            totals=compute_totals(draft.lines) if draft else None,
            violations=state["violations"], iterations=state["submissions"], reason=state["reason"],
        )
        trace.update(output={"status": result.status, "iterations": result.iterations})
    row = save_estimate_draft(
        session, quote_request_id=quote_request_id, status=result.status,
        draft=draft.model_dump(mode="json") if draft else None,
        violations=[v.model_dump(mode="json") for v in result.violations],
        iterations=result.iterations, reason=result.reason,
    )
    return EstimateRunResult(row=row, result=result)
```

```python
# backend/api/v1/estimate/route.py -- add import and Depends param, pass through
from core.tracing.langfuse_client import TracingClient, get_tracing_client

...

@router.post("", response_model=EstimateResponse)
def create_estimate(
    body: EstimateRequest,
    session: Session = Depends(get_session),
    llm_client: OpenAIAgentClient = Depends(get_agent_client),
    graph_client: GraphClient = Depends(get_graph_client),
    ns: str = Depends(get_graph_namespace),
    embedder: OpenAIEmbeddingClient = Depends(get_embedding_client),
    tracing: TracingClient = Depends(get_tracing_client),
) -> EstimateResponse:
    try:
        run = run_estimate(
            session, body.quote_request_id, body.as_of or DATASET_AS_OF, llm_client,
            GraphReader(graph_client, ns), embedder, tracing,
        )
```
(rest of the function body unchanged)

```python
# backend/tests/graph_support.py -- modify make_ctx
def make_ctx(session, graph, *, as_of=AS_OF, customer_id=None, sku_ids=(), embedder=None, trace=None) -> ToolContext:
    knowledge = KnowledgeService(session=session, graph=graph, embedder=embedder or FakeEmbedder())
    kwargs = {
        "session": session, "as_of": as_of, "graph": graph, "knowledge": knowledge, "request_customer_id": customer_id,
        "request_sku_ids": tuple(sku_ids),
    }
    if trace is not None:
        kwargs["trace"] = trace
    return ToolContext(**kwargs)
```

`test_graph_tools.py`'s own `_ctx(db_session, make_reader, **kwargs)` helper already forwards `**kwargs` straight to `make_ctx`, so it needs no edit: `_ctx(db_session, make_reader, trace=trace)` already works once `make_ctx` gains the `trace` parameter above.

Eight existing call sites pass `run_estimate(...)` without a `tracing` argument and must each gain `, TracingClient(None)` as the final positional argument (adding `from core.tracing.langfuse_client import TracingClient` to each file's imports if not already present from another edit in this task):
- `backend/tests/test_phase4_acceptance.py:159`
- `backend/tests/test_phase3_acceptance.py:81`, `:106`, `:124`, `:149`
- `backend/tests/app/estimate/test_service.py:18`, `:153`, `:197`

For example, `test_service.py:18`'s `return run_estimate(db_session, request_id, AS_OF, llm, make_reader(), FakeEmbedder())` becomes `return run_estimate(db_session, request_id, AS_OF, llm, make_reader(), FakeEmbedder(), TracingClient(None))`; apply the same pattern (append `, TracingClient(None)` before the closing parenthesis) at each of the other seven call sites listed above.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/app/estimate/ tests/api/v1/test_estimate_route.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/estimate/tools.py backend/app/estimate/graph.py backend/app/estimate/service.py backend/api/v1/estimate/route.py backend/tests/graph_support.py backend/tests/app/estimate/
git commit -m "feat: trace the estimate agent loop, tool calls, and graph-integrity checks"
```

---

## Task 11: Langfuse tracing in dedupe

**Files:**
- Modify: `backend/app/dedupe/service.py`, `backend/api/v1/dedupe/route.py`
- Test: `backend/tests/app/dedupe/test_service.py`

**Interfaces:**
- Consumes: `core.tracing.langfuse_client.TracingClient`, `get_tracing_client` (Task 4).
- Produces: `run_dedupe(session, quote_request_id, tracing: TracingClient)` (new required parameter).

- [ ] **Step 1: Update existing calls and write the failing tests**

`backend/tests/app/dedupe/test_service.py` already has six calls to `run_dedupe(db_session, <id>)`. Add `from core.tracing.langfuse_client import TracingClient` to its imports, and add a `, TracingClient(None)` argument to each of the six existing calls (`test_run_dedupe_flags_identical_sku_set_as_duplicate`, `test_run_dedupe_flags_superset_as_revision`, `test_run_dedupe_excludes_the_target_itself_from_candidates`, `test_run_dedupe_unresolved_customer_and_site_yields_no_candidates`, `test_run_dedupe_raises_for_unknown_quote_request`, `test_run_dedupe_blocks_on_shared_contract_alone`), e.g. `run_dedupe(db_session, second.id)` becomes `run_dedupe(db_session, second.id, TracingClient(None))`.

Then add two new tests at the end of the file, reusing its existing `_seed_customer_and_site`/`_make_request` helpers:

```python
class RecordingTraceHandle:
    def __init__(self):
        self.opened = []

    def span(self, name, **metadata):
        self.opened.append((name, metadata))
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def update(self, **metadata):
        pass


class RecordingTracingClient:
    def __init__(self):
        self.handle = RecordingTraceHandle()

    def trace(self, name, **metadata):
        self.handle.opened.append((name, metadata))
        return self.handle


def test_run_dedupe_opens_a_span_per_verdict(db_session):
    _seed_customer_and_site(db_session)
    first = _make_request(db_session, "CUST-A", "SITE-A", ["SKU-A", "SKU-B"])
    second = _make_request(db_session, "CUST-A", "SITE-A", ["SKU-A", "SKU-B"])
    db_session.flush()
    tracing = RecordingTracingClient()

    verdicts = run_dedupe(db_session, second.id, tracing)

    assert len(verdicts) == 1
    assert tracing.handle.opened == [("dedupe_verdict", {"candidate_id": str(first.id)})]


def test_run_dedupe_works_with_no_tracing_configured(db_session):
    _seed_customer_and_site(db_session)
    only_request = _make_request(db_session, "CUST-A", "SITE-A", ["SKU-A"])
    db_session.flush()

    verdicts = run_dedupe(db_session, only_request.id, TracingClient(None))

    assert verdicts == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/app/dedupe/test_service.py -v`
Expected: FAIL — `TypeError: run_dedupe() missing 1 required positional argument: 'tracing'` on every test in the file.

- [ ] **Step 3: Implement**

```python
# backend/app/dedupe/service.py -- modify signature and body
from core.tracing.langfuse_client import TracingClient


def run_dedupe(session: Session, quote_request_id: uuid.UUID, tracing: TracingClient) -> list[DedupeVerdictRow]:
    target = session.get(QuoteRequestRow, quote_request_id)
    if target is None:
        raise ValueError(f"quote_request {quote_request_id} not found")

    candidates = find_blocked_candidates(session, target)
    verdicts: list[DedupeVerdictRow] = []

    target_sku_ids = set(target.content_fingerprint.get("sku_ids", []))
    target_tokens = set(target.style_fingerprint.get("tokens", []))

    with tracing.trace("dedupe_run", quote_request_id=str(quote_request_id)) as trace:
        for candidate in candidates:
            candidate_sku_ids = set(candidate.content_fingerprint.get("sku_ids", []))
            candidate_tokens = set(candidate.style_fingerprint.get("tokens", []))

            verdict, content_score, content_signals = classify(target_sku_ids, candidate_sku_ids)
            style_score = jaccard(target_tokens, candidate_tokens)
            signals = _blocking_signals(target, candidate) + content_signals

            with trace.span("dedupe_verdict", candidate_id=str(candidate.id)) as span:
                row = save_verdict(
                    session, quote_request_id=target.id, candidate_quote_request_id=candidate.id,
                    verdict=verdict, content_jaccard=content_score, style_jaccard=style_score, signals_fired=signals,
                )
                span.update(output={"verdict": verdict, "content_jaccard": content_score, "style_jaccard": style_score})
            verdicts.append(row)

    return verdicts
```

```python
# backend/api/v1/dedupe/route.py -- add import and Depends param, pass through
from core.tracing.langfuse_client import TracingClient, get_tracing_client

...

@router.post("/{quote_request_id}", response_model=DedupeResponse)
def dedupe_quote_request(
    quote_request_id: uuid.UUID,
    session: Session = Depends(get_session),
    graph_client: GraphClient = Depends(get_graph_client),
    ns: str = Depends(get_graph_namespace),
    tracing: TracingClient = Depends(get_tracing_client),
) -> DedupeResponse:
    try:
        verdicts = run_dedupe(session, quote_request_id, tracing)
```
(rest of the function body unchanged)

Any existing call site of `run_dedupe(...)` in tests must gain a `TracingClient(None)` third argument; update every one found under `backend/tests/`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/app/dedupe/ tests/api/v1/test_dedupe_route.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/dedupe/service.py backend/api/v1/dedupe/route.py backend/tests/app/dedupe/test_service.py
git commit -m "feat: trace dedupe verdict decisions"
```

---

## Final verification (after all tasks)

Run the full suite once, against the real dev Postgres (5433) and Neo4j (17687), migrations at head:

```bash
cd backend
alembic upgrade head
pytest -v
```

Expected: every test passes, zero real Anthropic/OpenAI/Langfuse network calls, no test asserts an absolute row/node count against the shared databases.
