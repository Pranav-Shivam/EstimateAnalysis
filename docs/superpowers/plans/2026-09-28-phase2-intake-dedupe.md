# Phase 2: Intake and Dedupe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a raw quote-request email into structured, entity-resolved data (intake) and correctly classify it as a duplicate, a revision, or distinct against existing requests (dedupe), verified against Phase 1's 60 known-label scenario emails.

**Architecture:** FastAPI routes over a service/repository layering (route -> service -> repo -> Postgres/OpenAI), per `docs/backend-structure.txt`. Postgres (via Docker Compose, pgvector image per ADR-0001) holds both the reference data loaded from Phase 1's flat JSON and the app's own `quote_requests`/`dedupe_verdicts` tables. Intake calls OpenAI's structured-output API once per email; dedupe is pure algorithmic classification (blocking + Jaccard set comparison), no LLM involved.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (declarative ORM), Alembic, Postgres (`pgvector/pgvector` Docker image), `pydantic-settings`, raw `openai` Python SDK (structured outputs), `rapidfuzz`.

**Spec:** `docs/superpowers/specs/2026-09-28-phase2-intake-dedupe-design.md`

## Prerequisites (read before dispatching Task 1)

Postgres must be reachable at `postgresql+psycopg://postgres:postgres@localhost:5432/estimate_analysis` before Task 2 (and everything after it) can run its own tests. This project's Docker runs through WSL, not the Windows-native Docker Desktop pipe — start it with `docker compose up -d` from a WSL terminal, using the `docker-compose.yml` Task 1 creates. Confirm the port is reachable (e.g. `docker compose ps` shows the service healthy) before proceeding past Task 1. Every implementer subagent from Task 2 onward needs this already running; it is not something any task starts itself.

## Global Constraints

- Postgres via `docker-compose.yml` at repo root, `pgvector/pgvector:pg16` image (ADR-0001). No task or test invokes `docker` directly; starting/stopping the container is the human's job.
- Alembic migrations live under `backend/migrations/`; one revision (`0001_initial_schema`) creates all 6 tables together.
- `core/config/settings.py` reads `DATABASE_URL` and `OPENAI_API_KEY` from the environment/`.env` via `pydantic-settings`. `backend/.env.example` lists variable names only, never real values. No code or test ever reads or prints the contents of `backend/.env`.
- No test in the default `pytest` run makes a real OpenAI API call; intake's LLM call is mocked/stubbed everywhere except an explicitly separate, non-default integration check.
- Raw OpenAI Python SDK structured outputs for extraction (`client.responses.parse(..., text_format=QuoteRequestExtraction)`). No LangGraph in this phase.
- Entity resolution: exact case-insensitive name match first; `rapidfuzz.fuzz.token_sort_ratio` fallback, threshold 90; zero or multiple qualifying candidates resolve to `None` (never guessed).
- Dedupe classifier: `content_jaccard == 1.0` (non-empty sets) -> `DUPLICATE_OF`; one SKU-id set a strict superset of the other AND `content_jaccard >= 0.4` -> `REVISION_OF`; otherwise -> `DISTINCT`.
- Every scored candidate pair — including `DISTINCT` ones — gets a `dedupe_verdicts` row.
- No em dash anywhere in code, comments, or commit messages. No emojis. Commit messages never mention AI/Claude/Anthropic authorship.

## Review Focus

- A customer or SKU name fuzzy-matches two different real records above the threshold (a tie) -> must resolve to `None`, never pick one arbitrarily. Test added in Task 6.
- An extracted email has zero line items (a vague inquiry with no clear product ask) -> the `QuoteRequest` is still stored with an empty line-item list; nothing crashes. Test added in Task 7.
- The dedupe blocking query must never return the request being scored as its own candidate. Test added in Task 10.
- The classifier must never treat an unresolved (empty) SKU set as a subset of another request's SKU set (an empty set is not a meaningful "revision" of anything). Test added in Task 9.
- An OpenAI extraction call that raises (network error, rate limit, malformed response) must surface as a clean error with nothing stored — never a partial or guessed `QuoteRequest`. Test added in Task 7.

---

### Task 1: Dependencies, config, and Docker Compose

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `docker-compose.yml` (repo root)
- Create: `backend/.env.example`
- Create: `backend/core/__init__.py`
- Create: `backend/core/config/__init__.py`
- Create: `backend/core/config/settings.py`
- Test: `backend/tests/core/__init__.py`
- Test: `backend/tests/core/test_settings.py`

**Interfaces:**
- Produces: `core.config.settings.Settings` (pydantic-settings `BaseSettings` subclass with `database_url: str` (defaulted to the compose connection string) and `openai_api_key: str` (required, no default)).

- [ ] **Step 1: Add dependencies**

Run: `uv add fastapi "uvicorn[standard]" sqlalchemy "psycopg[binary]" alembic pydantic-settings openai rapidfuzz`
Run: `uv add --dev httpx`

- [ ] **Step 2: Write `docker-compose.yml`**

```yaml
services:
  postgres:
    image: pgvector/pgvector:0.8.6-pg16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: estimate_analysis
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

- [ ] **Step 3: Write `backend/.env.example`**

```
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/estimate_analysis
OPENAI_API_KEY=
```

- [ ] **Step 4: Write the failing test**

```python
# backend/tests/core/test_settings.py
import pytest
from pydantic import ValidationError

from core.config.settings import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    settings = Settings(_env_file=None)
    assert settings.database_url == "postgresql+psycopg://u:p@localhost:5432/db"
    assert settings.openai_api_key == "sk-test"


def test_settings_database_url_has_compose_default(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    settings = Settings(_env_file=None)
    assert settings.database_url == "postgresql+psycopg://postgres:postgres@localhost:5432/estimate_analysis"


def test_settings_missing_openai_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
```

- [ ] **Step 5: Run test to verify it fails**

Run: `uv run pytest tests/core/test_settings.py -v`
Expected: FAIL with "No module named 'core'" or similar import error.

- [ ] **Step 6: Write `backend/core/config/settings.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/estimate_analysis"
    openai_api_key: str
```

Also create empty `backend/core/__init__.py` and `backend/core/config/__init__.py`, and `backend/tests/core/__init__.py`.

- [ ] **Step 7: Update `backend/pyproject.toml`'s pytest config**

```toml
[tool.pytest.ini_options]
pythonpath = ["scripts", "."]
testpaths = ["tests"]
```

(Keep the existing `scripts` entry; add `"."` alongside it so `core`/`app`/`api` packages import cleanly regardless of pytest's rootdir-insertion behavior.)

- [ ] **Step 8: Run test to verify it passes**

Run: `uv run pytest tests/core/test_settings.py -v`
Expected: PASS (3 tests)

- [ ] **Step 9: Commit**

```bash
git add docker-compose.yml backend/.env.example backend/pyproject.toml backend/uv.lock backend/core backend/tests/core
git commit -m "feat: add Phase 2 dependencies, settings, and Postgres compose file"
```

---

### Task 2: Database session plumbing and initial migration

**Files:**
- Create: `backend/core/db/__init__.py`
- Create: `backend/core/db/base.py`
- Create: `backend/core/db/session.py`
- Create: `backend/alembic.ini`
- Create: `backend/migrations/env.py`
- Create: `backend/migrations/script.py.mako`
- Create: `backend/migrations/versions/0001_initial_schema.py`
- Create: `backend/tests/conftest.py`
- Test: `backend/tests/core/test_db_session.py`

**Interfaces:**
- Consumes: `core.config.settings.Settings` (Task 1).
- Produces: `core.db.base.Base` (SQLAlchemy `DeclarativeBase`, imported by every later module's ORM models); `core.db.session.make_engine(database_url: str) -> Engine`; `core.db.session.make_session_factory(engine: Engine) -> sessionmaker`; `core.db.session.get_session() -> Iterator[Session]` (FastAPI dependency, lazily builds the app-wide engine from `Settings()` on first call, commits on success, rolls back on exception); `backend/tests/conftest.py`'s `db_session` pytest fixture (a `Session` bound to a transaction that is rolled back after each test, so tests never leave rows behind).

- [ ] **Step 1: Write `backend/core/db/base.py`**

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

Create `backend/core/db/__init__.py` (empty).

- [ ] **Step 2: Write `backend/core/db/session.py`**

```python
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from core.config.settings import Settings


def make_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@lru_cache
def _app_session_factory() -> sessionmaker:
    settings = Settings()
    engine = make_engine(settings.database_url)
    return make_session_factory(engine)


def get_session() -> Iterator[Session]:
    session = _app_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
```

- [ ] **Step 3: Write `backend/tests/conftest.py`**

```python
import os

import pytest

from core.db.session import make_engine, make_session_factory

TEST_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/estimate_analysis"
)


@pytest.fixture
def db_session():
    engine = make_engine(TEST_DATABASE_URL)
    connection = engine.connect()
    transaction = connection.begin()
    session_factory = make_session_factory(engine)
    session = session_factory(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()
```

- [ ] **Step 4: Write `backend/alembic.ini`**

```ini
[alembic]
script_location = migrations
prepend_sys_path = .

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 5: Write `backend/migrations/script.py.mako`**

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 6: Write `backend/migrations/env.py`**

Note: this imports `app.reference_data.models`, `app.intake.models`, and `app.dedupe.models` so `Base.metadata` is fully populated for any future `alembic revision --autogenerate`. Those modules do not exist until Tasks 3, 7, and 10 respectively — this task's migration does not depend on them (its `upgrade()`/`downgrade()` are hand-written with explicit `op.create_table` calls, not generated from metadata), so leave these three imports commented out in this task and uncomment them in Task 10 once all three modules exist. Running `alembic upgrade head` in this task works without them because Alembic only needs `target_metadata` for autogeneration, not for applying an already-written revision.

```python
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from core.config.settings import Settings
from core.db.base import Base

# Uncomment once Tasks 3, 7, and 10 have added these modules (needed only for
# `alembic revision --autogenerate`, not for applying this plan's hand-written revisions):
# from app.reference_data import models as reference_data_models  # noqa: F401
# from app.intake import models as intake_models  # noqa: F401
# from app.dedupe import models as dedupe_models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

config.set_main_option("sqlalchemy.url", Settings().database_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 7: Write `backend/migrations/versions/0001_initial_schema.py`**

```python
"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-28

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skus",
        sa.Column("sku_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("list_price", sa.Float(), nullable=False),
        sa.Column("discontinued", sa.Boolean(), nullable=False),
        sa.Column("replaced_by", sa.Text(), sa.ForeignKey("skus.sku_id"), nullable=True),
        sa.Column("in_stock", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "customers",
        sa.Column("customer_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("account_tier", sa.Text(), nullable=False),
    )
    op.create_table(
        "sites",
        sa.Column("site_id", sa.Text(), primary_key=True),
        sa.Column("customer_id", sa.Text(), sa.ForeignKey("customers.customer_id"), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("zip", sa.Text(), nullable=False),
    )
    op.create_table(
        "contracts",
        sa.Column("contract_id", sa.Text(), primary_key=True),
        sa.Column("customer_id", sa.Text(), sa.ForeignKey("customers.customer_id"), nullable=False),
        sa.Column("discount_category", sa.Text(), nullable=False),
        sa.Column("covered_categories", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=False),
    )
    op.create_table(
        "quote_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("case_id", sa.Text(), nullable=True),
        sa.Column("customer_id", sa.Text(), sa.ForeignKey("customers.customer_id"), nullable=True),
        sa.Column("site_id", sa.Text(), sa.ForeignKey("sites.site_id"), nullable=True),
        sa.Column("contract_id", sa.Text(), sa.ForeignKey("contracts.contract_id"), nullable=True),
        sa.Column("raw_email_text", sa.Text(), nullable=False),
        sa.Column("parsed_json", postgresql.JSONB(), nullable=False),
        sa.Column("content_fingerprint", postgresql.JSONB(), nullable=False),
        sa.Column("style_fingerprint", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "dedupe_verdicts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("quote_request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("quote_requests.id"), nullable=False),
        sa.Column("candidate_quote_request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("quote_requests.id"), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("content_jaccard", sa.Float(), nullable=False),
        sa.Column("style_jaccard", sa.Float(), nullable=False),
        sa.Column("signals_fired", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("dedupe_verdicts")
    op.drop_table("quote_requests")
    op.drop_table("contracts")
    op.drop_table("sites")
    op.drop_table("customers")
    op.drop_table("skus")
```

- [ ] **Step 8: Apply the migration**

Run: `uv run alembic upgrade head`
Expected: no errors; logs show `Running upgrade -> 0001, initial schema`.

- [ ] **Step 9: Write the test**

```python
# backend/tests/core/test_db_session.py
from sqlalchemy import inspect

from core.db.session import make_engine

TEST_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/estimate_analysis"


def test_all_six_tables_exist():
    engine = make_engine(TEST_DATABASE_URL)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"skus", "customers", "sites", "contracts", "quote_requests", "dedupe_verdicts"} <= tables
    engine.dispose()
```

- [ ] **Step 10: Run test to verify it passes**

Run: `uv run pytest tests/core/test_db_session.py -v`
Expected: PASS (requires Postgres running per Prerequisites)

- [ ] **Step 11: Commit**

```bash
git add backend/core/db backend/alembic.ini backend/migrations backend/tests/conftest.py backend/tests/core/test_db_session.py
git commit -m "feat: add database session plumbing and initial schema migration"
```

---

### Task 3: Reference-data models and repository

**Files:**
- Create: `backend/app/__init__.py`
- Create: `backend/app/reference_data/__init__.py`
- Create: `backend/app/reference_data/models.py`
- Create: `backend/app/reference_data/repository.py`
- Test: `backend/tests/app/__init__.py`
- Test: `backend/tests/app/reference_data/__init__.py`
- Test: `backend/tests/app/reference_data/test_repository.py`

**Interfaces:**
- Consumes: `core.db.base.Base` (Task 2), `backend/tests/conftest.py`'s `db_session` fixture (Task 2).
- Produces: ORM classes `Sku`, `Customer`, `Site`, `Contract` (`app.reference_data.models`); repository functions `upsert_sku`, `upsert_customer`, `upsert_site`, `upsert_contract`, `all_customers(session) -> list[Customer]`, `all_skus(session) -> list[Sku]`, `contracts_for_customer(session, customer_id: str) -> list[Contract]` (`app.reference_data.repository`).

- [ ] **Step 1: Write `backend/app/reference_data/models.py`**

```python
from datetime import date

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class Sku(Base):
    __tablename__ = "skus"

    sku_id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    category: Mapped[str]
    list_price: Mapped[float]
    discontinued: Mapped[bool]
    replaced_by: Mapped[str | None] = mapped_column(ForeignKey("skus.sku_id"))
    in_stock: Mapped[bool]


class Customer(Base):
    __tablename__ = "customers"

    customer_id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    account_tier: Mapped[str]


class Site(Base):
    __tablename__ = "sites"

    site_id: Mapped[str] = mapped_column(primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"))
    address: Mapped[str]
    zip: Mapped[str]


class Contract(Base):
    __tablename__ = "contracts"

    contract_id: Mapped[str] = mapped_column(primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"))
    discount_category: Mapped[str]
    covered_categories: Mapped[list[str]] = mapped_column(ARRAY(Text))
    effective_from: Mapped[date]
    effective_to: Mapped[date]
```

Create empty `backend/app/__init__.py` and `backend/app/reference_data/__init__.py`.

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/app/reference_data/test_repository.py
from datetime import date

from app.reference_data.models import Customer, Sku
from app.reference_data.repository import (
    all_customers,
    all_skus,
    contracts_for_customer,
    upsert_contract,
    upsert_customer,
    upsert_site,
    upsert_sku,
)


def test_upsert_sku_inserts_then_updates(db_session):
    upsert_sku(db_session, sku_id="SKU-T1", name="Widget", category="Cat", list_price=10.0,
               discontinued=False, replaced_by=None, in_stock=True)
    db_session.flush()
    row = db_session.get(Sku, "SKU-T1")
    assert row.name == "Widget"

    upsert_sku(db_session, sku_id="SKU-T1", name="Widget V2", category="Cat", list_price=12.0,
               discontinued=True, replaced_by=None, in_stock=False)
    db_session.flush()
    assert db_session.get(Sku, "SKU-T1").name == "Widget V2"
    assert len(all_skus(db_session)) == 1


def test_upsert_customer_site_contract_and_lookup(db_session):
    upsert_customer(db_session, customer_id="CUST-T1", name="Test Co", account_tier="Standard")
    upsert_site(db_session, site_id="SITE-T1", customer_id="CUST-T1", address="1 Main St", zip_code="00000")
    upsert_contract(
        db_session, contract_id="CTR-T1", customer_id="CUST-T1", discount_category="A",
        covered_categories=["A", "B"], effective_from=date(2024, 1, 1), effective_to=date(2025, 1, 1),
    )
    db_session.flush()

    customers = all_customers(db_session)
    assert any(c.customer_id == "CUST-T1" for c in customers)

    contracts = contracts_for_customer(db_session, "CUST-T1")
    assert len(contracts) == 1
    assert contracts[0].contract_id == "CTR-T1"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/app/reference_data/test_repository.py -v`
Expected: FAIL with "No module named 'app.reference_data.repository'"

- [ ] **Step 4: Write `backend/app/reference_data/repository.py`**

```python
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.reference_data.models import Contract, Customer, Site, Sku


def upsert_sku(
    session: Session, *, sku_id: str, name: str, category: str, list_price: float,
    discontinued: bool, replaced_by: str | None, in_stock: bool,
) -> None:
    row = session.get(Sku, sku_id)
    if row is None:
        row = Sku(sku_id=sku_id)
        session.add(row)
    row.name = name
    row.category = category
    row.list_price = list_price
    row.discontinued = discontinued
    row.replaced_by = replaced_by
    row.in_stock = in_stock


def upsert_customer(session: Session, *, customer_id: str, name: str, account_tier: str) -> None:
    row = session.get(Customer, customer_id)
    if row is None:
        row = Customer(customer_id=customer_id)
        session.add(row)
    row.name = name
    row.account_tier = account_tier


def upsert_site(session: Session, *, site_id: str, customer_id: str, address: str, zip_code: str) -> None:
    row = session.get(Site, site_id)
    if row is None:
        row = Site(site_id=site_id)
        session.add(row)
    row.customer_id = customer_id
    row.address = address
    row.zip = zip_code


def upsert_contract(
    session: Session, *, contract_id: str, customer_id: str, discount_category: str,
    covered_categories: list[str], effective_from: date, effective_to: date,
) -> None:
    row = session.get(Contract, contract_id)
    if row is None:
        row = Contract(contract_id=contract_id)
        session.add(row)
    row.customer_id = customer_id
    row.discount_category = discount_category
    row.covered_categories = covered_categories
    row.effective_from = effective_from
    row.effective_to = effective_to


def all_customers(session: Session) -> list[Customer]:
    return list(session.scalars(select(Customer)))


def all_skus(session: Session) -> list[Sku]:
    return list(session.scalars(select(Sku)))


def contracts_for_customer(session: Session, customer_id: str) -> list[Contract]:
    return list(session.scalars(select(Contract).where(Contract.customer_id == customer_id)))
```

Create empty `backend/tests/app/__init__.py` and `backend/tests/app/reference_data/__init__.py`.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/app/reference_data/test_repository.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/__init__.py backend/app/reference_data backend/tests/app
git commit -m "feat: add reference-data models and repository"
```

---

### Task 4: Reference-data loader script

**Files:**
- Create: `backend/scripts/load_data.py`
- Test: `backend/tests/test_load_data.py`

**Interfaces:**
- Consumes: `app.reference_data.repository` (Task 3), `core.db.session.make_engine`/`make_session_factory` (Task 2), `core.config.settings.Settings` (Task 1).
- Produces: `scripts.load_data.load_catalog(session, catalog: list[dict]) -> None`, `scripts.load_data.load_customers(session, customers: list[dict]) -> None`, `scripts.load_data.run(data_dir: Path) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_load_data.py
from datetime import date

from load_data import load_catalog, load_customers
from app.reference_data.models import Contract, Sku
from app.reference_data.repository import all_customers, all_skus


def test_load_catalog_resolves_replaced_by_after_insert(db_session):
    catalog = [
        {"sku_id": "SKU-A", "name": "Old Part", "category": "C", "list_price": 5.0,
         "discontinued": True, "replaced_by": "SKU-B", "in_stock": False, "requires": []},
        {"sku_id": "SKU-B", "name": "New Part", "category": "C", "list_price": 6.0,
         "discontinued": False, "replaced_by": None, "in_stock": True, "requires": []},
    ]
    load_catalog(db_session, catalog)
    db_session.flush()

    assert len(all_skus(db_session)) == 2
    assert db_session.get(Sku, "SKU-A").replaced_by == "SKU-B"


def test_load_customers_inserts_sites_and_contracts(db_session):
    customers = [{
        "customer_id": "CUST-T9", "name": "Test Co", "account_tier": "Standard",
        "contacts": [], "sites": [{"site_id": "SITE-T9", "address": "1 Main St", "zip": "00000"}],
        "contracts": [{
            "contract_id": "CTR-T9", "discount_category": "A", "covered_categories": ["A"],
            "effective_from": "2024-01-01", "effective_to": "2025-01-01",
        }],
    }]
    load_customers(db_session, customers)
    db_session.flush()

    assert any(c.customer_id == "CUST-T9" for c in all_customers(db_session))
    contract = db_session.get(Contract, "CTR-T9")
    assert contract.effective_from == date(2024, 1, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_load_data.py -v`
Expected: FAIL with "No module named 'load_data'"

- [ ] **Step 3: Write `backend/scripts/load_data.py`**

```python
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.reference_data.models import Sku
from app.reference_data.repository import upsert_contract, upsert_customer, upsert_site, upsert_sku
from core.config.settings import Settings
from core.db.session import make_engine, make_session_factory

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def load_catalog(session, catalog: list[dict]) -> None:
    for sku in catalog:
        upsert_sku(
            session, sku_id=sku["sku_id"], name=sku["name"], category=sku["category"],
            list_price=sku["list_price"], discontinued=sku["discontinued"], replaced_by=None,
            in_stock=sku["in_stock"],
        )
    session.flush()
    for sku in catalog:
        if sku["discontinued"] and sku["replaced_by"]:
            row = session.get(Sku, sku["sku_id"])
            row.replaced_by = sku["replaced_by"]


def load_customers(session, customers: list[dict]) -> None:
    for customer in customers:
        upsert_customer(session, customer_id=customer["customer_id"], name=customer["name"], account_tier=customer["account_tier"])
        for site in customer["sites"]:
            upsert_site(session, site_id=site["site_id"], customer_id=customer["customer_id"], address=site["address"], zip_code=site["zip"])
        for contract in customer["contracts"]:
            upsert_contract(
                session, contract_id=contract["contract_id"], customer_id=customer["customer_id"],
                discount_category=contract["discount_category"], covered_categories=contract["covered_categories"],
                effective_from=date.fromisoformat(contract["effective_from"]),
                effective_to=date.fromisoformat(contract["effective_to"]),
            )


def run(data_dir: Path = DATA_DIR) -> None:
    catalog = json.loads((data_dir / "catalog.json").read_text(encoding="utf-8"))
    customers = json.loads((data_dir / "customers.json").read_text(encoding="utf-8"))

    settings = Settings()
    engine = make_engine(settings.database_url)
    session = make_session_factory(engine)()
    try:
        load_catalog(session, catalog)
        load_customers(session, customers)
        session.commit()
        print(f"loaded {len(catalog)} SKUs, {len(customers)} customers into {settings.database_url}")
    finally:
        session.close()


if __name__ == "__main__":
    run()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_load_data.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Load the real Phase 1 dataset**

Run: `uv run python scripts/load_data.py`
Expected: `loaded 650 SKUs, 125 customers into postgresql+psycopg://...` (uses the real `backend/data/{catalog,customers}.json` committed earlier)

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/load_data.py backend/tests/test_load_data.py
git commit -m "feat: add reference-data loader script"
```

---

### Task 5: OpenAI extraction client and QuoteRequest schema

**Files:**
- Create: `backend/core/llm/__init__.py`
- Create: `backend/core/llm/openai_client.py`
- Create: `backend/app/intake/__init__.py`
- Create: `backend/app/intake/schemas.py`
- Test: `backend/tests/app/intake/__init__.py`
- Test: `backend/tests/core/test_openai_client.py`

**Interfaces:**
- Produces: Pydantic models `LineItemExtraction`, `QuoteRequestExtraction` (`app.intake.schemas`); `core.llm.openai_client.ExtractionError` (exception); `core.llm.openai_client.OpenAIExtractionClient` with method `extract_quote_request(email_text: str) -> QuoteRequestExtraction`.

- [ ] **Step 1: Write `backend/app/intake/schemas.py`**

```python
from pydantic import BaseModel


class LineItemExtraction(BaseModel):
    sku_name_as_written: str
    quantity: str | None = None


class QuoteRequestExtraction(BaseModel):
    customer_name_as_written: str
    contact_name_as_written: str | None = None
    site_hint: str | None = None
    line_items: list[LineItemExtraction]
    requested_by: str | None = None
    raw_text: str
```

Create empty `backend/app/intake/__init__.py`.

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/core/test_openai_client.py
from unittest.mock import MagicMock

import pytest

from app.intake.schemas import LineItemExtraction, QuoteRequestExtraction
from core.llm.openai_client import ExtractionError, OpenAIExtractionClient


def test_extract_quote_request_returns_parsed_model():
    fake_parsed = QuoteRequestExtraction(
        customer_name_as_written="Zenith Contractors",
        line_items=[LineItemExtraction(sku_name_as_written="Widget", quantity="4")],
        raw_text="need 4 widgets",
    )
    fake_response = MagicMock(output_parsed=fake_parsed)
    fake_openai_client = MagicMock()
    fake_openai_client.responses.parse.return_value = fake_response

    client = OpenAIExtractionClient(client=fake_openai_client)
    result = client.extract_quote_request("need 4 widgets")

    assert result.customer_name_as_written == "Zenith Contractors"
    assert result.line_items[0].sku_name_as_written == "Widget"


def test_extract_quote_request_raises_extraction_error_on_api_failure():
    fake_openai_client = MagicMock()
    fake_openai_client.responses.parse.side_effect = RuntimeError("rate limited")

    client = OpenAIExtractionClient(client=fake_openai_client)
    with pytest.raises(ExtractionError):
        client.extract_quote_request("some email")


def test_extract_quote_request_raises_when_response_has_no_parsed_output():
    fake_response = MagicMock(output_parsed=None)
    fake_openai_client = MagicMock()
    fake_openai_client.responses.parse.return_value = fake_response

    client = OpenAIExtractionClient(client=fake_openai_client)
    with pytest.raises(ExtractionError):
        client.extract_quote_request("some email")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/core/test_openai_client.py -v`
Expected: FAIL with "No module named 'core.llm.openai_client'"

- [ ] **Step 4: Write `backend/core/llm/openai_client.py`**

```python
from openai import OpenAI

from app.intake.schemas import QuoteRequestExtraction

EXTRACTION_MODEL = "gpt-4o"

EXTRACTION_INSTRUCTIONS = (
    "Extract a structured quote request from this customer email. "
    "Use only facts present in the email text; never invent a customer name, "
    "SKU name, or quantity that is not written there."
)


class ExtractionError(Exception):
    pass


class OpenAIExtractionClient:
    def __init__(self, client: OpenAI | None = None) -> None:
        self._client = client or OpenAI()

    def extract_quote_request(self, email_text: str) -> QuoteRequestExtraction:
        try:
            response = self._client.responses.parse(
                model=EXTRACTION_MODEL,
                input=[
                    {"role": "system", "content": EXTRACTION_INSTRUCTIONS},
                    {"role": "user", "content": email_text},
                ],
                text_format=QuoteRequestExtraction,
            )
        except Exception as exc:
            raise ExtractionError(f"OpenAI extraction call failed: {exc}") from exc

        parsed = response.output_parsed
        if parsed is None:
            raise ExtractionError("OpenAI response did not contain parsed output")
        return parsed
```

Create empty `backend/core/llm/__init__.py` and `backend/tests/app/intake/__init__.py`.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/core/test_openai_client.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/core/llm backend/app/intake/__init__.py backend/app/intake/schemas.py backend/tests/core/test_openai_client.py backend/tests/app/intake/__init__.py
git commit -m "feat: add OpenAI structured-extraction client and QuoteRequest schema"
```

---

### Task 6: Entity resolution

**Files:**
- Create: `backend/app/intake/resolution.py`
- Test: `backend/tests/app/intake/test_resolution.py`

**Interfaces:**
- Consumes: `app.reference_data.repository.all_customers`/`all_skus` (Task 3), `app.intake.schemas.QuoteRequestExtraction` (Task 5).
- Produces: `dataclass ResolvedLineItem(sku_name_as_written: str, sku_id: str | None, quantity: str | None)`; `dataclass IntakeResult(customer_id: str | None, site_id: str | None, line_items: list[ResolvedLineItem], extraction: QuoteRequestExtraction)`; `resolve_extraction(session, extraction: QuoteRequestExtraction) -> IntakeResult`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/app/intake/test_resolution.py
from app.intake.resolution import resolve_extraction
from app.intake.schemas import LineItemExtraction, QuoteRequestExtraction
from app.reference_data.repository import upsert_customer, upsert_sku


def _seed(db_session):
    upsert_customer(db_session, customer_id="CUST-A", name="Zenith Contractors", account_tier="Standard")
    upsert_customer(db_session, customer_id="CUST-B", name="Zenith Plumbing", account_tier="Standard")
    upsert_sku(db_session, sku_id="SKU-A", name="Chrome Sprayer Corner-Mount", category="C",
               list_price=1.0, discontinued=False, replaced_by=None, in_stock=True)
    db_session.flush()


def test_exact_match_resolves_customer_and_sku(db_session):
    _seed(db_session)
    extraction = QuoteRequestExtraction(
        customer_name_as_written="Zenith Contractors",
        line_items=[LineItemExtraction(sku_name_as_written="Chrome Sprayer Corner-Mount", quantity="4")],
        raw_text="text",
    )
    result = resolve_extraction(db_session, extraction)
    assert result.customer_id == "CUST-A"
    assert result.line_items[0].sku_id == "SKU-A"


def test_fuzzy_match_resolves_shorthand_name(db_session):
    upsert_customer(db_session, customer_id="CUST-C", name="Advanced Contractors Group", account_tier="Standard")
    db_session.flush()
    extraction = QuoteRequestExtraction(
        customer_name_as_written="Advanced Contractors Grp",
        line_items=[],
        raw_text="text",
    )
    result = resolve_extraction(db_session, extraction)
    assert result.customer_id == "CUST-C"


def test_ambiguous_name_tie_resolves_to_none(db_session):
    _seed(db_session)
    extraction = QuoteRequestExtraction(customer_name_as_written="Zenith", line_items=[], raw_text="text")
    result = resolve_extraction(db_session, extraction)
    assert result.customer_id is None


def test_unresolvable_sku_name_stays_unresolved_without_blocking_others(db_session):
    _seed(db_session)
    extraction = QuoteRequestExtraction(
        customer_name_as_written="Zenith Contractors",
        line_items=[
            LineItemExtraction(sku_name_as_written="Chrome Sprayer Corner-Mount", quantity="1"),
            LineItemExtraction(sku_name_as_written="Some Totally Unknown Part", quantity="1"),
        ],
        raw_text="text",
    )
    result = resolve_extraction(db_session, extraction)
    assert result.line_items[0].sku_id == "SKU-A"
    assert result.line_items[1].sku_id is None


def test_empty_line_items_resolves_to_empty_list(db_session):
    _seed(db_session)
    extraction = QuoteRequestExtraction(customer_name_as_written="Zenith Contractors", line_items=[], raw_text="text")
    result = resolve_extraction(db_session, extraction)
    assert result.line_items == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/app/intake/test_resolution.py -v`
Expected: FAIL with "No module named 'app.intake.resolution'"

- [ ] **Step 3: Write `backend/app/intake/resolution.py`**

```python
from dataclasses import dataclass

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from app.intake.schemas import QuoteRequestExtraction
from app.reference_data.repository import all_customers, all_skus

FUZZY_MATCH_THRESHOLD = 90


@dataclass
class ResolvedLineItem:
    sku_name_as_written: str
    sku_id: str | None
    quantity: str | None


@dataclass
class IntakeResult:
    customer_id: str | None
    site_id: str | None
    line_items: list[ResolvedLineItem]
    extraction: QuoteRequestExtraction


def _match_name(name: str, candidates: dict[str, str]) -> str | None:
    lowered = name.strip().lower()
    exact = [cid for cid, cname in candidates.items() if cname.strip().lower() == lowered]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return None

    scored = [(cid, fuzz.token_sort_ratio(lowered, cname.strip().lower())) for cid, cname in candidates.items()]
    above_threshold = [cid for cid, score in scored if score >= FUZZY_MATCH_THRESHOLD]
    if len(above_threshold) == 1:
        return above_threshold[0]
    return None


def resolve_extraction(session: Session, extraction: QuoteRequestExtraction) -> IntakeResult:
    customer_candidates = {c.customer_id: c.name for c in all_customers(session)}
    sku_candidates = {s.sku_id: s.name for s in all_skus(session)}

    customer_id = _match_name(extraction.customer_name_as_written, customer_candidates)
    line_items = [
        ResolvedLineItem(
            sku_name_as_written=item.sku_name_as_written,
            sku_id=_match_name(item.sku_name_as_written, sku_candidates),
            quantity=item.quantity,
        )
        for item in extraction.line_items
    ]
    return IntakeResult(customer_id=customer_id, site_id=None, line_items=line_items, extraction=extraction)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/app/intake/test_resolution.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/intake/resolution.py backend/tests/app/intake/test_resolution.py
git commit -m "feat: add entity resolution for extracted customer/SKU names"
```

---

### Task 7: Intake service and repository

**Files:**
- Create: `backend/app/intake/models.py`
- Create: `backend/app/intake/repository.py`
- Create: `backend/app/intake/service.py`
- Create: `backend/app/dedupe/__init__.py`
- Create: `backend/app/dedupe/fingerprints.py`
- Test: `backend/tests/app/intake/test_service.py`

**Interfaces:**
- Consumes: `app.intake.resolution.resolve_extraction` (Task 6), `app.reference_data.repository.contracts_for_customer` (Task 3), `core.llm.openai_client.OpenAIExtractionClient`/`ExtractionError` (Task 5), `core.db.base.Base` (Task 2).
- Produces: ORM class `QuoteRequestRow` (`app.intake.models`); `app.intake.repository.save_quote_request(session, *, raw_email_text, parsed_json, content_fingerprint, style_fingerprint, customer_id, site_id=None, contract_id=None, case_id=None) -> QuoteRequestRow`; `app.dedupe.fingerprints.normalize_style_tokens(text: str) -> set[str]` (used here and by Task 9); `dataclass ProcessEmailResult(row: QuoteRequestRow, resolved_line_items: list[ResolvedLineItem])`; `app.intake.service.process_email(session, email_text: str, llm_client: OpenAIExtractionClient, case_id: str | None = None) -> ProcessEmailResult`.

Note: `app.dedupe.fingerprints` is created in this task (just `normalize_style_tokens`, needed by the intake service to compute `style_fingerprint`) and extended in Task 9 with `jaccard`, `is_strict_superset`, and `classify`. Both tasks touch the same file; Task 9 adds to what this task starts, it does not replace it.

- [ ] **Step 1: Write `backend/app/dedupe/fingerprints.py`**

```python
import re

STOPWORDS = {"the", "a", "an", "and", "or", "to", "for", "of", "on", "in", "is", "we", "i", "please", "thanks", "hi", "hello"}


def normalize_style_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for line in text.lower().splitlines():
        for word in re.findall(r"[a-z0-9]+", line):
            if word not in STOPWORDS:
                tokens.add(word)
    return tokens
```

Create empty `backend/app/dedupe/__init__.py`.

- [ ] **Step 2: Write `backend/app/intake/models.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from core.db.base import Base


class QuoteRequestRow(Base):
    __tablename__ = "quote_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[str | None] = mapped_column(Text)
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.customer_id"))
    site_id: Mapped[str | None] = mapped_column(ForeignKey("sites.site_id"))
    contract_id: Mapped[str | None] = mapped_column(ForeignKey("contracts.contract_id"))
    raw_email_text: Mapped[str] = mapped_column(Text)
    parsed_json: Mapped[dict] = mapped_column(JSONB)
    content_fingerprint: Mapped[dict] = mapped_column(JSONB)
    style_fingerprint: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
```

- [ ] **Step 3: Write `backend/app/intake/repository.py`**

```python
import uuid

from sqlalchemy.orm import Session

from app.intake.models import QuoteRequestRow


def save_quote_request(
    session: Session, *, raw_email_text: str, parsed_json: dict, content_fingerprint: dict,
    style_fingerprint: dict, customer_id: str | None, site_id: str | None = None,
    contract_id: str | None = None, case_id: str | None = None,
) -> QuoteRequestRow:
    row = QuoteRequestRow(
        id=uuid.uuid4(), case_id=case_id, customer_id=customer_id, site_id=site_id,
        contract_id=contract_id, raw_email_text=raw_email_text, parsed_json=parsed_json,
        content_fingerprint=content_fingerprint, style_fingerprint=style_fingerprint,
    )
    session.add(row)
    session.flush()
    return row


def get_quote_request(session: Session, quote_request_id: uuid.UUID) -> QuoteRequestRow | None:
    return session.get(QuoteRequestRow, quote_request_id)
```

- [ ] **Step 4: Write the failing test**

```python
# backend/tests/app/intake/test_service.py
from unittest.mock import MagicMock

import pytest

from app.intake.schemas import LineItemExtraction, QuoteRequestExtraction
from app.intake.service import process_email
from app.reference_data.repository import upsert_customer, upsert_sku
from core.llm.openai_client import ExtractionError


def _seed(db_session):
    upsert_customer(db_session, customer_id="CUST-A", name="Zenith Contractors", account_tier="Standard")
    upsert_sku(db_session, sku_id="SKU-A", name="Chrome Sprayer Corner-Mount", category="C",
               list_price=1.0, discontinued=False, replaced_by=None, in_stock=True)
    db_session.flush()


def test_process_email_stores_resolved_quote_request(db_session):
    _seed(db_session)
    extraction = QuoteRequestExtraction(
        customer_name_as_written="Zenith Contractors",
        line_items=[LineItemExtraction(sku_name_as_written="Chrome Sprayer Corner-Mount", quantity="4")],
        raw_text="need 4",
    )
    fake_client = MagicMock()
    fake_client.extract_quote_request.return_value = extraction

    result = process_email(db_session, "need 4 sprayers", fake_client)

    assert result.row.customer_id == "CUST-A"
    assert result.row.content_fingerprint["sku_ids"] == ["SKU-A"]
    assert result.resolved_line_items[0].sku_id == "SKU-A"


def test_process_email_handles_zero_line_items(db_session):
    _seed(db_session)
    extraction = QuoteRequestExtraction(customer_name_as_written="Zenith Contractors", line_items=[], raw_text="just asking")
    fake_client = MagicMock()
    fake_client.extract_quote_request.return_value = extraction

    result = process_email(db_session, "just asking a question", fake_client)

    assert result.row.content_fingerprint["sku_ids"] == []
    assert result.resolved_line_items == []


def test_process_email_raises_and_stores_nothing_on_extraction_failure(db_session):
    _seed(db_session)
    fake_client = MagicMock()
    fake_client.extract_quote_request.side_effect = ExtractionError("boom")

    with pytest.raises(ExtractionError):
        process_email(db_session, "some email", fake_client)

    from sqlalchemy import select
    from app.intake.models import QuoteRequestRow
    assert db_session.scalars(select(QuoteRequestRow)).all() == []
```

- [ ] **Step 5: Run test to verify it fails**

Run: `uv run pytest tests/app/intake/test_service.py -v`
Expected: FAIL with "No module named 'app.intake.service'"

- [ ] **Step 6: Write `backend/app/intake/service.py`**

```python
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.dedupe.fingerprints import normalize_style_tokens
from app.intake.models import QuoteRequestRow
from app.intake.repository import save_quote_request
from app.intake.resolution import ResolvedLineItem, resolve_extraction
from app.reference_data.repository import contracts_for_customer
from core.llm.openai_client import OpenAIExtractionClient


@dataclass
class ProcessEmailResult:
    row: QuoteRequestRow
    resolved_line_items: list[ResolvedLineItem]


def process_email(
    session: Session, email_text: str, llm_client: OpenAIExtractionClient, case_id: str | None = None,
) -> ProcessEmailResult:
    extraction = llm_client.extract_quote_request(email_text)
    resolved = resolve_extraction(session, extraction)

    resolved_sku_ids = [item.sku_id for item in resolved.line_items if item.sku_id]
    content_fingerprint = {"sku_ids": sorted(set(resolved_sku_ids))}
    style_fingerprint = {"tokens": sorted(normalize_style_tokens(email_text))}

    contract_id = None
    if resolved.customer_id:
        contracts = contracts_for_customer(session, resolved.customer_id)
        if len(contracts) == 1:
            contract_id = contracts[0].contract_id

    row = save_quote_request(
        session, raw_email_text=email_text, parsed_json=extraction.model_dump(),
        content_fingerprint=content_fingerprint, style_fingerprint=style_fingerprint,
        customer_id=resolved.customer_id, site_id=resolved.site_id, contract_id=contract_id, case_id=case_id,
    )
    return ProcessEmailResult(row=row, resolved_line_items=resolved.line_items)
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/app/intake/test_service.py -v`
Expected: PASS (3 tests)

- [ ] **Step 8: Commit**

```bash
git add backend/app/intake/models.py backend/app/intake/repository.py backend/app/intake/service.py backend/app/dedupe/__init__.py backend/app/dedupe/fingerprints.py backend/tests/app/intake/test_service.py
git commit -m "feat: add intake service tying extraction, resolution, and storage together"
```

---

### Task 8: Intake API route

**Files:**
- Create: `backend/api/__init__.py`
- Create: `backend/api/v1/__init__.py`
- Create: `backend/api/v1/intake/__init__.py`
- Create: `backend/api/v1/intake/request.py`
- Create: `backend/api/v1/intake/response.py`
- Create: `backend/api/v1/intake/route.py`
- Test: `backend/tests/api/__init__.py`
- Test: `backend/tests/api/v1/__init__.py`
- Test: `backend/tests/api/v1/test_intake_route.py`

**Interfaces:**
- Consumes: `app.intake.service.process_email` (Task 7), `core.db.session.get_session` (Task 2), `core.llm.openai_client.OpenAIExtractionClient`/`ExtractionError` (Task 5).
- Produces: FastAPI `router` at `api.v1.intake.route` (mounted at prefix `/v1/intake`); `get_llm_client()` dependency provider (overridable in tests).

- [ ] **Step 1: Write `backend/api/v1/intake/request.py`**

```python
from pydantic import BaseModel


class IntakeRequest(BaseModel):
    email_text: str
```

- [ ] **Step 2: Write `backend/api/v1/intake/response.py`**

```python
import uuid

from pydantic import BaseModel


class LineItemResponse(BaseModel):
    sku_name_as_written: str
    sku_id: str | None
    quantity: str | None


class IntakeResponse(BaseModel):
    quote_request_id: uuid.UUID
    customer_id: str | None
    site_id: str | None
    contract_id: str | None
    line_items: list[LineItemResponse]
```

- [ ] **Step 3: Write the failing test**

```python
# backend/tests/api/v1/test_intake_route.py
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from api.v1.intake.route import get_llm_client, router
from app.intake.schemas import LineItemExtraction, QuoteRequestExtraction
from app.reference_data.repository import upsert_customer, upsert_sku
from core.db.session import get_session
from core.llm.openai_client import ExtractionError
from main import app


def _client_with_overrides(db_session, fake_llm_client):
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_llm_client] = lambda: fake_llm_client
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_submit_email_returns_resolved_quote_request(db_session):
    upsert_customer(db_session, customer_id="CUST-A", name="Zenith Contractors", account_tier="Standard")
    upsert_sku(db_session, sku_id="SKU-A", name="Chrome Sprayer Corner-Mount", category="C",
               list_price=1.0, discontinued=False, replaced_by=None, in_stock=True)
    db_session.flush()

    fake_llm_client = MagicMock()
    fake_llm_client.extract_quote_request.return_value = QuoteRequestExtraction(
        customer_name_as_written="Zenith Contractors",
        line_items=[LineItemExtraction(sku_name_as_written="Chrome Sprayer Corner-Mount", quantity="4")],
        raw_text="need 4",
    )

    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_llm_client] = lambda: fake_llm_client
    client = TestClient(app)
    try:
        response = client.post("/v1/intake", json={"email_text": "need 4 sprayers"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["customer_id"] == "CUST-A"
    assert body["line_items"][0]["sku_id"] == "SKU-A"


def test_submit_email_returns_502_on_extraction_failure(db_session):
    fake_llm_client = MagicMock()
    fake_llm_client.extract_quote_request.side_effect = ExtractionError("boom")

    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_llm_client] = lambda: fake_llm_client
    client = TestClient(app)
    try:
        response = client.post("/v1/intake", json={"email_text": "some email"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/api/v1/test_intake_route.py -v`
Expected: FAIL with "No module named 'main'" or "No module named 'api'"

- [ ] **Step 5: Write `backend/api/v1/intake/route.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.v1.intake.request import IntakeRequest
from api.v1.intake.response import IntakeResponse, LineItemResponse
from app.intake.service import process_email
from core.db.session import get_session
from core.llm.openai_client import ExtractionError, OpenAIExtractionClient

router = APIRouter(prefix="/v1/intake", tags=["intake"])


def get_llm_client() -> OpenAIExtractionClient:
    return OpenAIExtractionClient()


@router.post("", response_model=IntakeResponse)
def submit_email(
    body: IntakeRequest,
    session: Session = Depends(get_session),
    llm_client: OpenAIExtractionClient = Depends(get_llm_client),
) -> IntakeResponse:
    try:
        result = process_email(session, body.email_text, llm_client)
    except ExtractionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return IntakeResponse(
        quote_request_id=result.row.id,
        customer_id=result.row.customer_id,
        site_id=result.row.site_id,
        contract_id=result.row.contract_id,
        line_items=[
            LineItemResponse(sku_name_as_written=li.sku_name_as_written, sku_id=li.sku_id, quantity=li.quantity)
            for li in result.resolved_line_items
        ],
    )
```

Create empty `backend/api/__init__.py`, `backend/api/v1/__init__.py`, `backend/api/v1/intake/__init__.py`, `backend/tests/api/__init__.py`, `backend/tests/api/v1/__init__.py`.

- [ ] **Step 6: Write a minimal `backend/main.py` so the route is mountable (fuller wiring happens in Task 12)**

```python
from fastapi import FastAPI

from api.v1.intake.route import router as intake_router

app = FastAPI(title="Estimate Analysis Backend")
app.include_router(intake_router)
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/api/v1/test_intake_route.py -v`
Expected: PASS (2 tests)

- [ ] **Step 8: Commit**

```bash
git add backend/api backend/main.py backend/tests/api
git commit -m "feat: add intake API route"
```

---

### Task 9: Dedupe fingerprint math and classifier

**Files:**
- Modify: `backend/app/dedupe/fingerprints.py`
- Test: `backend/tests/app/dedupe/__init__.py`
- Test: `backend/tests/app/dedupe/test_fingerprints.py`

**Interfaces:**
- Consumes: nothing beyond the stdlib; pure functions.
- Produces (added to the existing `app.dedupe.fingerprints` module from Task 7): `jaccard(a: set[str], b: set[str]) -> float`; `is_strict_superset(bigger: set[str], smaller: set[str]) -> bool`; `CONTENT_SUPERSET_FLOOR = 0.4`; `classify(sku_ids_a: set[str], sku_ids_b: set[str]) -> tuple[str, float, list[str]]` (returns `(verdict, content_jaccard, signals)` where `verdict` is one of `"DUPLICATE_OF"`, `"REVISION_OF"`, `"DISTINCT"`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/app/dedupe/test_fingerprints.py
from app.dedupe.fingerprints import classify, is_strict_superset, jaccard


def test_jaccard_identical_sets_is_one():
    assert jaccard({"A", "B"}, {"A", "B"}) == 1.0


def test_jaccard_disjoint_sets_is_zero():
    assert jaccard({"A"}, {"B"}) == 0.0


def test_jaccard_both_empty_is_zero():
    assert jaccard(set(), set()) == 0.0


def test_is_strict_superset_true_case():
    assert is_strict_superset({"A", "B", "C"}, {"A", "B"}) is True


def test_is_strict_superset_false_when_equal():
    assert is_strict_superset({"A", "B"}, {"A", "B"}) is False


def test_is_strict_superset_false_when_smaller_is_empty():
    # An empty set is never treated as a meaningful subset of anything --
    # an unresolved request must never be read as a "revision" of every other request.
    assert is_strict_superset({"A", "B"}, set()) is False


def test_classify_identical_sets_is_duplicate():
    verdict, score, signals = classify({"A", "B"}, {"A", "B"})
    assert verdict == "DUPLICATE_OF"
    assert score == 1.0
    assert "identical_sku_set" in signals


def test_classify_superset_above_floor_is_revision():
    verdict, score, signals = classify({"A", "B"}, {"A", "B", "C"})
    assert verdict == "REVISION_OF"
    assert score == 2 / 3
    assert "superset_relation" in signals


def test_classify_superset_below_floor_is_distinct():
    # sharing one SKU out of five is not a "revision" of a much larger, unrelated order
    verdict, score, signals = classify({"A"}, {"A", "B", "C", "D", "E"})
    assert verdict == "DISTINCT"


def test_classify_disjoint_sets_is_distinct():
    verdict, score, signals = classify({"A"}, {"B"})
    assert verdict == "DISTINCT"
    assert score == 0.0


def test_classify_two_empty_sets_is_distinct_not_duplicate():
    # Two unresolved requests must not be flagged as duplicates of each other.
    verdict, score, signals = classify(set(), set())
    assert verdict == "DISTINCT"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/app/dedupe/test_fingerprints.py -v`
Expected: FAIL with "cannot import name 'jaccard'"

- [ ] **Step 3: Add to `backend/app/dedupe/fingerprints.py`** (append below the existing `normalize_style_tokens` from Task 7; do not remove it)

```python
CONTENT_SUPERSET_FLOOR = 0.4


def jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def is_strict_superset(bigger: set[str], smaller: set[str]) -> bool:
    return bool(smaller) and smaller < bigger


def classify(sku_ids_a: set[str], sku_ids_b: set[str]) -> tuple[str, float, list[str]]:
    score = jaccard(sku_ids_a, sku_ids_b)

    if score == 1.0 and sku_ids_a:
        return "DUPLICATE_OF", score, ["identical_sku_set"]

    if is_strict_superset(sku_ids_a, sku_ids_b) or is_strict_superset(sku_ids_b, sku_ids_a):
        if score >= CONTENT_SUPERSET_FLOOR:
            return "REVISION_OF", score, ["superset_relation"]

    return "DISTINCT", score, []
```

Create empty `backend/tests/app/dedupe/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/app/dedupe/test_fingerprints.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/dedupe/fingerprints.py backend/tests/app/dedupe
git commit -m "feat: add dedupe fingerprint math and classifier"
```

---

### Task 10: Dedupe repository and service

**Files:**
- Create: `backend/app/dedupe/models.py`
- Create: `backend/app/dedupe/repository.py`
- Create: `backend/app/dedupe/service.py`
- Modify: `backend/migrations/env.py:9-13` (uncomment the three model imports now that Tasks 3, 7, and 10 all exist)
- Test: `backend/tests/app/dedupe/test_service.py`

**Interfaces:**
- Consumes: `app.intake.models.QuoteRequestRow` (Task 7), `app.dedupe.fingerprints.classify`/`jaccard` (Task 9).
- Produces: ORM class `DedupeVerdictRow` (`app.dedupe.models`); `app.dedupe.repository.find_blocked_candidates(session, target: QuoteRequestRow) -> list[QuoteRequestRow]`, `app.dedupe.repository.save_verdict(session, *, quote_request_id, candidate_quote_request_id, verdict, content_jaccard, style_jaccard, signals_fired) -> DedupeVerdictRow`; `app.dedupe.service.run_dedupe(session, quote_request_id: uuid.UUID) -> list[DedupeVerdictRow]`.

- [ ] **Step 1: Write `backend/app/dedupe/models.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import Float, ForeignKey, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from core.db.base import Base


class DedupeVerdictRow(Base):
    __tablename__ = "dedupe_verdicts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quote_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quote_requests.id"))
    candidate_quote_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quote_requests.id"))
    verdict: Mapped[str] = mapped_column(Text)
    content_jaccard: Mapped[float] = mapped_column(Float)
    style_jaccard: Mapped[float] = mapped_column(Float)
    signals_fired: Mapped[list[str]] = mapped_column(ARRAY(Text))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
```

- [ ] **Step 2: Write `backend/app/dedupe/repository.py`**

```python
import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.dedupe.models import DedupeVerdictRow
from app.intake.models import QuoteRequestRow


def find_blocked_candidates(session: Session, target: QuoteRequestRow) -> list[QuoteRequestRow]:
    conditions = []
    if target.customer_id:
        conditions.append(QuoteRequestRow.customer_id == target.customer_id)
    if target.site_id:
        conditions.append(QuoteRequestRow.site_id == target.site_id)
    if target.contract_id:
        conditions.append(QuoteRequestRow.contract_id == target.contract_id)

    if not conditions:
        return []

    stmt = select(QuoteRequestRow).where(or_(*conditions), QuoteRequestRow.id != target.id)
    return list(session.scalars(stmt))


def save_verdict(
    session: Session, *, quote_request_id: uuid.UUID, candidate_quote_request_id: uuid.UUID,
    verdict: str, content_jaccard: float, style_jaccard: float, signals_fired: list[str],
) -> DedupeVerdictRow:
    row = DedupeVerdictRow(
        id=uuid.uuid4(), quote_request_id=quote_request_id,
        candidate_quote_request_id=candidate_quote_request_id, verdict=verdict,
        content_jaccard=content_jaccard, style_jaccard=style_jaccard, signals_fired=signals_fired,
    )
    session.add(row)
    session.flush()
    return row
```

- [ ] **Step 3: Write the failing test**

```python
# backend/tests/app/dedupe/test_service.py
import uuid

from app.dedupe.service import run_dedupe
from app.intake.repository import save_quote_request


def _make_request(db_session, customer_id, site_id, sku_ids, raw_text="text"):
    return save_quote_request(
        db_session, raw_email_text=raw_text, parsed_json={},
        content_fingerprint={"sku_ids": sku_ids}, style_fingerprint={"tokens": []},
        customer_id=customer_id, site_id=site_id,
    )


def test_run_dedupe_flags_identical_sku_set_as_duplicate(db_session):
    first = _make_request(db_session, "CUST-A", "SITE-A", ["SKU-A", "SKU-B"])
    second = _make_request(db_session, "CUST-A", "SITE-A", ["SKU-A", "SKU-B"])
    db_session.flush()

    verdicts = run_dedupe(db_session, second.id)
    assert len(verdicts) == 1
    assert verdicts[0].candidate_quote_request_id == first.id
    assert verdicts[0].verdict == "DUPLICATE_OF"


def test_run_dedupe_flags_superset_as_revision(db_session):
    original = _make_request(db_session, "CUST-A", "SITE-A", ["SKU-A"])
    revision = _make_request(db_session, "CUST-A", "SITE-A", ["SKU-A", "SKU-B"])
    db_session.flush()

    verdicts = run_dedupe(db_session, revision.id)
    assert verdicts[0].verdict == "REVISION_OF"


def test_run_dedupe_excludes_the_target_itself_from_candidates(db_session):
    only_request = _make_request(db_session, "CUST-A", "SITE-A", ["SKU-A"])
    db_session.flush()

    verdicts = run_dedupe(db_session, only_request.id)
    assert verdicts == []


def test_run_dedupe_unresolved_customer_and_site_yields_no_candidates(db_session):
    request = _make_request(db_session, None, None, [])
    db_session.flush()

    verdicts = run_dedupe(db_session, request.id)
    assert verdicts == []


def test_run_dedupe_raises_for_unknown_quote_request(db_session):
    import pytest
    with pytest.raises(ValueError):
        run_dedupe(db_session, uuid.uuid4())
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/app/dedupe/test_service.py -v`
Expected: FAIL with "No module named 'app.dedupe.service'"

- [ ] **Step 5: Write `backend/app/dedupe/service.py`**

```python
import uuid

from sqlalchemy.orm import Session

from app.dedupe.fingerprints import classify, jaccard
from app.dedupe.models import DedupeVerdictRow
from app.dedupe.repository import find_blocked_candidates, save_verdict
from app.intake.models import QuoteRequestRow


def _blocking_signals(target: QuoteRequestRow, candidate: QuoteRequestRow) -> list[str]:
    signals = []
    if target.customer_id and target.customer_id == candidate.customer_id:
        signals.append("same_customer")
    if target.site_id and target.site_id == candidate.site_id:
        signals.append("same_site")
    if target.contract_id and target.contract_id == candidate.contract_id:
        signals.append("same_contract")
    return signals


def run_dedupe(session: Session, quote_request_id: uuid.UUID) -> list[DedupeVerdictRow]:
    target = session.get(QuoteRequestRow, quote_request_id)
    if target is None:
        raise ValueError(f"quote_request {quote_request_id} not found")

    candidates = find_blocked_candidates(session, target)
    verdicts: list[DedupeVerdictRow] = []

    target_sku_ids = set(target.content_fingerprint.get("sku_ids", []))
    target_tokens = set(target.style_fingerprint.get("tokens", []))

    for candidate in candidates:
        candidate_sku_ids = set(candidate.content_fingerprint.get("sku_ids", []))
        candidate_tokens = set(candidate.style_fingerprint.get("tokens", []))

        verdict, content_score, content_signals = classify(target_sku_ids, candidate_sku_ids)
        style_score = jaccard(target_tokens, candidate_tokens)
        signals = _blocking_signals(target, candidate) + content_signals

        row = save_verdict(
            session, quote_request_id=target.id, candidate_quote_request_id=candidate.id,
            verdict=verdict, content_jaccard=content_score, style_jaccard=style_score, signals_fired=signals,
        )
        verdicts.append(row)

    return verdicts
```

- [ ] **Step 6: Uncomment the model imports in `backend/migrations/env.py`**

```python
from app.reference_data import models as reference_data_models  # noqa: F401
from app.intake import models as intake_models  # noqa: F401
from app.dedupe import models as dedupe_models  # noqa: F401
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/app/dedupe/test_service.py -v`
Expected: PASS (5 tests)

- [ ] **Step 8: Commit**

```bash
git add backend/app/dedupe/models.py backend/app/dedupe/repository.py backend/app/dedupe/service.py backend/migrations/env.py backend/tests/app/dedupe/test_service.py
git commit -m "feat: add dedupe blocking, service, and verdict persistence"
```

---

### Task 11: Dedupe API route

**Files:**
- Create: `backend/api/v1/dedupe/__init__.py`
- Create: `backend/api/v1/dedupe/response.py`
- Create: `backend/api/v1/dedupe/route.py`
- Test: `backend/tests/api/v1/test_dedupe_route.py`

**Interfaces:**
- Consumes: `app.dedupe.service.run_dedupe` (Task 10), `core.db.session.get_session` (Task 2).
- Produces: FastAPI `router` at `api.v1.dedupe.route` (mounted at prefix `/v1/dedupe`).

- [ ] **Step 1: Write `backend/api/v1/dedupe/response.py`**

```python
import uuid

from pydantic import BaseModel


class DedupeVerdictResponse(BaseModel):
    candidate_quote_request_id: uuid.UUID
    verdict: str
    content_jaccard: float
    style_jaccard: float
    signals_fired: list[str]


class DedupeResponse(BaseModel):
    quote_request_id: uuid.UUID
    verdicts: list[DedupeVerdictResponse]
```

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/api/v1/test_dedupe_route.py
import uuid

from fastapi.testclient import TestClient

from app.intake.repository import save_quote_request
from core.db.session import get_session
from main import app


def test_dedupe_endpoint_returns_duplicate_verdict(db_session):
    first = save_quote_request(
        db_session, raw_email_text="t1", parsed_json={}, content_fingerprint={"sku_ids": ["SKU-A"]},
        style_fingerprint={"tokens": []}, customer_id="CUST-A", site_id="SITE-A",
    )
    second = save_quote_request(
        db_session, raw_email_text="t2", parsed_json={}, content_fingerprint={"sku_ids": ["SKU-A"]},
        style_fingerprint={"tokens": []}, customer_id="CUST-A", site_id="SITE-A",
    )
    db_session.flush()

    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    try:
        response = client.post(f"/v1/dedupe/{second.id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["verdicts"][0]["candidate_quote_request_id"] == str(first.id)
    assert body["verdicts"][0]["verdict"] == "DUPLICATE_OF"


def test_dedupe_endpoint_returns_404_for_unknown_id(db_session):
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    try:
        response = client.post(f"/v1/dedupe/{uuid.uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/api/v1/test_dedupe_route.py -v`
Expected: FAIL with "404 Not Found" for the first test (route not yet mounted) or import error

- [ ] **Step 4: Write `backend/api/v1/dedupe/route.py`**

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.v1.dedupe.response import DedupeResponse, DedupeVerdictResponse
from app.dedupe.service import run_dedupe
from core.db.session import get_session

router = APIRouter(prefix="/v1/dedupe", tags=["dedupe"])


@router.post("/{quote_request_id}", response_model=DedupeResponse)
def dedupe_quote_request(quote_request_id: uuid.UUID, session: Session = Depends(get_session)) -> DedupeResponse:
    try:
        verdicts = run_dedupe(session, quote_request_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return DedupeResponse(
        quote_request_id=quote_request_id,
        verdicts=[
            DedupeVerdictResponse(
                candidate_quote_request_id=v.candidate_quote_request_id, verdict=v.verdict,
                content_jaccard=v.content_jaccard, style_jaccard=v.style_jaccard, signals_fired=v.signals_fired,
            )
            for v in verdicts
        ],
    )
```

Create empty `backend/api/v1/dedupe/__init__.py`.

- [ ] **Step 5: Mount the dedupe router in `backend/main.py`**

```python
from fastapi import FastAPI

from api.v1.dedupe.route import router as dedupe_router
from api.v1.intake.route import router as intake_router

app = FastAPI(title="Estimate Analysis Backend")
app.include_router(intake_router)
app.include_router(dedupe_router)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/api/v1/test_dedupe_route.py -v`
Expected: PASS (2 tests)

- [ ] **Step 7: Commit**

```bash
git add backend/api/v1/dedupe backend/main.py backend/tests/api/v1/test_dedupe_route.py
git commit -m "feat: add dedupe API route"
```

---

### Task 12: App entrypoint wiring and README

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/README.md`

**Interfaces:**
- Consumes: `app` (FastAPI instance from Task 11's `main.py`).
- Produces: a runnable `uvicorn` entrypoint via `python main.py`.

- [ ] **Step 1: Finalize `backend/main.py`**

```python
from fastapi import FastAPI

from api.v1.dedupe.route import router as dedupe_router
from api.v1.intake.route import router as intake_router

app = FastAPI(title="Estimate Analysis Backend")
app.include_router(intake_router)
app.include_router(dedupe_router)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the full test suite to confirm nothing broke**

Run: `uv run pytest -v`
Expected: all tests pass (Postgres running per Prerequisites)

- [ ] **Step 3: Update `backend/README.md`** (append a Phase 2 section; keep Phase 1's existing content)

```markdown
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
```

- [ ] **Step 4: Commit**

```bash
git add backend/main.py backend/README.md
git commit -m "feat: wire up FastAPI entrypoint and document Phase 2 setup"
```

---

### Task 13: Acceptance test against Phase 1's real scenario set

**Files:**
- Test: `backend/tests/test_phase2_acceptance.py`

**Interfaces:**
- Consumes: `app.reference_data.repository` (Task 3), `app.intake.repository.save_quote_request` (Task 7), `app.dedupe.service.run_dedupe` (Task 10), the real committed `backend/data/{catalog,customers,scenarios}.json`.
- Produces: nothing consumed by later tasks; this is the plan's final verification of the spec's done-when criterion.

- [ ] **Step 1: Write `backend/tests/test_phase2_acceptance.py`**

```python
import json
from datetime import date
from pathlib import Path

from app.intake.repository import save_quote_request
from app.reference_data.models import Sku
from app.reference_data.repository import upsert_contract, upsert_customer, upsert_site, upsert_sku
from app.dedupe.service import run_dedupe

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _load_reference_data(session):
    catalog = json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
    customers = json.loads((DATA_DIR / "customers.json").read_text(encoding="utf-8"))

    for sku in catalog:
        upsert_sku(
            session, sku_id=sku["sku_id"], name=sku["name"], category=sku["category"],
            list_price=sku["list_price"], discontinued=sku["discontinued"], replaced_by=None,
            in_stock=sku["in_stock"],
        )
    session.flush()
    for sku in catalog:
        if sku["discontinued"] and sku["replaced_by"]:
            session.get(Sku, sku["sku_id"]).replaced_by = sku["replaced_by"]

    for customer in customers:
        upsert_customer(session, customer_id=customer["customer_id"], name=customer["name"], account_tier=customer["account_tier"])
        for site in customer["sites"]:
            upsert_site(session, site_id=site["site_id"], customer_id=customer["customer_id"], address=site["address"], zip_code=site["zip"])
        for contract in customer["contracts"]:
            upsert_contract(
                session, contract_id=contract["contract_id"], customer_id=customer["customer_id"],
                discount_category=contract["discount_category"], covered_categories=contract["covered_categories"],
                effective_from=date.fromisoformat(contract["effective_from"]),
                effective_to=date.fromisoformat(contract["effective_to"]),
            )
    session.flush()


def _insert_quote_request(session, case: dict):
    entities = case["entities"]
    if "sku_ids" in entities:
        sku_ids = entities["sku_ids"]
    elif "sku_id" in entities:
        sku_ids = [entities["sku_id"]]
    else:
        sku_ids = []

    return save_quote_request(
        session, raw_email_text=case["email_text"], parsed_json={"case_id": case["case_id"]},
        content_fingerprint={"sku_ids": sorted(set(sku_ids))}, style_fingerprint={"tokens": []},
        customer_id=entities["customer_id"], site_id=entities.get("site_id"), case_id=case["case_id"],
    )


def test_dedupe_classifier_matches_phase1_ground_truth(db_session):
    _load_reference_data(db_session)
    scenarios = json.loads((DATA_DIR / "scenarios.json").read_text(encoding="utf-8"))

    rows_by_case_id = {}
    for case in scenarios:
        rows_by_case_id[case["case_id"]] = _insert_quote_request(db_session, case)
    db_session.flush()

    duplicate_pairs: dict[str, list[str]] = {}
    revision_pairs: dict[str, list[str]] = {}
    for case in scenarios:
        pair_id = case["entities"].get("pair_id")
        if not pair_id:
            continue
        target = duplicate_pairs if case["scenario_type"] == "duplicate_pair" else revision_pairs
        target.setdefault(pair_id, []).append(case["case_id"])

    for case_ids in duplicate_pairs.values():
        assert len(case_ids) == 2
        second_row = rows_by_case_id[case_ids[1]]
        verdicts = run_dedupe(db_session, second_row.id)
        matched = [v for v in verdicts if v.candidate_quote_request_id == rows_by_case_id[case_ids[0]].id]
        assert len(matched) == 1
        assert matched[0].verdict == "DUPLICATE_OF"

    for case_ids in revision_pairs.values():
        assert len(case_ids) == 2
        revision_row = rows_by_case_id[case_ids[1]]
        verdicts = run_dedupe(db_session, revision_row.id)
        matched = [v for v in verdicts if v.candidate_quote_request_id == rows_by_case_id[case_ids[0]].id]
        assert len(matched) == 1
        assert matched[0].verdict == "REVISION_OF"

    clean_distinct_cases = [c for c in scenarios if c["scenario_type"] == "clean_distinct"]
    for case in clean_distinct_cases:
        row = rows_by_case_id[case["case_id"]]
        verdicts = run_dedupe(db_session, row.id)
        assert all(v.verdict == "DISTINCT" for v in verdicts)
```

- [ ] **Step 2: Run test to verify it passes**

Run: `uv run pytest tests/test_phase2_acceptance.py -v`
Expected: PASS. This is the direct test of the spec's done-when criterion: all 5 planted `duplicate_pair`s classify as `DUPLICATE_OF`, all 5 planted `revision_pair`s classify as `REVISION_OF`, and all 10 `clean_distinct` cases produce no false `DUPLICATE_OF`/`REVISION_OF` verdicts.

- [ ] **Step 3: Run the entire suite one more time**

Run: `uv run pytest -v`
Expected: all tests across both phases pass.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_phase2_acceptance.py
git commit -m "test: add Phase 2 acceptance test against Phase 1's real scenario set"
```
