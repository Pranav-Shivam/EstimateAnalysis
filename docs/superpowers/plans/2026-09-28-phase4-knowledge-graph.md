# Phase 4 Knowledge Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Phase 3 agent a Neo4j knowledge graph (the article's 10 nodes and 15 edges) so it resolves discontinued swaps, missing required parts and wrong-category discounts by graph traversal, with code guardrails that fail closed, plus Leiden communities, local and global query modes, and a hybrid SQL/graph/vector router.

**Architecture:** Postgres stays authoritative. `app/graph/` builds a namespaced, rebuildable Neo4j projection from Postgres (plus best-effort incremental sync of runtime entities). The agent reads it through an injected `GraphReader`; a new `graph_integrity` guardrail anchored on intake-resolved SKUs checks it and fails closed when the graph is unreachable or stale. `app/retrieval/` holds the rule-based router, the pgvector arm and the community-summary cache.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2 (autoflush off), Alembic, LangGraph, Neo4j 2026.09 Community + GDS 2026.09 (Docker), `neo4j` driver, Postgres 18 + pgvector 0.8.6, OpenAI (embeddings and summaries, behind gates), pytest.

**Spec:** `docs/superpowers/specs/2026-09-28-phase4-knowledge-graph-design.md`. Read it first; this plan implements it. Two deliberate refinements of the spec, both made while planning:
1. `structure_gen.py` uses no RNG (families come from the SKU name stem, one project per site), so it has no seed offset. The output is still fully deterministic.
2. `VARIANT_MIN_JACCARD = 0.2`. The dev `dedupe_verdicts` table is empty, so the value comes from the classifier's own floor: `CONTENT_SUPERSET_FLOOR` is 0.4 (revisions), and a same-customer `DISTINCT` pair with a non-superset overlap of at least 0.2 is a variant.

## Global Constraints

- Postgres is on host port **5433**, never 5432. Neo4j is on host ports **17474** (HTTP) and **17687** (Bolt), never 7474/7687. Neo4j image is pinned to `neo4j:2026.09.0-community`, never `latest`.
- **No em dash character anywhere** (code, comments, tests, docs, commit messages). No emojis.
- **No AI attribution in commits**: never `Co-Authored-By`, never "Generated with", never mention Claude or Anthropic. This repo rule overrides any default. Write commit messages as a human would (`feat: ...`, `fix: ...`, `test: ...`, `docs: ...`).
- Stage files by explicit path only (`git add path1 path2`). Never `git add -A` or `git add .`. Never read, edit or commit `backend/.env`.
- SQLAlchemy sessions run with **autoflush off**: `session.flush()` before reading a row you just added.
- Layering: route to service to repository to DB/LLM (`docs/backend-structure.txt`). No dead code, no silent TODOs, comments only where the reason is not obvious, matching the density of surrounding code.
- **No real OpenAI or other paid API call, ever, in tests or during the build.** Fakes only. The embedding and summary scripts are dry runs by default and only call an API with `--yes`; no agent or reviewer runs them with `--yes`.
- Tests must not assert absolute row or node counts against shared databases (the dev Postgres holds the real dataset; the dev Neo4j may hold the `main` graph). Assert only on ids the test created. Graph tests use the autouse `graph_ns` fixture (a unique `test-<hex>` namespace per test, dropped on teardown). Nothing in tests or code under test may write namespace `main`.
- If Neo4j is unreachable, graph tests must fail loudly with the start command. No silent skips.
- Fail closed: a graph-backed guardrail that cannot reach the graph, or finds it stale, ends the run `needs_review`. It never skips silently and never reaches `ready`.
- Guardrails anchor on data the LLM did not write. The SQL `contract_discount` guardrail stays the sole discount authority; `check_contract_coverage` is advisory.
- Run tests from `backend/` with the env inline (the worktree has no `.env`). Neo4j must be running (`docker start neo4j-estimate`):
  `DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5433/estimate_analysis OPENAI_API_KEY=unused .venv/Scripts/python.exe -m pytest <path> -v`
  Alembic likewise: `DATABASE_URL=... OPENAI_API_KEY=unused .venv/Scripts/python.exe -m alembic upgrade head`. In a fresh worktree run `uv sync` in `backend/` first.
- `rm -rf` is blocked by a hook; use `git worktree remove` for worktrees.
- Baseline before this plan: 274 tests pass on master.

## Review Focus

The spec implies these inputs but no task's main tests centre on them. Each has a test in the owning task, marked "(Review Focus)".

1. **Graph down or stale mid-flight.** Neo4j stopping between the freshness check and a later submission, or Postgres reference data changing after the graph was built. Expected: the run ends `needs_review` with a reason, never `ready`, never an exception to the caller. (Task 12)
2. **Replacement chains that cannot resolve.** A cycle (A replaced by B replaced by A), a chain deeper than the 10-hop bound, a discontinued SKU with no replacement. Expected: terminates, treated as unreplaceable, run ends `needs_review` immediately without burning retries. (Task 5, Task 12)
3. **Local query on odd centres.** Centre is a hub (a pricing category with more members than the cap), an id that does not exist, an id that exists only in another namespace, `hops` of 0 or 99. Expected: hub returns the capped node list with `truncated` true; unknown or foreign ids raise `NodeNotFound`; hops are clamped to 1..2. (Task 7)
4. **Router inputs.** Lowercase ids (`sku-0001`), empty or whitespace questions, a question that matches several rules (portfolio phrasing plus an id), an id prefix with no SQL lookup (`SITE-`). Expected: ids normalise to uppercase, empty text falls to SQL name search with empty evidence (and the API rejects it with 422), precedence is portfolio then similarity then id plus relationship then id then name. (Task 10)
5. **Sync edge cases.** A quote whose `draft` is SQL NULL (agent never submitted), the same draft synced twice, two drafts for one request with identical `created_at`, a dedupe verdict whose candidate has a different customer. Expected: Quote node only for the null draft; idempotent edges; SUPERSEDES only for a strictly earlier draft; no VARIANT_OF across customers. (Task 6)

## File Structure

New:
- `backend/core/graph/{__init__,client}.py`: driver wrapper, typed errors, cached client, namespace getter.
- `backend/scripts/data_gen/structure_gen.py`: product families and projects.
- `backend/data/structure.json`: generated, committed like `pricing.json`.
- `backend/migrations/versions/0004_graph_structure_and_retrieval.py`
- `backend/app/graph/{__init__,constant,schemas,helper,repository,reader,service}.py`
- `backend/app/retrieval/{__init__,models,router,vector,summarizer,service}.py`
- `backend/app/reference_data/search.py`: fuzzy SKU and customer search extracted from `tools.py`.
- `backend/core/llm/{openai_embedding_client,openai_summary_client}.py`
- `backend/api/v1/retrieval/{__init__,request,response,route}.py`, `backend/api/v1/graph/{__init__,response,route}.py`
- `backend/scripts/{embed_skus,summarize_communities}.py`
- Tests: `tests/graph_support.py`, `tests/core/test_graph_client.py`, `tests/data_gen/test_structure_gen.py`, `tests/data_gen/test_validate_structure.py`, `tests/app/reference_data/test_structure_models.py`, `tests/app/graph/{__init__,test_helper,test_rebuild,test_reader,test_sync,test_communities}.py`, `tests/app/retrieval/{__init__,test_router,test_vector,test_summarizer,test_service}.py`, `tests/core/test_openai_embedding_client.py`, `tests/core/test_openai_summary_client.py`, `tests/app/estimate/test_graph_tools.py`, `tests/app/estimate/test_graph_integrity.py`, `tests/api/v1/test_retrieval_route.py`, `tests/api/v1/test_graph_route.py`, `tests/test_phase4_acceptance.py`.

Modified: `backend/pyproject.toml`, `uv.lock`, `core/config/settings.py`, `.env.example`, `docker-compose.yml`, `migrations/env.py`, `app/reference_data/{models,repository}.py`, `app/intake/repository.py`, `app/dedupe/repository.py`, `app/estimate/{repository,tools,guardrails,graph,service,prompts}.py`, `api/v1/{intake,dedupe,estimate}/route.py`, `main.py`, `scripts/load_data.py`, `scripts/data_gen/validate.py`, `tests/conftest.py`, and the existing estimate tests listed in Tasks 11 and 12.

---

### Task 1: Foundations (dependencies, settings, compose, graph client, test fixtures)

**Files:**
- Modify: `backend/pyproject.toml`, `backend/uv.lock` (via `uv add`), `backend/core/config/settings.py`, `backend/.env.example`, `docker-compose.yml`, `backend/tests/conftest.py`, `backend/tests/core/test_settings.py`
- Create: `backend/core/graph/__init__.py` (empty), `backend/core/graph/client.py`, `backend/tests/core/test_graph_client.py`

**Interfaces:**
- Produces: `core.graph.client.GraphClient(uri, user, password)` with `.read(query, **params) -> list[dict]`, `.write(query, **params) -> list[dict]`, `.close()`; `GraphError`, `GraphUnavailable(GraphError)`, `GraphQueryFailed(GraphError)`; `get_graph_client() -> GraphClient` (`lru_cache`); `get_graph_namespace() -> str`. `Settings.neo4j_uri/neo4j_user/neo4j_password/graph_namespace`. Fixtures `graph_ns` (autouse, str) and `graph_client` in `tests/conftest.py`.

- [ ] **Step 1: Add dependencies and check they import**

Run from `backend/`: `uv add neo4j pgvector` then `.venv/Scripts/python.exe -c "import neo4j, pgvector; print(neo4j.__version__)"`. Expected: a version prints. (The worktree needs `uv sync` first.)

- [ ] **Step 2: Write the failing settings tests**

Append to `backend/tests/core/test_settings.py`:

```python
def test_graph_settings_have_dev_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5433/db")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    for name in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "GRAPH_NAMESPACE"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.neo4j_uri == "bolt://localhost:17687"
    assert settings.neo4j_user == "neo4j"
    assert settings.neo4j_password == "neo4j-dev-password"
    assert settings.graph_namespace == "main"


def test_graph_settings_can_be_overridden_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5433/db")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("NEO4J_URI", "bolt://example.invalid:1")
    monkeypatch.setenv("GRAPH_NAMESPACE", "other")

    settings = Settings(_env_file=None)

    assert settings.neo4j_uri == "bolt://example.invalid:1"
    assert settings.graph_namespace == "other"
```

- [ ] **Step 3: Run to verify failure**

Run: `pytest tests/core/test_settings.py -v`. Expected: the two new tests FAIL with `AttributeError` (fields missing).

- [ ] **Step 4: Implement settings**

Replace `backend/core/config/settings.py` body:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    openai_api_key: str
    # Dev defaults match docker-compose.yml. Host port 17687 avoids the Neo4j default and local collisions.
    neo4j_uri: str = "bolt://localhost:17687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j-dev-password"
    # Every graph node carries its namespace, so tests share one Neo4j without touching the real graph.
    graph_namespace: str = "main"
```

Append to `backend/.env.example`:

```
NEO4J_URI=bolt://localhost:17687
NEO4J_USER=neo4j
NEO4J_PASSWORD=neo4j-dev-password
GRAPH_NAMESPACE=main
```

- [ ] **Step 5: Add the compose service**

In `docker-compose.yml` add under `services:` (after `postgres`) and under `volumes:`:

```yaml
  neo4j:
    image: neo4j:2026.09.0-community
    container_name: neo4j-estimate
    restart: unless-stopped
    environment:
      NEO4J_AUTH: neo4j/neo4j-dev-password
      NEO4J_PLUGINS: '["graph-data-science"]'
    ports:
      - "17474:7474"
      - "17687:7687"
    volumes:
      - neo4j_estimate_data:/data
```

```yaml
volumes:
  postgres_data:
  neo4j_estimate_data:
    name: neo4j_estimate_data
```

(The `name:` reuses the volume the owner already created with `docker run`. If a container named `neo4j-estimate` is already running from that `docker run`, `docker rm -f neo4j-estimate` before `docker compose up -d neo4j`. Do not run compose in this task; the container is already up.)

- [ ] **Step 6: Write the failing client tests and fixtures**

Append to `backend/tests/conftest.py` (add the imports at the top of the file):

```python
import uuid

from core.graph.client import GraphUnavailable, get_graph_client


@pytest.fixture(autouse=True)
def graph_ns(monkeypatch):
    """A unique namespace per test. Setting the env var makes any code path that reads the configured namespace
    (the app's routes, for example) write into this test's namespace, never into `main`."""
    ns = f"test-{uuid.uuid4().hex[:12]}"
    monkeypatch.setenv("GRAPH_NAMESPACE", ns)
    yield ns
    if get_graph_client.cache_info().currsize:
        get_graph_client().write("MATCH (n {ns: $ns}) DETACH DELETE n", ns=ns)


@pytest.fixture
def graph_client():
    client = get_graph_client()
    try:
        client.read("RETURN 1 AS ok")
    except GraphUnavailable as exc:
        pytest.fail(f"Neo4j is not reachable ({exc}). Start it with: docker start neo4j-estimate", pytrace=False)
    return client
```

Create `backend/tests/core/test_graph_client.py`:

```python
import pytest

from core.config.settings import Settings
from core.graph.client import GraphClient, GraphQueryFailed, GraphUnavailable


def test_read_returns_rows_as_dicts(graph_client):
    assert graph_client.read("RETURN $n AS n", n=7) == [{"n": 7}]


def test_write_then_read_round_trips_inside_the_test_namespace(graph_client, graph_ns):
    graph_client.write("CREATE (:Probe {ns: $ns, id: 'p1'})", ns=graph_ns)

    rows = graph_client.read("MATCH (p:Probe {ns: $ns}) RETURN p.id AS id", ns=graph_ns)

    assert rows == [{"id": "p1"}]


def test_a_cypher_error_raises_graph_query_failed(graph_client):
    with pytest.raises(GraphQueryFailed):
        graph_client.read("THIS IS NOT CYPHER")


def test_an_unreachable_server_raises_graph_unavailable():
    client = GraphClient("bolt://localhost:1", "neo4j", "x")
    try:
        with pytest.raises(GraphUnavailable):
            client.read("RETURN 1")
    finally:
        client.close()


def test_a_wrong_password_raises_graph_unavailable(graph_client, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5433/db")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    settings = Settings(_env_file=None)
    client = GraphClient(settings.neo4j_uri, settings.neo4j_user, "definitely-wrong")
    try:
        with pytest.raises(GraphUnavailable):
            client.read("RETURN 1")
    finally:
        client.close()
```

- [ ] **Step 7: Run to verify failure**

Run: `pytest tests/core/test_graph_client.py -v`. Expected: collection error `ModuleNotFoundError: core.graph`.

- [ ] **Step 8: Implement the client**

Create `backend/core/graph/__init__.py` (empty) and `backend/core/graph/client.py`:

```python
from functools import lru_cache

from neo4j import GraphDatabase, Query, RoutingControl
from neo4j.exceptions import AuthError, Neo4jError, ServiceUnavailable, SessionExpired

from core.config.settings import Settings

DATABASE = "neo4j"
CONNECTION_TIMEOUT_SECONDS = 5
QUERY_TIMEOUT_SECONDS = 30


class GraphError(Exception):
    pass


class GraphUnavailable(GraphError):
    pass


class GraphQueryFailed(GraphError):
    pass


class GraphClient:
    def __init__(self, uri: str, user: str, password: str) -> None:
        # Notifications off: GDS emits deprecation notices on some procedures that would flood the log.
        self._driver = GraphDatabase.driver(
            uri, auth=(user, password), connection_timeout=CONNECTION_TIMEOUT_SECONDS,
            notifications_min_severity="OFF",
        )

    def read(self, query: str, **params) -> list[dict]:
        return self._execute(query, params, RoutingControl.READ)

    def write(self, query: str, **params) -> list[dict]:
        return self._execute(query, params, RoutingControl.WRITE)

    def close(self) -> None:
        self._driver.close()

    def _execute(self, query: str, params: dict, routing: RoutingControl) -> list[dict]:
        try:
            result = self._driver.execute_query(
                Query(query, timeout=QUERY_TIMEOUT_SECONDS), parameters_=params, routing_=routing, database_=DATABASE,
            )
        except (ServiceUnavailable, SessionExpired, AuthError, OSError) as exc:
            raise GraphUnavailable(f"Neo4j is unavailable: {exc}") from exc
        except Neo4jError as exc:
            raise GraphQueryFailed(f"Neo4j query failed: {exc}") from exc
        return [record.data() for record in result.records]


@lru_cache
def get_graph_client() -> GraphClient:
    settings = Settings()
    return GraphClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)


def get_graph_namespace() -> str:
    return Settings().graph_namespace
```

- [ ] **Step 9: Run to verify pass**

Run: `pytest tests/core/test_settings.py tests/core/test_graph_client.py -v`. Expected: all PASS. Then run the full suite once (`pytest -q`) to confirm the autouse fixture broke nothing: 274 + the new tests pass.

- [ ] **Step 10: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/core/config/settings.py backend/.env.example docker-compose.yml backend/tests/conftest.py backend/tests/core/test_settings.py backend/core/graph/__init__.py backend/core/graph/client.py backend/tests/core/test_graph_client.py
git commit -m "feat: add Neo4j client, graph settings, compose service, and namespaced test fixtures"
```

---

### Task 2: Structure data generator (families, projects) and validation

**Files:**
- Create: `backend/scripts/data_gen/structure_gen.py`, `backend/data/structure.json` (generated), `backend/tests/data_gen/test_structure_gen.py`, `backend/tests/data_gen/test_validate_structure.py`
- Modify: `backend/scripts/data_gen/validate.py`

**Interfaces:**
- Produces: `structure_gen.family_name(sku: dict) -> str`; `generate_structure(catalog: list[dict], customers: list[dict]) -> dict` returning `{"families": [{"family_id","name","category"}], "sku_family": {sku_id: family_id}, "projects": [{"project_id","customer_id","site_id","name"}]}`; `write_structure(structure, path, force=False)`; `validate.check_structure(catalog, customers, structure) -> list[str]`.

- [ ] **Step 1: Write the failing generator tests**

Create `backend/tests/data_gen/test_structure_gen.py`:

```python
import json
from pathlib import Path

import pytest

from data_gen.structure_gen import family_name, generate_structure, write_structure

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _sku(sku_id, name, category):
    return {"sku_id": sku_id, "name": name, "category": category, "list_price": 10.0, "discontinued": False,
            "replaced_by": None, "requires": [], "in_stock": True}


def _catalog():
    return [
        _sku("SKU-0001", "Copper Adapter 1/2 in", "Plumbing-Fittings"),
        _sku("SKU-0002", "Copper Adapter 3/4 in", "Plumbing-Fittings"),
        _sku("SKU-0003", "Chrome Sprayer Corner-Mount", "Plumbing-Fixtures"),
        _sku("SKU-0004", "PVC Tee 1-1/2 in", "Plumbing-Fittings"),
        _sku("SKU-0005", "Commercial Evaporator Coil 4 Ton", "HVAC-Equipment"),
    ]


def _customers():
    return [
        {"customer_id": "CUST-0001", "name": "Crown Services", "account_tier": "Standard", "contacts": [],
         "contracts": [], "sites": [
             {"site_id": "SITE-0001", "address": "9441 Main St, Greenville, SC", "zip": "29601"},
             {"site_id": "SITE-0002", "address": "12 Elm St, Greenville, SC", "zip": "29602"},
         ]},
        {"customer_id": "CUST-0002", "name": "Peak Plumbing", "account_tier": "Standard", "contacts": [],
         "contracts": [], "sites": [{"site_id": "SITE-0003", "address": "1 Oak Ave, Austin, TX", "zip": "73301"}]},
    ]


def test_family_name_strips_the_size_suffix():
    assert family_name(_sku("S", "Copper Adapter 1/2 in", "Plumbing-Fittings")) == "Copper Adapter"
    assert family_name(_sku("S", "PVC Tee 1-1/2 in", "Plumbing-Fittings")) == "PVC Tee"
    assert family_name(_sku("S", "Chrome Sprayer Corner-Mount", "Plumbing-Fixtures")) == "Chrome Sprayer"
    assert family_name(_sku("S", "Commercial Evaporator Coil 4 Ton", "HVAC-Equipment")) == "Commercial Evaporator Coil"


def test_family_name_rejects_a_name_with_no_known_size():
    with pytest.raises(ValueError, match="SKU-9"):
        family_name(_sku("SKU-9", "Mystery Gadget", "Plumbing-Fittings"))


def test_skus_sharing_a_stem_share_a_family_and_others_do_not():
    structure = generate_structure(_catalog(), _customers())
    by_sku = structure["sku_family"]

    assert by_sku["SKU-0001"] == by_sku["SKU-0002"]
    assert len({by_sku["SKU-0001"], by_sku["SKU-0003"], by_sku["SKU-0004"], by_sku["SKU-0005"]}) == 4
    families = {f["family_id"]: f for f in structure["families"]}
    assert families[by_sku["SKU-0001"]] == {
        "family_id": by_sku["SKU-0001"], "name": "Copper Adapter", "category": "Plumbing-Fittings",
    }


def test_family_ids_are_assigned_in_sorted_category_then_name_order():
    structure = generate_structure(_catalog(), _customers())

    order = [(f["category"], f["name"]) for f in structure["families"]]
    assert order == sorted(order)
    assert [f["family_id"] for f in structure["families"]] == [f"FAM-{i:04d}" for i in range(1, len(order) + 1)]


def test_one_project_per_site_with_ids_derived_from_the_site():
    structure = generate_structure(_catalog(), _customers())

    assert [(p["project_id"], p["customer_id"], p["site_id"]) for p in structure["projects"]] == [
        ("PRJ-0001", "CUST-0001", "SITE-0001"),
        ("PRJ-0002", "CUST-0001", "SITE-0002"),
        ("PRJ-0003", "CUST-0002", "SITE-0003"),
    ]
    assert structure["projects"][0]["name"] == "Crown Services job at 9441 Main St, Greenville, SC"


def test_generation_is_deterministic():
    assert generate_structure(_catalog(), _customers()) == generate_structure(_catalog(), _customers())


def test_write_structure_refuses_to_overwrite_without_force(tmp_path):
    path = tmp_path / "structure.json"
    write_structure({"families": [], "sku_family": {}, "projects": []}, path)

    with pytest.raises(FileExistsError):
        write_structure({"families": [], "sku_family": {}, "projects": []}, path)

    write_structure({"families": [{"family_id": "F"}], "sku_family": {}, "projects": []}, path, force=True)
    assert json.loads(path.read_text(encoding="utf-8"))["families"] == [{"family_id": "F"}]


def test_real_dataset_gives_every_sku_a_family_of_its_own_category():
    catalog = json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
    customers = json.loads((DATA_DIR / "customers.json").read_text(encoding="utf-8"))

    structure = generate_structure(catalog, customers)

    families = {f["family_id"]: f for f in structure["families"]}
    for sku in catalog:
        assert families[structure["sku_family"][sku["sku_id"]]]["category"] == sku["category"]
    assert len(structure["projects"]) == sum(len(c["sites"]) for c in customers)
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/data_gen/test_structure_gen.py -v`. Expected: collection error, `data_gen.structure_gen` not found.

- [ ] **Step 3: Implement the generator**

Create `backend/scripts/data_gen/structure_gen.py`:

```python
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_gen.catalog_gen import SIZES

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def family_name(sku: dict) -> str:
    """A SKU name is '<material> <base> <size>', so the family is the name minus its size suffix."""
    name = sku["name"]
    # Longest suffix first, so a size that ends another size (none today) cannot win by accident.
    for size in sorted(SIZES[sku["category"]], key=len, reverse=True):
        suffix = f" {size}"
        if name.endswith(suffix):
            return name[: -len(suffix)]
    raise ValueError(f"SKU {sku['sku_id']} name {name!r} has no known size suffix for {sku['category']}")


def generate_structure(catalog: list[dict], customers: list[dict]) -> dict:
    keys = sorted({(sku["category"], family_name(sku)) for sku in catalog})
    family_ids = {key: f"FAM-{index:04d}" for index, key in enumerate(keys, start=1)}
    families = [{"family_id": family_ids[key], "name": key[1], "category": key[0]} for key in keys]
    sku_family = {sku["sku_id"]: family_ids[(sku["category"], family_name(sku))] for sku in catalog}

    projects = [
        {
            "project_id": "PRJ-" + site["site_id"].removeprefix("SITE-"),
            "customer_id": customer["customer_id"],
            "site_id": site["site_id"],
            "name": f"{customer['name']} job at {site['address']}",
        }
        for customer in customers
        for site in customer["sites"]
    ]
    return {"families": families, "sku_family": sku_family, "projects": projects}


def write_structure(structure: dict, path: Path, force: bool = False) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists; pass --force to overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(structure, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate product families and one project per site")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    catalog = json.loads((args.data_dir / "catalog.json").read_text(encoding="utf-8"))
    customers = json.loads((args.data_dir / "customers.json").read_text(encoding="utf-8"))

    structure = generate_structure(catalog, customers)
    write_structure(structure, args.data_dir / "structure.json", force=args.force)
    print(
        f"wrote {len(structure['families'])} families and {len(structure['projects'])} projects "
        f"to {args.data_dir / 'structure.json'}"
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/data_gen/test_structure_gen.py -v`. Expected: PASS.

- [ ] **Step 5: Write the failing validation tests**

Create `backend/tests/data_gen/test_validate_structure.py`:

```python
from data_gen.validate import check_structure

CATALOG = [
    {"sku_id": "SKU-1", "category": "Cat-A"},
    {"sku_id": "SKU-2", "category": "Cat-A"},
]
CUSTOMERS = [
    {"customer_id": "CUST-1", "sites": [{"site_id": "SITE-1"}, {"site_id": "SITE-2"}]},
    {"customer_id": "CUST-2", "sites": [{"site_id": "SITE-3"}]},
]


def _good():
    return {
        "families": [{"family_id": "FAM-1", "name": "F", "category": "Cat-A"}],
        "sku_family": {"SKU-1": "FAM-1", "SKU-2": "FAM-1"},
        "projects": [
            {"project_id": "PRJ-1", "customer_id": "CUST-1", "site_id": "SITE-1", "name": "n"},
            {"project_id": "PRJ-2", "customer_id": "CUST-1", "site_id": "SITE-2", "name": "n"},
            {"project_id": "PRJ-3", "customer_id": "CUST-2", "site_id": "SITE-3", "name": "n"},
        ],
    }


def test_a_consistent_structure_passes():
    assert check_structure(CATALOG, CUSTOMERS, _good()) == []


def test_a_sku_without_a_family_is_reported():
    structure = _good()
    del structure["sku_family"]["SKU-2"]

    assert any("SKU-2 has no family" in f for f in check_structure(CATALOG, CUSTOMERS, structure))


def test_a_mapping_to_an_unknown_family_or_sku_is_reported():
    structure = _good()
    structure["sku_family"]["SKU-1"] = "FAM-NOPE"
    structure["sku_family"]["SKU-GHOST"] = "FAM-1"

    failures = check_structure(CATALOG, CUSTOMERS, structure)

    assert any("unknown family FAM-NOPE" in f for f in failures)
    assert any("unknown SKU SKU-GHOST" in f for f in failures)


def test_a_family_in_a_different_category_than_its_sku_is_reported():
    structure = _good()
    structure["families"][0]["category"] = "Cat-B"

    assert any("category" in f for f in check_structure(CATALOG, CUSTOMERS, structure))


def test_a_site_without_exactly_one_project_is_reported():
    structure = _good()
    structure["projects"] = structure["projects"][:2]
    structure["projects"].append({"project_id": "PRJ-9", "customer_id": "CUST-1", "site_id": "SITE-1", "name": "n"})

    failures = check_structure(CATALOG, CUSTOMERS, structure)

    assert any("SITE-1" in f and "2 projects" in f for f in failures)
    assert any("SITE-3" in f and "0 projects" in f for f in failures)


def test_a_project_on_another_customers_site_or_unknown_site_is_reported():
    structure = _good()
    structure["projects"][0]["customer_id"] = "CUST-2"
    structure["projects"][1]["site_id"] = "SITE-GHOST"

    failures = check_structure(CATALOG, CUSTOMERS, structure)

    assert any("PRJ-1" in f and "belongs to" in f for f in failures)
    assert any("PRJ-2" in f and "unknown site SITE-GHOST" in f for f in failures)
```

- [ ] **Step 6: Run to verify failure**

Run: `pytest tests/data_gen/test_validate_structure.py -v`. Expected: FAIL, `ImportError: cannot import name 'check_structure'`.

- [ ] **Step 7: Implement `check_structure` and wire it into `validate.py`**

Add to `backend/scripts/data_gen/validate.py`, after `check_pricing`:

```python
def check_structure(catalog: list[dict], customers: list[dict], structure: dict) -> list[str]:
    failures = []
    category_by_sku = {s["sku_id"]: s["category"] for s in catalog}
    family_category = {f["family_id"]: f["category"] for f in structure["families"]}
    mapping = structure["sku_family"]

    for sku_id in sorted(set(category_by_sku) - set(mapping)):
        failures.append(f"structure: SKU {sku_id} has no family")
    for sku_id in sorted(set(mapping) - set(category_by_sku)):
        failures.append(f"structure: mapping references unknown SKU {sku_id}")
    for sku_id, family_id in sorted(mapping.items()):
        if family_id not in family_category:
            failures.append(f"structure: SKU {sku_id} maps to unknown family {family_id}")
        elif sku_id in category_by_sku and family_category[family_id] != category_by_sku[sku_id]:
            failures.append(f"structure: SKU {sku_id} category differs from its family {family_id} category")

    site_owner = {site["site_id"]: c["customer_id"] for c in customers for site in c["sites"]}
    projects_per_site: dict[str, int] = {}
    for project in structure["projects"]:
        owner = site_owner.get(project["site_id"])
        if owner is None:
            failures.append(f"structure: project {project['project_id']} references unknown site {project['site_id']}")
            continue
        if owner != project["customer_id"]:
            failures.append(
                f"structure: project {project['project_id']} site {project['site_id']} belongs to {owner}, "
                f"not {project['customer_id']}"
            )
        projects_per_site[project["site_id"]] = projects_per_site.get(project["site_id"], 0) + 1
    for site_id in sorted(site_owner):
        count = projects_per_site.get(site_id, 0)
        if count != 1:
            failures.append(f"structure: site {site_id} has {count} projects, expected exactly 1")

    return failures
```

In `main()` add the argument and the call:

```python
    parser.add_argument("--structure", type=Path, default=DATA_DIR / "structure.json")
    ...
    structure = json.loads(args.structure.read_text(encoding="utf-8"))
    ...
        + check_pricing(catalog, customers, pricing)
        + check_structure(catalog, customers, structure)
```

- [ ] **Step 8: Run to verify pass, generate the real data, validate it**

Run: `pytest tests/data_gen -v` (all PASS). Then from `backend/`:
`.venv/Scripts/python.exe scripts/data_gen/structure_gen.py` (prints the family and project counts; report them in your handoff) and `.venv/Scripts/python.exe scripts/data_gen/validate.py` (expects `all checks passed`).

- [ ] **Step 9: Commit**

```bash
git add backend/scripts/data_gen/structure_gen.py backend/scripts/data_gen/validate.py backend/data/structure.json backend/tests/data_gen/test_structure_gen.py backend/tests/data_gen/test_validate_structure.py
git commit -m "feat: generate product families and per-site projects with validation"
```

### Task 3: Postgres structure (migration 0004, models, repositories, loader)

**Files:**
- Modify: `backend/app/reference_data/models.py`, `backend/app/reference_data/repository.py`, `backend/scripts/load_data.py`, `backend/migrations/env.py`, `backend/tests/test_load_data.py`
- Create: `backend/app/retrieval/__init__.py` (empty), `backend/app/retrieval/models.py`, `backend/core/llm/openai_embedding_client.py` (constants only for now), `backend/migrations/versions/0004_graph_structure_and_retrieval.py`, `backend/tests/app/reference_data/test_structure_models.py`

**Interfaces:**
- Consumes: the `data/structure.json` shape from Task 2.
- Produces: ORM `ProductFamily(family_id, name, category)`, `Project(project_id, customer_id, site_id unique, name)`, `Contact(contact_id, customer_id, name, email, phone)`, `Sku.family_id`; `app.retrieval.models.SkuEmbedding(sku_id, embedding, model, created_at)` and `CommunitySummary(member_hash, summary, model, created_at)`; `core.llm.openai_embedding_client.EMBEDDING_MODEL` and `EMBEDDING_DIMENSIONS = 1536` (Task 9 completes that module). Repository functions in `app/reference_data/repository.py`: `upsert_family(session, *, family_id, name, category)`, `set_sku_family(session, sku_id, family_id)` (raises `ValueError` for an unknown SKU), `upsert_project(session, *, project_id, customer_id, site_id, name)`, `upsert_contact(session, *, contact_id, customer_id, name, email, phone)`, `all_contracts`, `all_sites`, `all_requirements`, `all_families`, `all_projects`, `all_contacts`, `sites_for_customer(session, customer_id)`, `project_for_site(session, site_id) -> Project | None`. Loader: `load_structure(session, structure: dict) -> None`; `load_customers` now also loads contacts with ids `<customer_id>-C<n>`.

- [ ] **Step 1: Write the failing model tests**

Create `backend/tests/app/reference_data/test_structure_models.py`:

```python
import pytest
from sqlalchemy.exc import IntegrityError

from app.reference_data.models import Contact, Customer, ProductFamily, Project, Site, Sku
from app.retrieval.models import CommunitySummary, SkuEmbedding


def _customer(session, customer_id="CUST-SM1"):
    session.add(Customer(customer_id=customer_id, name="n", account_tier="Standard"))
    session.flush()


def test_family_project_and_contact_round_trip(db_session):
    _customer(db_session)
    db_session.add(Site(site_id="SITE-SM1", customer_id="CUST-SM1", address="1 Main St", zip="00000"))
    db_session.add(ProductFamily(family_id="FAM-SM1", name="Copper Adapter", category="Cat-SM"))
    db_session.flush()
    db_session.add(Project(project_id="PRJ-SM1", customer_id="CUST-SM1", site_id="SITE-SM1", name="job"))
    db_session.add(Contact(contact_id="CUST-SM1-C1", customer_id="CUST-SM1", name="Ravi", email="r@x.example", phone="555"))
    db_session.flush()

    assert db_session.get(Project, "PRJ-SM1").site_id == "SITE-SM1"
    assert db_session.get(Contact, "CUST-SM1-C1").email == "r@x.example"
    assert db_session.get(ProductFamily, "FAM-SM1").category == "Cat-SM"


def test_a_site_can_host_only_one_project(db_session):
    _customer(db_session)
    db_session.add(Site(site_id="SITE-SM2", customer_id="CUST-SM1", address="2 Main St", zip="00000"))
    db_session.flush()
    db_session.add(Project(project_id="PRJ-SM2", customer_id="CUST-SM1", site_id="SITE-SM2", name="a"))
    db_session.flush()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(Project(project_id="PRJ-SM3", customer_id="CUST-SM1", site_id="SITE-SM2", name="b"))
            db_session.flush()


def test_sku_family_link(db_session):
    db_session.add(ProductFamily(family_id="FAM-SM4", name="F", category="Cat-SM"))
    db_session.flush()
    db_session.add(Sku(sku_id="SKU-SM4", name="F 1 in", category="Cat-SM", list_price=1.0, discontinued=False,
                       replaced_by=None, in_stock=True, family_id="FAM-SM4"))
    db_session.flush()

    assert db_session.get(Sku, "SKU-SM4").family_id == "FAM-SM4"


def test_embedding_and_summary_round_trip(db_session):
    db_session.add(Sku(sku_id="SKU-SM5", name="n", category="Cat-SM", list_price=1.0, discontinued=False,
                       replaced_by=None, in_stock=True))
    db_session.flush()
    db_session.add(SkuEmbedding(sku_id="SKU-SM5", embedding=[0.5] * 1536, model="test-model"))
    db_session.add(CommunitySummary(member_hash="hash-sm5", summary="A cluster.", model="test-model"))
    db_session.flush()
    db_session.expire_all()

    assert list(db_session.get(SkuEmbedding, "SKU-SM5").embedding)[:2] == [0.5, 0.5]
    assert db_session.get(CommunitySummary, "hash-sm5").summary == "A cluster."
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/app/reference_data/test_structure_models.py -v`. Expected: collection error (`app.retrieval` missing).

- [ ] **Step 3: Implement models and the embedding constants**

Create `backend/core/llm/openai_embedding_client.py` containing only this for now (Task 9 completes it):

```python
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
```

Create `backend/app/retrieval/__init__.py` (empty) and `backend/app/retrieval/models.py`:

```python
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from core.db.base import Base
from core.llm.openai_embedding_client import EMBEDDING_DIMENSIONS


class SkuEmbedding(Base):
    __tablename__ = "sku_embeddings"

    sku_id: Mapped[str] = mapped_column(ForeignKey("skus.sku_id"), primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    model: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class CommunitySummary(Base):
    __tablename__ = "community_summaries"

    member_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    summary: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
```

In `backend/app/reference_data/models.py` add `family_id` to `Sku` (after `in_stock`) and the three new classes at the end of the file:

```python
    family_id: Mapped[str | None] = mapped_column(ForeignKey("product_families.family_id"))
```

```python
class ProductFamily(Base):
    __tablename__ = "product_families"

    family_id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    category: Mapped[str]


class Project(Base):
    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"))
    # One project per site: a resolved site identifies its project.
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.site_id"), unique=True)
    name: Mapped[str]


class Contact(Base):
    __tablename__ = "contacts"

    contact_id: Mapped[str] = mapped_column(primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.customer_id"))
    name: Mapped[str]
    email: Mapped[str]
    phone: Mapped[str]
```

In `backend/migrations/env.py` add `from app.retrieval import models as retrieval_models  # noqa: F401` beside the other model imports.

- [ ] **Step 4: Write the migration**

Create `backend/migrations/versions/0004_graph_structure_and_retrieval.py`:

```python
"""product families, projects, contacts, sku embeddings, community summaries

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-28

"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "product_families",
        sa.Column("family_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
    )
    op.add_column("skus", sa.Column("family_id", sa.Text(), sa.ForeignKey("product_families.family_id"), nullable=True))
    op.create_table(
        "projects",
        sa.Column("project_id", sa.Text(), primary_key=True),
        sa.Column("customer_id", sa.Text(), sa.ForeignKey("customers.customer_id"), nullable=False),
        sa.Column("site_id", sa.Text(), sa.ForeignKey("sites.site_id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.UniqueConstraint("site_id", name="uq_projects_site_id"),
    )
    op.create_table(
        "contacts",
        sa.Column("contact_id", sa.Text(), primary_key=True),
        sa.Column("customer_id", sa.Text(), sa.ForeignKey("customers.customer_id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=False),
    )
    op.create_table(
        "sku_embeddings",
        sa.Column("sku_id", sa.Text(), sa.ForeignKey("skus.sku_id"), primary_key=True),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "community_summaries",
        sa.Column("member_hash", sa.Text(), primary_key=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("community_summaries")
    op.drop_table("sku_embeddings")
    op.drop_table("contacts")
    op.drop_table("projects")
    op.drop_column("skus", "family_id")
    op.drop_table("product_families")
```

Apply and check reversibility against the dev DB (the tests need the tables; this shared-schema change is intended and precedes the merge): `alembic upgrade head`, then `alembic downgrade -1`, then `alembic upgrade head` again. All three must succeed. The `vector` extension is left installed on downgrade on purpose.

- [ ] **Step 5: Run to verify the model tests pass**

Run: `pytest tests/app/reference_data/test_structure_models.py -v`. Expected: PASS.

- [ ] **Step 6: Write the failing repository and loader tests**

Append to `backend/tests/test_load_data.py` (add `load_structure` to the `from load_data import ...` line, plus these imports):

```python
from app.reference_data.models import Contact, ProductFamily, Project
from app.reference_data.repository import project_for_site, sites_for_customer
```

```python
def _structure_customers():
    return [{
        "customer_id": "CUST-ST1", "name": "Struct Co", "account_tier": "Standard",
        "contacts": [
            {"name": "Ravi Kumar", "email": "ravi@struct.example", "phone": "555-0001"},
            {"name": "Kiran Rao", "email": "kiran@struct.example", "phone": "555-0002"},
        ],
        "sites": [{"site_id": "SITE-ST1", "address": "1 Main St, Town, ST", "zip": "11111"}],
        "contracts": [],
    }]


def _structure():
    return {
        "families": [{"family_id": "FAM-ST1", "name": "Copper Adapter", "category": "Cat-ST"}],
        "sku_family": {"SKU-ST1": "FAM-ST1"},
        "projects": [{"project_id": "PRJ-ST1", "customer_id": "CUST-ST1", "site_id": "SITE-ST1", "name": "job"}],
    }


def _structure_catalog():
    return [{"sku_id": "SKU-ST1", "name": "Copper Adapter 1 in", "category": "Cat-ST", "list_price": 5.0,
             "discontinued": False, "replaced_by": None, "in_stock": True, "requires": []}]


def test_load_customers_loads_contacts_with_derived_ids(db_session):
    load_customers(db_session, _structure_customers())
    db_session.flush()

    assert db_session.get(Contact, "CUST-ST1-C1").name == "Ravi Kumar"
    assert db_session.get(Contact, "CUST-ST1-C2").email == "kiran@struct.example"


def test_load_customers_is_idempotent_for_contacts(db_session):
    load_customers(db_session, _structure_customers())
    load_customers(db_session, _structure_customers())
    db_session.flush()

    assert db_session.get(Contact, "CUST-ST1-C2").phone == "555-0002"


def test_load_structure_links_skus_families_and_projects(db_session):
    load_catalog(db_session, _structure_catalog())
    load_customers(db_session, _structure_customers())

    load_structure(db_session, _structure())
    db_session.flush()

    assert db_session.get(Sku, "SKU-ST1").family_id == "FAM-ST1"
    assert db_session.get(ProductFamily, "FAM-ST1").name == "Copper Adapter"
    assert project_for_site(db_session, "SITE-ST1").project_id == "PRJ-ST1"
    assert [s.site_id for s in sites_for_customer(db_session, "CUST-ST1")] == ["SITE-ST1"]


def test_load_structure_is_idempotent(db_session):
    load_catalog(db_session, _structure_catalog())
    load_customers(db_session, _structure_customers())

    load_structure(db_session, _structure())
    load_structure(db_session, _structure())
    db_session.flush()

    assert db_session.get(Project, "PRJ-ST1").name == "job"


def test_load_structure_rejects_an_unknown_sku(db_session):
    load_customers(db_session, _structure_customers())
    structure = _structure()
    structure["sku_family"] = {"SKU-NOPE": "FAM-ST1"}

    with pytest.raises(ValueError, match="SKU-NOPE"):
        load_structure(db_session, structure)
```

- [ ] **Step 7: Run to verify failure**

Run: `pytest tests/test_load_data.py -v`. Expected: the new tests FAIL (`ImportError: load_structure`).

- [ ] **Step 8: Implement repositories and loader**

Append to `backend/app/reference_data/repository.py` (extend the model import line with `Contact, ProductFamily, Project`):

```python
def upsert_family(session: Session, *, family_id: str, name: str, category: str) -> None:
    row = session.get(ProductFamily, family_id)
    if row is None:
        row = ProductFamily(family_id=family_id)
        session.add(row)
    row.name = name
    row.category = category


def set_sku_family(session: Session, sku_id: str, family_id: str) -> None:
    sku = session.get(Sku, sku_id)
    if sku is None:
        raise ValueError(f"structure references unknown SKU {sku_id}")
    sku.family_id = family_id


def upsert_project(session: Session, *, project_id: str, customer_id: str, site_id: str, name: str) -> None:
    row = session.get(Project, project_id)
    if row is None:
        row = Project(project_id=project_id)
        session.add(row)
    row.customer_id = customer_id
    row.site_id = site_id
    row.name = name


def upsert_contact(
    session: Session, *, contact_id: str, customer_id: str, name: str, email: str, phone: str,
) -> None:
    row = session.get(Contact, contact_id)
    if row is None:
        row = Contact(contact_id=contact_id)
        session.add(row)
    row.customer_id = customer_id
    row.name = name
    row.email = email
    row.phone = phone


def all_contracts(session: Session) -> list[Contract]:
    return list(session.scalars(select(Contract).order_by(Contract.contract_id)))


def all_sites(session: Session) -> list[Site]:
    return list(session.scalars(select(Site).order_by(Site.site_id)))


def all_requirements(session: Session) -> list[SkuRequirement]:
    return list(session.scalars(select(SkuRequirement).order_by(SkuRequirement.sku_id, SkuRequirement.required_sku_id)))


def all_families(session: Session) -> list[ProductFamily]:
    return list(session.scalars(select(ProductFamily).order_by(ProductFamily.family_id)))


def all_projects(session: Session) -> list[Project]:
    return list(session.scalars(select(Project).order_by(Project.project_id)))


def all_contacts(session: Session) -> list[Contact]:
    return list(session.scalars(select(Contact).order_by(Contact.contact_id)))


def sites_for_customer(session: Session, customer_id: str) -> list[Site]:
    return list(session.scalars(select(Site).where(Site.customer_id == customer_id).order_by(Site.site_id)))


def project_for_site(session: Session, site_id: str) -> Project | None:
    return session.scalar(select(Project).where(Project.site_id == site_id))
```

In `backend/scripts/load_data.py`: extend the repository import with `set_sku_family, upsert_contact, upsert_family, upsert_project`; in `load_customers`, right after the `upsert_customer(...)` call and before the sites loop add:

```python
        for number, contact in enumerate(customer["contacts"], start=1):
            upsert_contact(
                session, contact_id=f"{customer['customer_id']}-C{number}", customer_id=customer["customer_id"],
                name=contact["name"], email=contact["email"], phone=contact["phone"],
            )
```

Add the loader and wire it into `run`:

```python
def load_structure(session, structure: dict) -> None:
    # Sessions run with autoflush off: SKUs, customers and sites loaded earlier must be flushed to be linked.
    session.flush()
    for family in structure["families"]:
        upsert_family(session, family_id=family["family_id"], name=family["name"], category=family["category"])
    session.flush()
    for sku_id, family_id in structure["sku_family"].items():
        set_sku_family(session, sku_id, family_id)
    for project in structure["projects"]:
        upsert_project(
            session, project_id=project["project_id"], customer_id=project["customer_id"],
            site_id=project["site_id"], name=project["name"],
        )
```

In `run`: read `structure = json.loads((data_dir / "structure.json").read_text(encoding="utf-8"))`, call `load_structure(session, structure)` after `load_pricing(session, pricing)`, and extend the printed line with `{len(structure['families'])} families, {len(structure['projects'])} projects`.

- [ ] **Step 9: Run to verify pass**

Run: `pytest tests/test_load_data.py tests/app/reference_data -v`, then the full suite `pytest -q`. Expected: all PASS (274 plus the new tests).

- [ ] **Step 10: Commit**

```bash
git add backend/app/reference_data/models.py backend/app/reference_data/repository.py backend/app/retrieval/__init__.py backend/app/retrieval/models.py backend/core/llm/openai_embedding_client.py backend/migrations/env.py backend/migrations/versions/0004_graph_structure_and_retrieval.py backend/scripts/load_data.py backend/tests/test_load_data.py backend/tests/app/reference_data/test_structure_models.py
git commit -m "feat: add product families, projects, contacts, embeddings and summary tables"
```

---

### Task 4: Reference graph projection (constants, Cypher repository, rebuild, freshness fingerprint)

**Files:**
- Create: `backend/app/graph/__init__.py` (empty), `backend/app/graph/constant.py`, `backend/app/graph/schemas.py`, `backend/app/graph/repository.py`, `backend/app/graph/service.py`, `backend/tests/app/graph/__init__.py` (empty), `backend/tests/app/graph/test_rebuild.py`, `backend/tests/app/reference_data/test_fingerprint.py`
- Modify: `backend/app/reference_data/repository.py` (add `reference_fingerprint`), `backend/tests/app/estimate/seed.py` (add `seed_structure`)

**Interfaces:**
- Consumes: Task 1 `GraphClient`; Task 3 repository readers.
- Produces:
  - `app.graph.constant`: `NODE_LABELS`, `EDGE_TYPES`, `BATCH_SIZE = 1000`, `MAX_CHAIN_HOPS = 10`.
  - `app.graph.repository`: `node_key(ns, node_id) -> str` (`"<ns>:<id>"`), `drop_namespace(client, ns)`, `ensure_constraints(client)`, `merge_nodes(client, ns, label, rows)` with `rows = [{"id": str, "props": dict}]`, `merge_edges(client, ns, edge_type, from_label, to_label, rows)` with `rows = [{"from": str, "to": str, "props": dict}]`, `count_nodes_by_label(client, ns) -> dict[str, int]`, `count_edges_by_type(client, ns) -> dict[str, int]`.
  - `app.reference_data.repository.reference_fingerprint(session) -> str`.
  - `app.graph.schemas.RebuildSummary(namespace, fingerprint, node_counts, edge_counts)`.
  - `app.graph.service.rebuild_reference_graph(session, client, ns) -> None`.
  - `tests.app.estimate.seed.seed_structure(session)`.

- [ ] **Step 1: Write the failing fingerprint tests**

Create `backend/tests/app/reference_data/test_fingerprint.py`:

```python
from app.intake.repository import save_quote_request
from app.reference_data.models import Contract, Customer, Sku
from app.reference_data.repository import reference_fingerprint, upsert_requirement
from tests.app.estimate.seed import seed_world


def test_fingerprint_is_stable_for_unchanged_data(db_session):
    seed_world(db_session)

    assert reference_fingerprint(db_session) == reference_fingerprint(db_session)


def test_fingerprint_changes_when_a_sku_is_discontinued(db_session):
    seed_world(db_session)
    before = reference_fingerprint(db_session)

    db_session.get(Sku, "SKU-E-A1").discontinued = True
    db_session.flush()

    assert reference_fingerprint(db_session) != before


def test_fingerprint_changes_when_a_requirement_is_added(db_session):
    seed_world(db_session)
    before = reference_fingerprint(db_session)

    upsert_requirement(db_session, sku_id="SKU-E-P1", required_sku_id="SKU-E-A1")
    db_session.flush()

    assert reference_fingerprint(db_session) != before


def test_fingerprint_changes_when_a_contract_changes(db_session):
    seed_world(db_session)
    before = reference_fingerprint(db_session)

    db_session.get(Contract, "CTR-E1").covered_categories = ["Cat-E-A", "Cat-E-B"]
    db_session.flush()

    assert reference_fingerprint(db_session) != before


def test_fingerprint_ignores_runtime_entities_and_unrelated_columns(db_session):
    seed_world(db_session)
    before = reference_fingerprint(db_session)

    save_quote_request(
        db_session, raw_email_text="x", parsed_json={}, content_fingerprint={}, style_fingerprint={},
        customer_id="CUST-E1",
    )
    db_session.get(Customer, "CUST-E1").name = "Renamed Co"
    db_session.get(Sku, "SKU-E-A1").list_price = 123.0
    db_session.flush()

    assert reference_fingerprint(db_session) == before
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/app/reference_data/test_fingerprint.py -v`. Expected: FAIL, `ImportError: cannot import name 'reference_fingerprint'`.

- [ ] **Step 3: Implement the fingerprint**

Add `import hashlib` at the top of `backend/app/reference_data/repository.py` and append:

```python
def reference_fingerprint(session: Session) -> str:
    """Digest of the reference rows the graph guardrail depends on. The graph stores it at rebuild time; a
    mismatch later means Postgres moved on and the graph is stale."""
    digest = hashlib.md5(usedforsecurity=False)
    statements = (
        select(Sku.sku_id, Sku.category, Sku.discontinued, Sku.replaced_by, Sku.family_id, Sku.in_stock)
        .order_by(Sku.sku_id),
        select(SkuRequirement.sku_id, SkuRequirement.required_sku_id)
        .order_by(SkuRequirement.sku_id, SkuRequirement.required_sku_id),
        select(
            Contract.contract_id, Contract.customer_id, Contract.covered_categories, Contract.effective_from,
            Contract.effective_to, Contract.discount_pct,
        ).order_by(Contract.contract_id),
    )
    for statement in statements:
        for row in session.execute(statement):
            digest.update(repr(tuple(row)).encode("utf-8"))
        digest.update(b"|")
    return digest.hexdigest()
```

Run: `pytest tests/app/reference_data/test_fingerprint.py -v`. Expected: PASS.

- [ ] **Step 4: Add the structure seed**

Append to `backend/tests/app/estimate/seed.py` (extend its repository import with `set_sku_family, upsert_contact, upsert_family, upsert_project, upsert_site`):

```python
def seed_structure(session) -> None:
    """Adds the article's identity layer to seed_world: two sites for CUST-E1 (12 Elm Street in two cities, so a
    street-only hint is ambiguous), one project per site, a family holding SKU-E-A1 and SKU-E-OLD, one contact."""
    upsert_site(session, site_id="SITE-E1", customer_id="CUST-E1", address="12 Elm Street, Springfield, IL", zip_code="62701")
    upsert_site(session, site_id="SITE-E2", customer_id="CUST-E1", address="12 Elm Street, Portland, OR", zip_code="97201")
    upsert_family(session, family_id="FAM-E-A", name="Zorpwidget Alpha", category="Cat-E-A")
    session.flush()
    set_sku_family(session, "SKU-E-A1", "FAM-E-A")
    set_sku_family(session, "SKU-E-OLD", "FAM-E-A")
    upsert_project(session, project_id="PRJ-E1", customer_id="CUST-E1", site_id="SITE-E1", name="Vexthorn job at 12 Elm Street, Springfield")
    upsert_project(session, project_id="PRJ-E2", customer_id="CUST-E1", site_id="SITE-E2", name="Vexthorn job at 12 Elm Street, Portland")
    upsert_contact(
        session, contact_id="CUST-E1-C1", customer_id="CUST-E1", name="Ravi Kumar",
        email="ravi@vexthorn.example.com", phone="555-0100",
    )
    session.flush()
```

- [ ] **Step 5: Write the failing rebuild tests**

Create `backend/tests/app/graph/__init__.py` (empty) and `backend/tests/app/graph/test_rebuild.py`:

```python
import uuid

from app.graph.repository import count_edges_by_type, count_nodes_by_label, ensure_constraints, node_key
from app.graph.service import rebuild_reference_graph
from app.reference_data.models import Contract
from app.reference_data.repository import reference_fingerprint, upsert_contract
from tests.app.estimate.seed import seed_structure, seed_world


def _node(client, ns, node_id):
    rows = client.read(
        "MATCH (n {key: $key}) RETURN labels(n) AS labels, properties(n) AS props", key=node_key(ns, node_id)
    )
    return rows[0] if rows else None


def _edges(client, ns, source, edge_type, target):
    rows = client.read(
        "MATCH ({key: $source})-[r]->({key: $target}) WHERE type(r) = $type RETURN count(r) AS count",
        source=node_key(ns, source), target=node_key(ns, target), type=edge_type,
    )
    return rows[0]["count"]


def _build(db_session, graph_client, graph_ns):
    seed_world(db_session)
    seed_structure(db_session)
    rebuild_reference_graph(db_session, graph_client, graph_ns)


def test_every_reference_node_type_is_built_with_its_properties(db_session, graph_client, graph_ns):
    _build(db_session, graph_client, graph_ns)

    sku = _node(graph_client, graph_ns, "SKU-E-A1")
    assert sku["labels"] == ["SKU"]
    assert sku["props"]["ns"] == graph_ns and sku["props"]["id"] == "SKU-E-A1"
    assert sku["props"]["category"] == "Cat-E-A" and sku["props"]["list_price"] == 100.0
    assert sku["props"]["discontinued"] is False and sku["props"]["in_stock"] is True
    assert _node(graph_client, graph_ns, "Cat-E-A")["labels"] == ["PricingCategory"]
    assert _node(graph_client, graph_ns, "CUST-E1")["props"]["account_tier"] == "Standard"
    assert _node(graph_client, graph_ns, "CUST-E1-C1")["labels"] == ["Person"]
    contract = _node(graph_client, graph_ns, "CTR-E1")
    assert contract["labels"] == ["Contract"]
    assert contract["props"]["discount_pct"] == 10.0
    assert contract["props"]["effective_from"] == "2024-01-01"
    assert _node(graph_client, graph_ns, "FAM-E-A")["props"]["name"] == "Zorpwidget Alpha"
    assert _node(graph_client, graph_ns, "PRJ-E1")["labels"] == ["Project"]
    assert _node(graph_client, graph_ns, "SITE-E1")["props"]["zip"] == "62701"


def test_every_reference_edge_type_is_built(db_session, graph_client, graph_ns):
    _build(db_session, graph_client, graph_ns)

    expected = [
        ("CUST-E1-C1", "WORKS_FOR", "CUST-E1"),
        ("CUST-E1", "HOLDS", "CTR-E1"),
        ("CTR-E1", "COVERS", "Cat-E-A"),
        ("SKU-E-A1", "IN_FAMILY", "FAM-E-A"),
        ("SKU-E-OLD", "REPLACED_BY", "SKU-E-A1"),
        ("SKU-E-A1", "PRICED_IN", "Cat-E-A"),
        ("SKU-E-B1", "REQUIRES", "SKU-E-A1"),
        ("CUST-E1", "HAS_PROJECT", "PRJ-E1"),
        ("PRJ-E1", "AT_SITE", "SITE-E1"),
    ]
    for source, edge_type, target in expected:
        assert _edges(graph_client, graph_ns, source, edge_type, target) == 1, (source, edge_type, target)


def test_a_gap_sku_has_no_list_price_property(db_session, graph_client, graph_ns):
    _build(db_session, graph_client, graph_ns)

    assert "list_price" not in _node(graph_client, graph_ns, "SKU-E-GAP")["props"]


def test_a_covered_category_with_no_skus_still_gets_a_node_and_edge(db_session, graph_client, graph_ns):
    seed_world(db_session)
    template = db_session.get(Contract, "CTR-E1")
    upsert_contract(
        db_session, contract_id="CTR-E-EMPTY", customer_id="CUST-E2", discount_category="Cat-E-EMPTY",
        covered_categories=["Cat-E-EMPTY"], effective_from=template.effective_from,
        effective_to=template.effective_to, discount_pct=5.0,
    )
    db_session.flush()

    rebuild_reference_graph(db_session, graph_client, graph_ns)

    assert _edges(graph_client, graph_ns, "CTR-E-EMPTY", "COVERS", "Cat-E-EMPTY") == 1


def test_rebuild_is_idempotent(db_session, graph_client, graph_ns):
    _build(db_session, graph_client, graph_ns)
    before = (count_nodes_by_label(graph_client, graph_ns), count_edges_by_type(graph_client, graph_ns))

    rebuild_reference_graph(db_session, graph_client, graph_ns)

    assert (count_nodes_by_label(graph_client, graph_ns), count_edges_by_type(graph_client, graph_ns)) == before
    assert _edges(graph_client, graph_ns, "SKU-E-B1", "REQUIRES", "SKU-E-A1") == 1


def test_rebuild_replaces_stale_content_in_its_namespace(db_session, graph_client, graph_ns):
    _build(db_session, graph_client, graph_ns)
    graph_client.write(
        "CREATE (:SKU {ns: $ns, key: $key, id: 'SKU-STALE'})", ns=graph_ns, key=node_key(graph_ns, "SKU-STALE"),
    )

    rebuild_reference_graph(db_session, graph_client, graph_ns)

    assert _node(graph_client, graph_ns, "SKU-STALE") is None


def test_rebuild_leaves_other_namespaces_alone(db_session, graph_client, graph_ns):
    other = f"test-other-{uuid.uuid4().hex[:8]}"
    graph_client.write(
        "CREATE (:Sentinel {ns: $ns, key: $key, id: 'keep-me'})", ns=other, key=node_key(other, "keep-me"),
    )
    try:
        _build(db_session, graph_client, graph_ns)

        assert _node(graph_client, other, "keep-me") is not None
    finally:
        graph_client.write("MATCH (n {ns: $ns}) DETACH DELETE n", ns=other)


def test_graph_meta_stores_the_reference_fingerprint(db_session, graph_client, graph_ns):
    _build(db_session, graph_client, graph_ns)

    meta = _node(graph_client, graph_ns, graph_ns)

    assert meta["labels"] == ["GraphMeta"]
    assert meta["props"]["reference_fingerprint"] == reference_fingerprint(db_session)
    assert meta["props"]["built_at"]


def test_ensure_constraints_can_run_twice(graph_client):
    ensure_constraints(graph_client)
    ensure_constraints(graph_client)
```

- [ ] **Step 6: Run to verify failure**

Run: `pytest tests/app/graph/test_rebuild.py -v`. Expected: collection error (`app.graph` missing).

- [ ] **Step 7: Implement constants, schemas, repository, service**

Create `backend/app/graph/__init__.py` (empty). Create `backend/app/graph/constant.py`:

```python
NODE_LABELS = (
    "Customer", "Person", "Contract", "PricingCategory", "ProductFamily", "SKU", "Project", "Site",
    "QuoteRequest", "Quote", "GraphMeta",
)
EDGE_TYPES = (
    "WORKS_FOR", "HOLDS", "COVERS", "IN_FAMILY", "REPLACED_BY", "PRICED_IN", "REQUIRES", "HAS_PROJECT", "AT_SITE",
    "FOR_PROJECT", "DUPLICATE_OF", "REVISION_OF", "VARIANT_OF", "SUPERSEDES", "PRICE_VARIANCE",
)
BATCH_SIZE = 1000
# A REPLACED_BY chain longer than this is treated as unresolvable: the run ends for review instead of walking on.
MAX_CHAIN_HOPS = 10
```

Create `backend/app/graph/schemas.py`:

```python
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RebuildSummary:
    namespace: str
    fingerprint: str
    node_counts: dict[str, int] = field(default_factory=dict)
    edge_counts: dict[str, int] = field(default_factory=dict)
```

Create `backend/app/graph/repository.py`:

```python
from collections.abc import Iterator

from app.graph.constant import BATCH_SIZE, EDGE_TYPES, NODE_LABELS
from core.graph.client import GraphClient


def node_key(ns: str, node_id: str) -> str:
    return f"{ns}:{node_id}"


def _require(name: str, allowed: tuple[str, ...], kind: str) -> None:
    # Labels and relationship types cannot be Cypher parameters, so they are interpolated. Only known names pass.
    if name not in allowed:
        raise ValueError(f"unknown graph {kind} {name!r}")


def _batches(rows: list[dict]) -> Iterator[list[dict]]:
    for start in range(0, len(rows), BATCH_SIZE):
        yield rows[start:start + BATCH_SIZE]


def drop_namespace(client: GraphClient, ns: str) -> None:
    client.write("MATCH (n {ns: $ns}) DETACH DELETE n", ns=ns)


def ensure_constraints(client: GraphClient) -> None:
    # Community edition has no composite node keys, so uniqueness is enforced on the namespaced `key` property.
    for label in NODE_LABELS:
        client.write(f"CREATE CONSTRAINT {label.lower()}_key IF NOT EXISTS FOR (n:{label}) REQUIRE n.key IS UNIQUE")


def merge_nodes(client: GraphClient, ns: str, label: str, rows: list[dict]) -> None:
    _require(label, NODE_LABELS, "label")
    query = f"UNWIND $rows AS row MERGE (n:{label} {{key: row.key}}) SET n.ns = $ns, n.id = row.id SET n += row.props"
    for batch in _batches(rows):
        client.write(
            query, ns=ns,
            rows=[{"key": node_key(ns, r["id"]), "id": r["id"], "props": r["props"]} for r in batch],
        )


def merge_edges(
    client: GraphClient, ns: str, edge_type: str, from_label: str, to_label: str, rows: list[dict],
) -> None:
    _require(edge_type, EDGE_TYPES, "edge type")
    _require(from_label, NODE_LABELS, "label")
    _require(to_label, NODE_LABELS, "label")
    query = (
        f"UNWIND $rows AS row MATCH (a:{from_label} {{key: row.source}}) MATCH (b:{to_label} {{key: row.target}}) "
        f"MERGE (a)-[r:{edge_type}]->(b) SET r += row.props"
    )
    for batch in _batches(rows):
        client.write(
            query,
            rows=[{"source": node_key(ns, r["from"]), "target": node_key(ns, r["to"]), "props": r["props"]} for r in batch],
        )


def count_nodes_by_label(client: GraphClient, ns: str) -> dict[str, int]:
    rows = client.read(
        "MATCH (n {ns: $ns}) UNWIND labels(n) AS label RETURN label, count(n) AS count ORDER BY label", ns=ns,
    )
    return {row["label"]: row["count"] for row in rows}


def count_edges_by_type(client: GraphClient, ns: str) -> dict[str, int]:
    rows = client.read(
        "MATCH ({ns: $ns})-[r]->() RETURN type(r) AS type, count(r) AS count ORDER BY type", ns=ns,
    )
    return {row["type"]: row["count"] for row in rows}
```

Create `backend/app/graph/service.py`:

```python
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.graph.repository import drop_namespace, ensure_constraints, merge_edges, merge_nodes
from app.reference_data.repository import (
    all_contacts, all_contracts, all_customers, all_families, all_projects, all_requirements, all_sites, all_skus,
    reference_fingerprint,
)
from core.graph.client import GraphClient


def _edge(source: str, target: str) -> dict:
    return {"from": source, "to": target, "props": {}}


def rebuild_reference_graph(session: Session, client: GraphClient, ns: str) -> None:
    """Wipe and reload the reference part of one namespace from Postgres. Idempotent."""
    skus = all_skus(session)
    contracts = all_contracts(session)
    projects = all_projects(session)
    contacts = all_contacts(session)

    drop_namespace(client, ns)
    ensure_constraints(client)

    # A contract can cover a category no SKU uses; the node must exist for the COVERS edge.
    categories = sorted({s.category for s in skus} | {c for k in contracts for c in k.covered_categories})
    merge_nodes(client, ns, "PricingCategory", [{"id": c, "props": {}} for c in categories])
    merge_nodes(client, ns, "ProductFamily", [{"id": f.family_id, "props": {"name": f.name}} for f in all_families(session)])
    merge_nodes(client, ns, "SKU", [
        {"id": s.sku_id, "props": {
            "name": s.name, "category": s.category, "list_price": s.list_price,
            "discontinued": s.discontinued, "in_stock": s.in_stock,
        }} for s in skus
    ])
    merge_nodes(client, ns, "Customer", [
        {"id": c.customer_id, "props": {"name": c.name, "account_tier": c.account_tier}} for c in all_customers(session)
    ])
    merge_nodes(client, ns, "Person", [
        {"id": p.contact_id, "props": {"name": p.name, "email": p.email, "phone": p.phone}} for p in contacts
    ])
    merge_nodes(client, ns, "Contract", [
        {"id": k.contract_id, "props": {
            "discount_pct": k.discount_pct, "discount_category": k.discount_category,
            "effective_from": k.effective_from.isoformat(), "effective_to": k.effective_to.isoformat(),
        }} for k in contracts
    ])
    merge_nodes(client, ns, "Site", [
        {"id": s.site_id, "props": {"address": s.address, "zip": s.zip}} for s in all_sites(session)
    ])
    merge_nodes(client, ns, "Project", [{"id": p.project_id, "props": {"name": p.name}} for p in projects])

    merge_edges(client, ns, "WORKS_FOR", "Person", "Customer", [_edge(p.contact_id, p.customer_id) for p in contacts])
    merge_edges(client, ns, "HOLDS", "Customer", "Contract", [_edge(k.customer_id, k.contract_id) for k in contracts])
    merge_edges(client, ns, "COVERS", "Contract", "PricingCategory", [
        _edge(k.contract_id, category) for k in contracts for category in k.covered_categories
    ])
    merge_edges(client, ns, "IN_FAMILY", "SKU", "ProductFamily", [_edge(s.sku_id, s.family_id) for s in skus if s.family_id])
    merge_edges(client, ns, "REPLACED_BY", "SKU", "SKU", [_edge(s.sku_id, s.replaced_by) for s in skus if s.replaced_by])
    merge_edges(client, ns, "PRICED_IN", "SKU", "PricingCategory", [_edge(s.sku_id, s.category) for s in skus])
    merge_edges(client, ns, "REQUIRES", "SKU", "SKU", [
        _edge(r.sku_id, r.required_sku_id) for r in all_requirements(session)
    ])
    merge_edges(client, ns, "HAS_PROJECT", "Customer", "Project", [_edge(p.customer_id, p.project_id) for p in projects])
    merge_edges(client, ns, "AT_SITE", "Project", "Site", [_edge(p.project_id, p.site_id) for p in projects])

    merge_nodes(client, ns, "GraphMeta", [{"id": ns, "props": {
        "reference_fingerprint": reference_fingerprint(session),
        "built_at": datetime.now(timezone.utc).isoformat(),
    }}])
```

- [ ] **Step 8: Run to verify pass**

Run: `pytest tests/app/graph tests/app/reference_data -v`. Expected: PASS. Then confirm the teardown left nothing behind: run `graph_client.read("MATCH (n) WHERE n.ns STARTS WITH 'test-' RETURN count(n) AS c")` in a one-off Python shell; it must be 0.

- [ ] **Step 9: Commit**

```bash
git add backend/app/graph/__init__.py backend/app/graph/constant.py backend/app/graph/schemas.py backend/app/graph/repository.py backend/app/graph/service.py backend/app/reference_data/repository.py backend/tests/app/estimate/seed.py backend/tests/app/graph/__init__.py backend/tests/app/graph/test_rebuild.py backend/tests/app/reference_data/test_fingerprint.py
git commit -m "feat: project Postgres reference data into a namespaced Neo4j graph with a freshness fingerprint"
```

---

### Task 5: GraphReader (chain, required parts, contract coverage) and graph test support

**Files:**
- Create: `backend/app/graph/reader.py`, `backend/tests/graph_support.py`, `backend/tests/app/graph/test_reader.py`
- Modify: `backend/app/graph/repository.py`, `backend/app/graph/schemas.py`, `backend/tests/conftest.py`, `backend/tests/app/estimate/seed.py`

**Interfaces:**
- Consumes: Task 4 repository and `rebuild_reference_graph`.
- Produces:
  - `app.graph.schemas`: `ChainNode(sku_id, name, discontinued, in_stock)`; `SkuChain(nodes: tuple[ChainNode, ...], live_end: ChainNode | None)` with `.sku_id` and `.evidence_path -> list[str]`; `RequiredPart(sku_id, name, discontinued, in_stock)`; `ContractCoverage(contract_id, discount_pct, effective_from, effective_to, sku_category, covered_categories, covered, active_on_as_of)`.
  - `app.graph.reader.GraphReader(client, ns)` with public `.client` and `.ns`; `.sku_chain(sku_id) -> SkuChain | None` (None when the SKU is not in the graph); `.required_parts(sku_id) -> list[RequiredPart]`; `.contract_coverage(customer_id, sku_id, as_of: date) -> list[ContractCoverage]` (one row per contract the customer holds; `sku_category` is None when the SKU is unknown); `.stored_fingerprint() -> str | None`.
  - `tests.graph_support.build_reader(session, client, ns) -> GraphReader`; `tests.graph_support.UnusedGraph`; fixture `make_reader` (a callable returning `build_reader(db_session, graph_client, graph_ns)`) in `tests/conftest.py`.
  - `tests.app.estimate.seed.seed_chain_world(session)`.

- [ ] **Step 1: Add the chain seed**

Append to `backend/tests/app/estimate/seed.py` (add `from app.reference_data.models import Sku` at the top; `upsert_requirement` is already imported):

```python
def seed_chain_world(session) -> None:
    """Extends seed_world with the chains the graph must walk.

    SKU-E-OLD2 (discontinued) replaced by SKU-E-OLD (discontinued) replaced by live SKU-E-A1. SKU-E-DEAD is
    discontinued with no replacement. SKU-E-CYC1 and SKU-E-CYC2 are discontinued and replace each other.
    SKU-E-D0 .. SKU-E-D11 is a discontinued chain ending at SKU-E-A1, 12 hops from D0 and past the 10-hop bound.
    SKU-E-NEEDOLD is live and requires the discontinued SKU-E-OLD."""
    deep_ids = [f"SKU-E-D{i}" for i in range(12)]
    for sku_id in ("SKU-E-OLD2", "SKU-E-DEAD", "SKU-E-CYC1", "SKU-E-CYC2", *deep_ids):
        _sku(session, sku_id, sku_id, "Cat-E-A", 5.0, discontinued=True, in_stock=False)
    _sku(session, "SKU-E-NEEDOLD", "Needs An Old Part", "Cat-E-B", 7.0)
    session.flush()

    links = {"SKU-E-OLD2": "SKU-E-OLD", "SKU-E-CYC1": "SKU-E-CYC2", "SKU-E-CYC2": "SKU-E-CYC1"}
    links.update({deep_ids[i]: deep_ids[i + 1] for i in range(11)})
    links[deep_ids[11]] = "SKU-E-A1"
    for sku_id, target in links.items():
        session.get(Sku, sku_id).replaced_by = target
    upsert_requirement(session, sku_id="SKU-E-NEEDOLD", required_sku_id="SKU-E-OLD")
    session.flush()
```

- [ ] **Step 2: Add test support and the fixture**

Create `backend/tests/graph_support.py`:

```python
from app.graph.reader import GraphReader
from app.graph.service import rebuild_reference_graph


def build_reader(session, client, ns) -> GraphReader:
    """Rebuild the reference graph for the rows visible to this session (including uncommitted test rows) into the
    test namespace and return a reader over it. Call after seeding."""
    rebuild_reference_graph(session, client, ns)
    return GraphReader(client, ns)


class UnusedGraph:
    """Stands in for the graph in tests that must not touch it; any use fails loudly."""

    def __getattr__(self, name):
        raise AssertionError(f"graph.{name} was used by a test that declared the graph unused")
```

Append to `backend/tests/conftest.py`:

```python
from tests.graph_support import build_reader


@pytest.fixture
def make_reader(db_session, graph_client, graph_ns):
    def _make():
        return build_reader(db_session, graph_client, graph_ns)

    return _make
```

(`tests/graph_support.py` imports `app.graph.reader`, created in step 5; the fixture import only works after step 5. Do steps 3 to 5 before running anything.)

- [ ] **Step 3: Write the failing reader tests**

Create `backend/tests/app/graph/test_reader.py`:

```python
from datetime import date

from app.graph.constant import MAX_CHAIN_HOPS
from app.reference_data.repository import reference_fingerprint
from tests.app.estimate.seed import AS_OF, seed_chain_world, seed_world


def _reader(db_session, make_reader):
    seed_world(db_session)
    seed_chain_world(db_session)
    return make_reader()


def test_a_live_sku_is_its_own_live_end(db_session, make_reader):
    chain = _reader(db_session, make_reader).sku_chain("SKU-E-A1")

    assert [n.sku_id for n in chain.nodes] == ["SKU-E-A1"]
    assert chain.live_end.sku_id == "SKU-E-A1"
    assert chain.evidence_path == ["SKU-E-A1"]


def test_a_discontinued_sku_walks_to_its_live_replacement(db_session, make_reader):
    chain = _reader(db_session, make_reader).sku_chain("SKU-E-OLD")

    assert [n.sku_id for n in chain.nodes] == ["SKU-E-OLD", "SKU-E-A1"]
    assert chain.nodes[0].discontinued is True and chain.nodes[0].in_stock is False
    assert chain.live_end.sku_id == "SKU-E-A1"
    assert chain.sku_id == "SKU-E-OLD"
    assert chain.evidence_path == ["SKU-E-OLD", "REPLACED_BY", "SKU-E-A1"]


def test_a_two_hop_chain_reaches_the_live_end(db_session, make_reader):
    chain = _reader(db_session, make_reader).sku_chain("SKU-E-OLD2")

    assert [n.sku_id for n in chain.nodes] == ["SKU-E-OLD2", "SKU-E-OLD", "SKU-E-A1"]
    assert chain.live_end.sku_id == "SKU-E-A1"
    assert chain.evidence_path == ["SKU-E-OLD2", "REPLACED_BY", "SKU-E-OLD", "REPLACED_BY", "SKU-E-A1"]


def test_a_discontinued_sku_with_no_replacement_has_no_live_end(db_session, make_reader):
    chain = _reader(db_session, make_reader).sku_chain("SKU-E-DEAD")

    assert [n.sku_id for n in chain.nodes] == ["SKU-E-DEAD"]
    assert chain.live_end is None


def test_a_replacement_cycle_terminates_with_no_live_end(db_session, make_reader):
    """(Review Focus) A replaced by B replaced by A must not loop forever."""
    chain = _reader(db_session, make_reader).sku_chain("SKU-E-CYC1")

    assert chain.live_end is None
    assert {n.sku_id for n in chain.nodes} == {"SKU-E-CYC1", "SKU-E-CYC2"}


def test_a_chain_past_the_hop_bound_is_treated_as_unresolvable(db_session, make_reader):
    """(Review Focus) D0 reaches the live SKU only after 12 hops; the bound is 10."""
    chain = _reader(db_session, make_reader).sku_chain("SKU-E-D0")

    assert MAX_CHAIN_HOPS == 10
    assert chain.live_end is None
    assert len(chain.nodes) == MAX_CHAIN_HOPS + 1


def test_a_chain_within_the_hop_bound_is_resolved_from_the_middle(db_session, make_reader):
    chain = _reader(db_session, make_reader).sku_chain("SKU-E-D5")

    assert chain.live_end.sku_id == "SKU-E-A1"


def test_an_unknown_sku_has_no_chain(db_session, make_reader):
    assert _reader(db_session, make_reader).sku_chain("SKU-NOPE") is None


def test_required_parts_lists_direct_requirements_with_their_status(db_session, make_reader):
    reader = _reader(db_session, make_reader)

    assert [(p.sku_id, p.discontinued) for p in reader.required_parts("SKU-E-B1")] == [("SKU-E-A1", False)]
    assert [(p.sku_id, p.discontinued, p.in_stock) for p in reader.required_parts("SKU-E-NEEDOLD")] == [
        ("SKU-E-OLD", True, False),
    ]
    assert reader.required_parts("SKU-E-A1") == []
    assert reader.required_parts("SKU-NOPE") == []


def test_contract_coverage_says_covered_and_active(db_session, make_reader):
    coverage = _reader(db_session, make_reader).contract_coverage("CUST-E1", "SKU-E-A1", AS_OF)

    assert len(coverage) == 1
    row = coverage[0]
    assert (row.contract_id, row.discount_pct, row.sku_category) == ("CTR-E1", 10.0, "Cat-E-A")
    assert row.covered is True and row.active_on_as_of is True
    assert row.covered_categories == ("Cat-E-A",)


def test_contract_coverage_says_uncovered_for_another_category(db_session, make_reader):
    row = _reader(db_session, make_reader).contract_coverage("CUST-E1", "SKU-E-B1", AS_OF)[0]

    assert row.covered is False
    assert row.sku_category == "Cat-E-B"
    assert row.covered_categories == ("Cat-E-A",)


def test_contract_coverage_reports_an_inactive_contract(db_session, make_reader):
    row = _reader(db_session, make_reader).contract_coverage("CUST-E1", "SKU-E-A1", date(2026, 1, 1))[0]

    assert row.covered is True
    assert row.active_on_as_of is False


def test_contract_coverage_is_empty_for_a_customer_without_contracts(db_session, make_reader):
    assert _reader(db_session, make_reader).contract_coverage("CUST-E2", "SKU-E-A1", AS_OF) == []


def test_contract_coverage_for_an_unknown_sku_has_no_category(db_session, make_reader):
    row = _reader(db_session, make_reader).contract_coverage("CUST-E1", "SKU-NOPE", AS_OF)[0]

    assert row.sku_category is None
    assert row.covered is False


def test_stored_fingerprint_matches_postgres_after_a_build(db_session, make_reader):
    reader = _reader(db_session, make_reader)

    assert reader.stored_fingerprint() == reference_fingerprint(db_session)


def test_stored_fingerprint_is_none_before_any_build(graph_client, graph_ns):
    from app.graph.reader import GraphReader

    assert GraphReader(graph_client, graph_ns).stored_fingerprint() is None
```

- [ ] **Step 4: Run to verify failure**

Run: `pytest tests/app/graph/test_reader.py -v`. Expected: collection error (`app.graph.reader` missing; it also breaks `tests/conftest.py`, so every test errors until step 5).

- [ ] **Step 5: Implement schemas, Cypher, and the reader**

Append to `backend/app/graph/schemas.py`:

```python
@dataclass(frozen=True)
class ChainNode:
    sku_id: str
    name: str
    discontinued: bool
    in_stock: bool


@dataclass(frozen=True)
class SkuChain:
    # The SKU asked about first, then one node per REPLACED_BY hop.
    nodes: tuple[ChainNode, ...]
    # The first node in the chain that is not discontinued, or None when the chain never reaches a live SKU.
    live_end: ChainNode | None

    @property
    def sku_id(self) -> str:
        return self.nodes[0].sku_id

    @property
    def evidence_path(self) -> list[str]:
        """Node ids and edge types from the asked SKU to its live end (or to the last node reached)."""
        end = self.nodes.index(self.live_end) if self.live_end is not None else len(self.nodes) - 1
        path: list[str] = []
        for node in self.nodes[: end + 1]:
            if path:
                path.append("REPLACED_BY")
            path.append(node.sku_id)
        return path


@dataclass(frozen=True)
class RequiredPart:
    sku_id: str
    name: str
    discontinued: bool
    in_stock: bool


@dataclass(frozen=True)
class ContractCoverage:
    contract_id: str
    discount_pct: float
    effective_from: str
    effective_to: str
    sku_category: str | None
    covered_categories: tuple[str, ...]
    covered: bool
    active_on_as_of: bool
```

Append to `backend/app/graph/repository.py` (add `MAX_CHAIN_HOPS` to the `app.graph.constant` import):

```python
def fetch_sku_chain(client: GraphClient, ns: str, sku_id: str) -> list[dict] | None:
    """The longest REPLACED_BY path (at most MAX_CHAIN_HOPS hops) from a SKU, as node dicts. Relationships are
    never repeated inside a path, so a cycle ends the walk instead of looping."""
    rows = client.read(
        f"MATCH path = (s:SKU {{key: $key}})-[:REPLACED_BY*0..{MAX_CHAIN_HOPS}]->(e:SKU) "
        "RETURN [n IN nodes(path) | {id: n.id, name: n.name, discontinued: n.discontinued, in_stock: n.in_stock}] "
        "AS chain ORDER BY length(path) DESC LIMIT 1",
        key=node_key(ns, sku_id),
    )
    return rows[0]["chain"] if rows else None


def fetch_required_parts(client: GraphClient, ns: str, sku_id: str) -> list[dict]:
    return client.read(
        "MATCH (s:SKU {key: $key})-[:REQUIRES]->(r:SKU) "
        "RETURN r.id AS id, r.name AS name, r.discontinued AS discontinued, r.in_stock AS in_stock ORDER BY r.id",
        key=node_key(ns, sku_id),
    )


def fetch_contract_coverage(client: GraphClient, ns: str, customer_id: str, sku_id: str) -> list[dict]:
    return client.read(
        "MATCH (c:Customer {key: $customer_key})-[:HOLDS]->(k:Contract) "
        "OPTIONAL MATCH (s:SKU {key: $sku_key})-[:PRICED_IN]->(sc:PricingCategory) "
        "RETURN k.id AS contract_id, k.discount_pct AS discount_pct, k.effective_from AS effective_from, "
        "k.effective_to AS effective_to, sc.id AS sku_category, "
        "COLLECT { MATCH (k)-[:COVERS]->(x:PricingCategory) RETURN x.id ORDER BY x.id } AS covered_categories, "
        "(sc IS NOT NULL AND EXISTS { (k)-[:COVERS]->(sc) }) AS covered ORDER BY k.id",
        customer_key=node_key(ns, customer_id), sku_key=node_key(ns, sku_id),
    )


def fetch_fingerprint(client: GraphClient, ns: str) -> str | None:
    rows = client.read(
        "MATCH (m:GraphMeta {key: $key}) RETURN m.reference_fingerprint AS fingerprint", key=node_key(ns, ns),
    )
    return rows[0]["fingerprint"] if rows else None
```

Create `backend/app/graph/reader.py`:

```python
from datetime import date

from app.graph import repository
from app.graph.schemas import ChainNode, ContractCoverage, RequiredPart, SkuChain
from core.graph.client import GraphClient


class GraphReader:
    """Read-only, namespace-scoped view of the graph for the agent tools and guardrails."""

    def __init__(self, client: GraphClient, ns: str) -> None:
        self.client = client
        self.ns = ns

    def sku_chain(self, sku_id: str) -> SkuChain | None:
        raw = repository.fetch_sku_chain(self.client, self.ns, sku_id)
        if raw is None:
            return None
        nodes = tuple(
            ChainNode(sku_id=n["id"], name=n["name"], discontinued=bool(n["discontinued"]), in_stock=bool(n["in_stock"]))
            for n in raw
        )
        live_end = next((node for node in nodes if not node.discontinued), None)
        return SkuChain(nodes=nodes, live_end=live_end)

    def required_parts(self, sku_id: str) -> list[RequiredPart]:
        return [
            RequiredPart(sku_id=r["id"], name=r["name"], discontinued=bool(r["discontinued"]), in_stock=bool(r["in_stock"]))
            for r in repository.fetch_required_parts(self.client, self.ns, sku_id)
        ]

    def contract_coverage(self, customer_id: str, sku_id: str, as_of: date) -> list[ContractCoverage]:
        today = as_of.isoformat()
        return [
            ContractCoverage(
                contract_id=r["contract_id"], discount_pct=r["discount_pct"], effective_from=r["effective_from"],
                effective_to=r["effective_to"], sku_category=r["sku_category"],
                covered_categories=tuple(r["covered_categories"]), covered=bool(r["covered"]),
                active_on_as_of=r["effective_from"] <= today <= r["effective_to"],
            )
            for r in repository.fetch_contract_coverage(self.client, self.ns, customer_id, sku_id)
        ]

    def stored_fingerprint(self) -> str | None:
        return repository.fetch_fingerprint(self.client, self.ns)
```

- [ ] **Step 6: Run to verify pass**

Run: `pytest tests/app/graph -v`, then the full suite `pytest -q`. Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/graph/reader.py backend/app/graph/repository.py backend/app/graph/schemas.py backend/tests/graph_support.py backend/tests/conftest.py backend/tests/app/estimate/seed.py backend/tests/app/graph/test_reader.py
git commit -m "feat: add a graph reader for replacement chains, required parts, and contract coverage"
```

---

---

### Task 6: Runtime sync (quote requests, dedupe edges, quotes), full rebuild, route hooks

**Files:**
- Create: `backend/app/graph/helper.py`, `backend/tests/app/graph/test_helper.py`, `backend/tests/app/graph/test_sync.py`
- Modify: `backend/app/graph/constant.py`, `backend/app/graph/repository.py`, `backend/app/graph/service.py`, `backend/app/intake/repository.py`, `backend/app/dedupe/repository.py`, `backend/app/estimate/repository.py`, `backend/api/v1/intake/route.py`, `backend/api/v1/dedupe/route.py`, `backend/tests/graph_support.py`, `backend/tests/app/graph/test_rebuild.py`, `backend/tests/api/v1/test_intake_route.py`, `backend/tests/api/v1/test_dedupe_route.py`

**Interfaces:**
- Consumes: Tasks 4 and 5 (`merge_nodes`, `merge_edges`, `node_key`, `rebuild_reference_graph`, `reference_fingerprint`, `count_*`), Task 3 (`project_for_site`, `sites_for_customer`, `get_sku`).
- Produces:
  - `app.graph.constant.VARIANT_MIN_JACCARD = 0.2`.
  - `app.graph.helper.match_site(hint: str, sites) -> str | None` (objects with `.site_id`, `.address`, `.zip`).
  - `app.graph.repository.replace_price_variance(client, ns, quote_id, rows)` with `rows = [{"sku_id": str, "props": dict}]`.
  - `app.intake.repository.all_quote_request_ids(session) -> list[uuid.UUID]` (by `created_at`), `app.dedupe.repository.verdicts_for_request(session, quote_request_id) -> list[DedupeVerdictRow]` and `all_verdict_request_ids(session) -> list[uuid.UUID]`, `app.estimate.repository.all_estimate_draft_ids(session)` (by `created_at`) and `previous_estimate_draft(session, row) -> EstimateDraftRow | None` (strictly earlier `created_at`, same quote request, latest first).
  - `app.graph.service`: `sync_quote_request(session, client, ns, quote_request_id)`, `sync_dedupe_verdicts(session, client, ns, quote_request_id)`, `sync_quote(session, client, ns, estimate_id)`, `rebuild_graph(session, client, ns) -> RebuildSummary`, `sync_best_effort(description, sync, *args) -> None`. Sync functions raise `ValueError` for an unknown id.
  - `tests.graph_support.graph_node(client, ns, node_id) -> dict | None` (keys `labels`, `props`), `graph_edge_count(client, ns, source, edge_type, target) -> int`, `FailingGraphClient` (every call raises `GraphUnavailable`).

- [ ] **Step 1: Move the test helpers and add the failing client**

In `backend/tests/graph_support.py` add (and add `from app.graph.repository import node_key` and `from core.graph.client import GraphUnavailable` to the imports):

```python
def graph_node(client, ns, node_id):
    rows = client.read(
        "MATCH (n {key: $key}) RETURN labels(n) AS labels, properties(n) AS props", key=node_key(ns, node_id)
    )
    return rows[0] if rows else None


def graph_edge_count(client, ns, source, edge_type, target) -> int:
    rows = client.read(
        "MATCH ({key: $source})-[r]->({key: $target}) WHERE type(r) = $type RETURN count(r) AS count",
        source=node_key(ns, source), target=node_key(ns, target), type=edge_type,
    )
    return rows[0]["count"]


class FailingGraphClient:
    """A graph client whose server is down."""

    def read(self, query, **params):
        raise GraphUnavailable("Neo4j is unavailable: test double")

    def write(self, query, **params):
        raise GraphUnavailable("Neo4j is unavailable: test double")
```

In `backend/tests/app/graph/test_rebuild.py` delete the local `_node` and `_edges` functions, import `graph_edge_count` and `graph_node` from `tests.graph_support`, and replace their call sites (`_node(` becomes `graph_node(`, `_edges(` becomes `graph_edge_count(`). Run `pytest tests/app/graph/test_rebuild.py -v`; it must still pass.

- [ ] **Step 2: Write the failing helper tests**

Create `backend/tests/app/graph/test_helper.py`:

```python
from types import SimpleNamespace

from app.graph.helper import match_site

SITES = [
    SimpleNamespace(site_id="SITE-1", address="12 Elm Street, Springfield, IL", zip="62701"),
    SimpleNamespace(site_id="SITE-2", address="12 Elm Street, Portland, OR", zip="97201"),
    SimpleNamespace(site_id="SITE-3", address="9 Oak Avenue, Austin, TX", zip="73301"),
]


def test_a_zip_in_the_hint_picks_that_site():
    assert match_site("job over at 62701 next week", SITES) == "SITE-1"


def test_a_unique_street_in_the_hint_picks_that_site():
    assert match_site("the 9 oak avenue job", SITES) == "SITE-3"


def test_matching_is_case_insensitive():
    assert match_site("9 OAK AVENUE", SITES) == "SITE-3"


def test_a_street_shared_by_two_sites_is_ambiguous():
    assert match_site("12 Elm Street", SITES) is None


def test_a_street_plus_a_zip_that_agree_is_still_one_site():
    assert match_site("12 Elm Street, 97201", SITES) == "SITE-2"


def test_a_hint_naming_two_different_sites_is_ambiguous():
    assert match_site("62701 or maybe 73301", SITES) is None


def test_a_hint_naming_no_site_matches_nothing():
    assert match_site("the downtown project", SITES) is None
    assert match_site("", SITES) is None


def test_no_sites_matches_nothing():
    assert match_site("62701", []) is None
```

- [ ] **Step 3: Implement the helper and run**

Create `backend/app/graph/helper.py`:

```python
def match_site(hint: str, sites) -> str | None:
    """The one site a free-text hint points at, by zip or street; None when it names none or several."""
    text = hint.lower()
    matches = [site.site_id for site in sites if _mentions(text, site)]
    return matches[0] if len(matches) == 1 else None


def _mentions(text: str, site) -> bool:
    street = site.address.split(",")[0].strip().lower()
    return site.zip in text or (street != "" and street in text)
```

Run: `pytest tests/app/graph/test_helper.py -v`. Expected: PASS.

- [ ] **Step 4: Write the failing sync tests**

Create `backend/tests/app/graph/test_sync.py`:

```python
import logging
import uuid
from datetime import datetime, timezone

import pytest

from app.dedupe.repository import save_verdict
from app.estimate.models import EstimateDraftRow
from app.graph.constant import VARIANT_MIN_JACCARD
from app.graph.repository import node_key
from app.graph.service import (
    rebuild_graph, sync_best_effort, sync_dedupe_verdicts, sync_quote, sync_quote_request,
)
from app.intake.repository import save_quote_request
from app.reference_data.repository import reference_fingerprint
from core.graph.client import GraphUnavailable
from tests.app.estimate.seed import seed_structure, seed_world
from tests.graph_support import FailingGraphClient, graph_edge_count, graph_node


def _world(db_session, make_reader):
    seed_world(db_session)
    seed_structure(db_session)
    return make_reader()


def _request(session, *, customer_id="CUST-E1", hint=None, site_id=None, case_id=None):
    extraction = {"site_hint": hint} if hint else {}
    return save_quote_request(
        session, raw_email_text="x", parsed_json={"extraction": extraction, "resolved_line_items": []},
        content_fingerprint={"sku_ids": ["SKU-E-A1"]}, style_fingerprint={"tokens": []},
        customer_id=customer_id, site_id=site_id, case_id=case_id,
    )


def _draft_row(session, request_id, created_at, draft, status="ready"):
    row = EstimateDraftRow(
        id=uuid.uuid4(), quote_request_id=request_id, status=status, draft=draft, violations=[], iterations=1,
        reason=None, created_at=created_at,
    )
    session.add(row)
    session.flush()
    return row


def _line(sku_id, unit_price, discount_pct=0.0, price_source="list"):
    return {"sku_id": sku_id, "quantity": 1, "unit_price": unit_price, "price_source": price_source,
            "discount_pct": discount_pct}


T1 = datetime(2024, 9, 1, 9, 0, tzinfo=timezone.utc)
T2 = datetime(2024, 9, 1, 10, 0, tzinfo=timezone.utc)


def test_sync_quote_request_creates_the_node(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    row = _request(db_session, case_id="sc-9")

    sync_quote_request(db_session, graph_client, graph_ns, row.id)

    node = graph_node(graph_client, graph_ns, str(row.id))
    assert node["labels"] == ["QuoteRequest"]
    assert node["props"]["case_id"] == "sc-9"


def test_a_zip_in_the_site_hint_links_the_request_to_that_sites_project(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    row = _request(db_session, hint="the job at 62701")

    sync_quote_request(db_session, graph_client, graph_ns, row.id)

    assert graph_edge_count(graph_client, graph_ns, str(row.id), "FOR_PROJECT", "PRJ-E1") == 1


def test_an_ambiguous_site_hint_links_nothing(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    row = _request(db_session, hint="12 Elm Street")

    sync_quote_request(db_session, graph_client, graph_ns, row.id)

    assert graph_edge_count(graph_client, graph_ns, str(row.id), "FOR_PROJECT", "PRJ-E1") == 0
    assert graph_edge_count(graph_client, graph_ns, str(row.id), "FOR_PROJECT", "PRJ-E2") == 0


def test_no_hint_or_no_customer_links_nothing(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    no_hint = _request(db_session)
    no_customer = _request(db_session, customer_id=None, hint="62701")

    sync_quote_request(db_session, graph_client, graph_ns, no_hint.id)
    sync_quote_request(db_session, graph_client, graph_ns, no_customer.id)

    for row in (no_hint, no_customer):
        assert graph_edge_count(graph_client, graph_ns, str(row.id), "FOR_PROJECT", "PRJ-E1") == 0


def test_a_resolved_site_id_wins_over_the_hint(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    row = _request(db_session, hint="62701", site_id="SITE-E2")

    sync_quote_request(db_session, graph_client, graph_ns, row.id)

    assert graph_edge_count(graph_client, graph_ns, str(row.id), "FOR_PROJECT", "PRJ-E2") == 1
    assert graph_edge_count(graph_client, graph_ns, str(row.id), "FOR_PROJECT", "PRJ-E1") == 0


def test_sync_quote_request_is_idempotent(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    row = _request(db_session, hint="62701")

    sync_quote_request(db_session, graph_client, graph_ns, row.id)
    sync_quote_request(db_session, graph_client, graph_ns, row.id)

    assert graph_edge_count(graph_client, graph_ns, str(row.id), "FOR_PROJECT", "PRJ-E1") == 1
    nodes = graph_client.read("MATCH (n:QuoteRequest {key: $key}) RETURN count(n) AS c", key=node_key(graph_ns, str(row.id)))
    assert nodes == [{"c": 1}]


def test_sync_quote_request_rejects_an_unknown_id(db_session, graph_client, graph_ns):
    with pytest.raises(ValueError):
        sync_quote_request(db_session, graph_client, graph_ns, uuid.uuid4())


def _pair(db_session, *, other_customer="CUST-E1"):
    target = _request(db_session)
    candidate = _request(db_session, customer_id=other_customer)
    return target, candidate


def _verdict(db_session, target, candidate, verdict, jaccard):
    save_verdict(
        db_session, quote_request_id=target.id, candidate_quote_request_id=candidate.id, verdict=verdict,
        content_jaccard=jaccard, style_jaccard=0.0, signals_fired=[],
    )


def test_duplicate_and_revision_verdicts_become_edges_with_their_score(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    target, duplicate = _pair(db_session)
    revision = _request(db_session)
    _verdict(db_session, target, duplicate, "DUPLICATE_OF", 1.0)
    _verdict(db_session, target, revision, "REVISION_OF", 0.5)

    sync_dedupe_verdicts(db_session, graph_client, graph_ns, target.id)

    assert graph_edge_count(graph_client, graph_ns, str(target.id), "DUPLICATE_OF", str(duplicate.id)) == 1
    assert graph_edge_count(graph_client, graph_ns, str(target.id), "REVISION_OF", str(revision.id)) == 1
    scores = graph_client.read(
        "MATCH ({key: $key})-[r:DUPLICATE_OF]->() RETURN r.content_jaccard AS score", key=node_key(graph_ns, str(target.id)),
    )
    assert scores == [{"score": 1.0}]


def test_a_same_customer_distinct_pair_with_enough_overlap_is_a_variant(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    target, candidate = _pair(db_session)
    _verdict(db_session, target, candidate, "DISTINCT", VARIANT_MIN_JACCARD)

    sync_dedupe_verdicts(db_session, graph_client, graph_ns, target.id)

    assert graph_edge_count(graph_client, graph_ns, str(target.id), "VARIANT_OF", str(candidate.id)) == 1


def test_a_distinct_pair_below_the_overlap_floor_is_not_a_variant(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    target, candidate = _pair(db_session)
    _verdict(db_session, target, candidate, "DISTINCT", VARIANT_MIN_JACCARD - 0.01)

    sync_dedupe_verdicts(db_session, graph_client, graph_ns, target.id)

    assert graph_edge_count(graph_client, graph_ns, str(target.id), "VARIANT_OF", str(candidate.id)) == 0


def test_a_distinct_pair_across_customers_is_never_a_variant(db_session, graph_client, graph_ns, make_reader):
    """(Review Focus) Same-looking requests from different customers are unrelated, not variants."""
    _world(db_session, make_reader)
    target, candidate = _pair(db_session, other_customer="CUST-E2")
    _verdict(db_session, target, candidate, "DISTINCT", 0.9)

    sync_dedupe_verdicts(db_session, graph_client, graph_ns, target.id)

    assert graph_edge_count(graph_client, graph_ns, str(target.id), "VARIANT_OF", str(candidate.id)) == 0


def test_sync_dedupe_verdicts_is_idempotent_and_needs_no_verdicts(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    target, candidate = _pair(db_session)
    _verdict(db_session, target, candidate, "DUPLICATE_OF", 1.0)

    sync_dedupe_verdicts(db_session, graph_client, graph_ns, target.id)
    sync_dedupe_verdicts(db_session, graph_client, graph_ns, target.id)
    sync_dedupe_verdicts(db_session, graph_client, graph_ns, candidate.id)

    assert graph_edge_count(graph_client, graph_ns, str(target.id), "DUPLICATE_OF", str(candidate.id)) == 1


def _variance(client, ns, quote_id):
    return client.read(
        "MATCH ({key: $key})-[r:PRICE_VARIANCE]->(s:SKU) RETURN s.id AS sku, properties(r) AS props ORDER BY s.id, r.line_index",
        key=node_key(ns, str(quote_id)),
    )


def test_a_quote_gets_price_variance_edges_only_for_discounted_or_predicted_lines(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    request = _request(db_session)
    draft = {"customer_id": "CUST-E1", "contract_id": "CTR-E1", "lines": [
        _line("SKU-E-A1", 100.0, discount_pct=10.0),
        _line("SKU-E-GAP", 20.0, price_source="predicted"),
        _line("SKU-E-B1", 50.0),
    ]}
    row = _draft_row(db_session, request.id, T1, draft)

    sync_quote(db_session, graph_client, graph_ns, row.id)

    node = graph_node(graph_client, graph_ns, str(row.id))
    assert node["props"]["status"] == "ready" and node["props"]["quote_request_id"] == str(request.id)
    variance = _variance(graph_client, graph_ns, row.id)
    assert [v["sku"] for v in variance] == ["SKU-E-A1", "SKU-E-GAP"]
    discounted, predicted = variance[0]["props"], variance[1]["props"]
    assert discounted["list_price"] == 100.0 and discounted["unit_price"] == 100.0
    assert discounted["discount_pct"] == 10.0 and discounted["net_unit_price"] == 90.0
    assert discounted["price_source"] == "list" and discounted["line_index"] == 0
    assert "list_price" not in predicted and predicted["price_source"] == "predicted"
    assert predicted["net_unit_price"] == 20.0


def test_syncing_a_quote_twice_does_not_duplicate_edges(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    request = _request(db_session)
    row = _draft_row(db_session, request.id, T1, {"lines": [_line("SKU-E-A1", 100.0, discount_pct=10.0)]})

    sync_quote(db_session, graph_client, graph_ns, row.id)
    sync_quote(db_session, graph_client, graph_ns, row.id)

    assert len(_variance(graph_client, graph_ns, row.id)) == 1


def test_a_quote_with_no_draft_is_just_a_node(db_session, graph_client, graph_ns, make_reader):
    """(Review Focus) The agent never submitted: draft is SQL NULL."""
    _world(db_session, make_reader)
    request = _request(db_session)
    row = _draft_row(db_session, request.id, T1, None, status="needs_review")

    sync_quote(db_session, graph_client, graph_ns, row.id)

    assert graph_node(graph_client, graph_ns, str(row.id))["props"]["status"] == "needs_review"
    assert _variance(graph_client, graph_ns, row.id) == []


def test_a_later_quote_supersedes_the_earlier_one_for_the_same_request(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    request = _request(db_session)
    other_request = _request(db_session)
    first = _draft_row(db_session, request.id, T1, {"lines": []})
    second = _draft_row(db_session, request.id, T2, {"lines": []})
    unrelated = _draft_row(db_session, other_request.id, T2, {"lines": []})

    sync_quote(db_session, graph_client, graph_ns, second.id)
    sync_quote(db_session, graph_client, graph_ns, unrelated.id)
    sync_quote(db_session, graph_client, graph_ns, first.id)

    assert graph_edge_count(graph_client, graph_ns, str(second.id), "SUPERSEDES", str(first.id)) == 1
    assert graph_edge_count(graph_client, graph_ns, str(first.id), "SUPERSEDES", str(second.id)) == 0
    assert graph_edge_count(graph_client, graph_ns, str(unrelated.id), "SUPERSEDES", str(first.id)) == 0


def test_quotes_with_identical_timestamps_do_not_supersede_each_other(db_session, graph_client, graph_ns, make_reader):
    """(Review Focus) One transaction stamps every row with the same created_at."""
    _world(db_session, make_reader)
    request = _request(db_session)
    first = _draft_row(db_session, request.id, T1, {"lines": []})
    second = _draft_row(db_session, request.id, T1, {"lines": []})

    sync_quote(db_session, graph_client, graph_ns, first.id)
    sync_quote(db_session, graph_client, graph_ns, second.id)

    assert graph_edge_count(graph_client, graph_ns, str(second.id), "SUPERSEDES", str(first.id)) == 0
    assert graph_edge_count(graph_client, graph_ns, str(first.id), "SUPERSEDES", str(second.id)) == 0


def test_sync_quote_rejects_an_unknown_id(db_session, graph_client, graph_ns):
    with pytest.raises(ValueError):
        sync_quote(db_session, graph_client, graph_ns, uuid.uuid4())


def test_rebuild_graph_restores_runtime_entities_from_postgres(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    target, candidate = _pair(db_session)
    _verdict(db_session, target, candidate, "DUPLICATE_OF", 1.0)
    draft = _draft_row(db_session, target.id, T1, {"lines": [_line("SKU-E-A1", 100.0, discount_pct=10.0)]})

    first = rebuild_graph(db_session, graph_client, graph_ns)
    second = rebuild_graph(db_session, graph_client, graph_ns)

    assert graph_edge_count(graph_client, graph_ns, str(target.id), "DUPLICATE_OF", str(candidate.id)) == 1
    assert len(_variance(graph_client, graph_ns, draft.id)) == 1
    assert first == second
    assert first.namespace == graph_ns
    assert first.fingerprint == reference_fingerprint(db_session)
    assert first.node_counts["QuoteRequest"] >= 2 and first.node_counts["Quote"] >= 1
    assert first.edge_counts["DUPLICATE_OF"] >= 1


def test_sync_best_effort_swallows_graph_errors_and_logs(caplog):
    calls = []

    def sync(*args):
        calls.append(args)
        raise GraphUnavailable("down")

    with caplog.at_level(logging.WARNING):
        sync_best_effort("quote request", sync, "a", "b")

    assert calls == [("a", "b")]
    assert "graph sync failed for quote request" in caplog.text


def test_sync_best_effort_does_not_hide_other_errors():
    def sync():
        raise RuntimeError("a real bug")

    with pytest.raises(RuntimeError):
        sync_best_effort("quote request", sync)


def test_failing_graph_client_is_a_graph_unavailable_source(db_session, graph_ns):
    seed_world(db_session)
    row = _request(db_session)

    with pytest.raises(GraphUnavailable):
        sync_quote_request(db_session, FailingGraphClient(), graph_ns, row.id)
```

- [ ] **Step 5: Run to verify failure**

Run: `pytest tests/app/graph/test_sync.py -v`. Expected: collection error (`sync_quote_request` and the repository readers do not exist).

- [ ] **Step 6: Implement repositories, constants and service**

Append to `backend/app/graph/constant.py`:

```python
# A same-customer DISTINCT pair overlapping at least this much is a variant of the earlier request. It sits below the
# classifier's CONTENT_SUPERSET_FLOOR (0.4, which makes revisions) so partial overlap that is not a superset counts.
VARIANT_MIN_JACCARD = 0.2
```

Append to `backend/app/graph/repository.py`:

```python
def replace_price_variance(client: GraphClient, ns: str, quote_id: str, rows: list[dict]) -> None:
    """Delete then recreate a quote's PRICE_VARIANCE edges, so a re-sync never duplicates them. Two lines for the
    same SKU stay two edges, which MERGE would collapse."""
    quote_key = node_key(ns, quote_id)
    client.write("MATCH ({key: $key})-[r:PRICE_VARIANCE]->() DELETE r", key=quote_key)
    if rows:
        client.write(
            "UNWIND $rows AS row MATCH (q:Quote {key: $quote_key}) MATCH (s:SKU {key: row.sku_key}) "
            "CREATE (q)-[r:PRICE_VARIANCE]->(s) SET r += row.props",
            quote_key=quote_key,
            rows=[{"sku_key": node_key(ns, r["sku_id"]), "props": r["props"]} for r in rows],
        )
```

Append to `backend/app/intake/repository.py` (add `from sqlalchemy import select`):

```python
def all_quote_request_ids(session: Session) -> list[uuid.UUID]:
    return list(session.scalars(select(QuoteRequestRow.id).order_by(QuoteRequestRow.created_at, QuoteRequestRow.id)))
```

Append to `backend/app/dedupe/repository.py`:

```python
def verdicts_for_request(session: Session, quote_request_id: uuid.UUID) -> list[DedupeVerdictRow]:
    return list(session.scalars(
        select(DedupeVerdictRow).where(DedupeVerdictRow.quote_request_id == quote_request_id)
        .order_by(DedupeVerdictRow.created_at, DedupeVerdictRow.id)
    ))


def all_verdict_request_ids(session: Session) -> list[uuid.UUID]:
    return list(session.scalars(select(DedupeVerdictRow.quote_request_id).distinct()))
```

Append to `backend/app/estimate/repository.py` (add `from sqlalchemy import select`):

```python
def all_estimate_draft_ids(session: Session) -> list[uuid.UUID]:
    return list(session.scalars(select(EstimateDraftRow.id).order_by(EstimateDraftRow.created_at, EstimateDraftRow.id)))


def previous_estimate_draft(session: Session, row: EstimateDraftRow) -> EstimateDraftRow | None:
    """The latest draft for the same quote request created strictly before this one. Equal timestamps (one
    transaction stamps every row alike) are not ordered, so they do not supersede each other."""
    return session.scalars(
        select(EstimateDraftRow)
        .where(EstimateDraftRow.quote_request_id == row.quote_request_id, EstimateDraftRow.created_at < row.created_at)
        .order_by(EstimateDraftRow.created_at.desc())
        .limit(1)
    ).first()
```

Replace the imports and append to `backend/app/graph/service.py`:

```python
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.dedupe.repository import all_verdict_request_ids, verdicts_for_request
from app.estimate.models import EstimateDraftRow
from app.estimate.repository import all_estimate_draft_ids, get_estimate_draft, previous_estimate_draft
from app.graph.constant import VARIANT_MIN_JACCARD
from app.graph.helper import match_site
from app.graph.repository import (
    count_edges_by_type, count_nodes_by_label, drop_namespace, ensure_constraints, merge_edges, merge_nodes,
    replace_price_variance,
)
from app.graph.schemas import RebuildSummary
from app.intake.models import QuoteRequestRow
from app.intake.repository import all_quote_request_ids, get_quote_request
from app.reference_data.repository import (
    all_contacts, all_contracts, all_customers, all_families, all_projects, all_requirements, all_sites, all_skus,
    get_sku, project_for_site, reference_fingerprint, sites_for_customer,
)
from core.graph.client import GraphClient, GraphError

logger = logging.getLogger(__name__)
```

```python
def _created_at(row) -> str | None:
    return row.created_at.isoformat() if row.created_at else None


def _project_for_request(session: Session, row: QuoteRequestRow) -> str | None:
    site_id = row.site_id
    if site_id is None:
        hint = (row.parsed_json.get("extraction") or {}).get("site_hint")
        if not hint or row.customer_id is None:
            return None
        site_id = match_site(hint, sites_for_customer(session, row.customer_id))
    if site_id is None:
        return None
    project = project_for_site(session, site_id)
    return project.project_id if project else None


def sync_quote_request(session: Session, client: GraphClient, ns: str, quote_request_id: uuid.UUID) -> None:
    row = get_quote_request(session, quote_request_id)
    if row is None:
        raise ValueError(f"quote request {quote_request_id} not found")
    merge_nodes(client, ns, "QuoteRequest", [
        {"id": str(row.id), "props": {"case_id": row.case_id, "created_at": _created_at(row)}},
    ])
    project_id = _project_for_request(session, row)
    if project_id is not None:
        merge_edges(client, ns, "FOR_PROJECT", "QuoteRequest", "Project", [_edge(str(row.id), project_id)])


def _verdict_edge_type(verdict, target: QuoteRequestRow, candidate: QuoteRequestRow) -> str | None:
    if verdict.verdict in ("DUPLICATE_OF", "REVISION_OF"):
        return verdict.verdict
    same_customer = target.customer_id is not None and target.customer_id == candidate.customer_id
    if verdict.verdict == "DISTINCT" and same_customer and verdict.content_jaccard >= VARIANT_MIN_JACCARD:
        return "VARIANT_OF"
    return None


def sync_dedupe_verdicts(session: Session, client: GraphClient, ns: str, quote_request_id: uuid.UUID) -> None:
    verdicts = verdicts_for_request(session, quote_request_id)
    if not verdicts:
        return
    target = get_quote_request(session, quote_request_id)
    sync_quote_request(session, client, ns, quote_request_id)
    rows_by_type: dict[str, list[dict]] = {}
    for verdict in verdicts:
        candidate = get_quote_request(session, verdict.candidate_quote_request_id)
        edge_type = _verdict_edge_type(verdict, target, candidate)
        if edge_type is None:
            continue
        sync_quote_request(session, client, ns, candidate.id)
        rows_by_type.setdefault(edge_type, []).append({
            "from": str(target.id), "to": str(candidate.id), "props": {"content_jaccard": verdict.content_jaccard},
        })
    for edge_type, rows in rows_by_type.items():
        merge_edges(client, ns, edge_type, "QuoteRequest", "QuoteRequest", rows)


def _merge_quote_node(client: GraphClient, ns: str, row: EstimateDraftRow) -> None:
    merge_nodes(client, ns, "Quote", [{"id": str(row.id), "props": {
        "quote_request_id": str(row.quote_request_id), "status": row.status, "created_at": _created_at(row),
    }}])


def _price_variance_rows(session: Session, row: EstimateDraftRow) -> list[dict]:
    rows = []
    for index, line in enumerate((row.draft or {}).get("lines", [])):
        sku_id = line.get("sku_id")
        discount = line.get("discount_pct") or 0.0
        source = line.get("price_source")
        if sku_id is None or (discount == 0 and source != "predicted"):
            continue
        unit_price = line.get("unit_price")
        sku = get_sku(session, sku_id)
        rows.append({"sku_id": sku_id, "props": {
            "line_index": index, "list_price": sku.list_price if sku else None, "unit_price": unit_price,
            "discount_pct": discount, "price_source": source,
            "net_unit_price": round(unit_price * (1 - discount / 100), 4) if unit_price is not None else None,
        }})
    return rows


def sync_quote(session: Session, client: GraphClient, ns: str, estimate_id: uuid.UUID) -> None:
    row = get_estimate_draft(session, estimate_id)
    if row is None:
        raise ValueError(f"estimate draft {estimate_id} not found")
    _merge_quote_node(client, ns, row)
    previous = previous_estimate_draft(session, row)
    if previous is not None:
        _merge_quote_node(client, ns, previous)
        merge_edges(client, ns, "SUPERSEDES", "Quote", "Quote", [_edge(str(row.id), str(previous.id))])
    replace_price_variance(client, ns, str(row.id), _price_variance_rows(session, row))


def rebuild_graph(session: Session, client: GraphClient, ns: str) -> RebuildSummary:
    """Reload the whole namespace, runtime entities included, from Postgres."""
    rebuild_reference_graph(session, client, ns)
    for request_id in all_quote_request_ids(session):
        sync_quote_request(session, client, ns, request_id)
    for request_id in all_verdict_request_ids(session):
        sync_dedupe_verdicts(session, client, ns, request_id)
    for estimate_id in all_estimate_draft_ids(session):
        sync_quote(session, client, ns, estimate_id)
    return RebuildSummary(
        namespace=ns, fingerprint=reference_fingerprint(session),
        node_counts=count_nodes_by_label(client, ns), edge_counts=count_edges_by_type(client, ns),
    )


def sync_best_effort(description: str, sync, *args) -> None:
    """Run a sync after Postgres has committed. The graph is derived, so a failure is logged and a rebuild repairs
    it; it must never fail the request that already succeeded."""
    try:
        sync(*args)
    except GraphError:
        logger.warning("graph sync failed for %s; run a rebuild to repair the graph", description, exc_info=True)
```

(The imports at the top of `service.py` now overlap the Task 4 imports: merge them into one block; do not leave duplicate names.)

- [ ] **Step 7: Run to verify pass**

Run: `pytest tests/app/graph -v`. Expected: PASS.

- [ ] **Step 8: Write the failing route-hook tests**

Append to `backend/tests/api/v1/test_intake_route.py` (add `from api.v1.intake.route import get_llm_client` already present; add `from core.graph.client import get_graph_client`, `from tests.graph_support import FailingGraphClient`):

```python
def _intake_post(db_session, fake_llm_client):
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_llm_client] = lambda: fake_llm_client
    try:
        return TestClient(app).post("/v1/intake", json={"email_text": "need 4 sprayers"})
    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_llm_client, None)


def _seeded_llm(db_session):
    upsert_customer(db_session, customer_id="CUST-A", name="Bramblewick Contractors", account_tier="Standard")
    upsert_sku(db_session, sku_id="SKU-A", name="Quazzlebolt Sprayer Assembly", category="C",
               list_price=1.0, discontinued=False, replaced_by=None, in_stock=True)
    db_session.flush()
    llm = MagicMock()
    llm.extract_quote_request.return_value = QuoteRequestExtraction(
        customer_name_as_written="Bramblewick Contractors",
        line_items=[LineItemExtraction(sku_name_as_written="Quazzlebolt Sprayer Assembly", quantity="4")],
        raw_text="need 4",
    )
    return llm


def test_submit_email_syncs_the_quote_request_into_the_graph(db_session, graph_client, graph_ns):
    response = _intake_post(db_session, _seeded_llm(db_session))

    rows = graph_client.read(
        "MATCH (q:QuoteRequest {key: $key}) RETURN q.id AS id", key=f"{graph_ns}:{response.json()['quote_request_id']}",
    )
    assert rows == [{"id": response.json()["quote_request_id"]}]


def test_submit_email_still_succeeds_when_the_graph_is_down(db_session):
    llm = _seeded_llm(db_session)
    app.dependency_overrides[get_graph_client] = lambda: FailingGraphClient()
    try:
        response = _intake_post(db_session, llm)
    finally:
        app.dependency_overrides.pop(get_graph_client, None)

    assert response.status_code == 200
```

Append to `backend/tests/api/v1/test_dedupe_route.py` (add `from core.graph.client import get_graph_client`, `from tests.graph_support import FailingGraphClient, graph_edge_count`):

```python
def _two_identical_requests(db_session):
    _seed_customer_and_site(db_session)
    kwargs = dict(parsed_json={}, content_fingerprint={"sku_ids": ["SKU-A"]}, style_fingerprint={"tokens": []},
                  customer_id="CUST-A", site_id="SITE-A")
    first = save_quote_request(db_session, raw_email_text="t1", **kwargs)
    second = save_quote_request(db_session, raw_email_text="t2", **kwargs)
    db_session.flush()
    return first, second


def test_dedupe_endpoint_syncs_the_duplicate_edge_into_the_graph(db_session, graph_client, graph_ns):
    first, second = _two_identical_requests(db_session)
    app.dependency_overrides[get_session] = lambda: db_session
    try:
        TestClient(app).post(f"/v1/dedupe/{second.id}")
    finally:
        app.dependency_overrides.clear()

    assert graph_edge_count(graph_client, graph_ns, str(second.id), "DUPLICATE_OF", str(first.id)) == 1


def test_dedupe_endpoint_still_succeeds_when_the_graph_is_down(db_session):
    _, second = _two_identical_requests(db_session)
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_graph_client] = lambda: FailingGraphClient()
    try:
        response = TestClient(app).post(f"/v1/dedupe/{second.id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
```

- [ ] **Step 9: Run to verify failure, then wire the routes**

Run `pytest tests/api/v1/test_intake_route.py tests/api/v1/test_dedupe_route.py -v`: the two "syncs" tests FAIL (nothing synced yet).

In `backend/api/v1/intake/route.py` add imports `from app.graph.service import sync_best_effort, sync_quote_request`, `from core.graph.client import GraphClient, get_graph_client, get_graph_namespace`; add two dependencies to `submit_email` and the hook after `session.commit()`:

```python
    graph_client: GraphClient = Depends(get_graph_client),
    ns: str = Depends(get_graph_namespace),
```

```python
    session.commit()
    sync_best_effort("quote request", sync_quote_request, session, graph_client, ns, result.row.id)
```

In `backend/api/v1/dedupe/route.py` the same imports with `sync_dedupe_verdicts`, the same two dependencies on `dedupe_quote_request`, and after `session.commit()`:

```python
    sync_best_effort("dedupe verdicts", sync_dedupe_verdicts, session, graph_client, ns, quote_request_id)
```

- [ ] **Step 10: Run to verify pass**

Run: `pytest tests/api/v1/test_intake_route.py tests/api/v1/test_dedupe_route.py tests/app/graph -v`, then the full suite `pytest -q`. Expected: all PASS.

- [ ] **Step 11: Commit**

```bash
git add backend/app/graph/helper.py backend/app/graph/constant.py backend/app/graph/repository.py backend/app/graph/service.py backend/app/intake/repository.py backend/app/dedupe/repository.py backend/app/estimate/repository.py backend/api/v1/intake/route.py backend/api/v1/dedupe/route.py backend/tests/graph_support.py backend/tests/app/graph/test_rebuild.py backend/tests/app/graph/test_helper.py backend/tests/app/graph/test_sync.py backend/tests/api/v1/test_intake_route.py backend/tests/api/v1/test_dedupe_route.py
git commit -m "feat: sync quote requests, dedupe edges and quotes into the graph after commit"
```

---

### Task 7: Leiden communities, global statistics, local fan-out

**Files:**
- Modify: `backend/app/graph/constant.py`, `backend/app/graph/schemas.py`, `backend/app/graph/helper.py`, `backend/app/graph/repository.py`, `backend/app/graph/service.py`, `backend/tests/graph_support.py`, `backend/tests/app/graph/test_helper.py`
- Create: `backend/tests/app/graph/test_communities.py`

**Interfaces:**
- Consumes: Tasks 4 to 6.
- Produces:
  - `app.graph.constant`: `LEIDEN_SEED = 42`, `LEIDEN_GAMMA = 1.0`, `LOCAL_MAX_HOPS = 2`, `LOCAL_MAX_NODES = 50`, `LOCAL_MAX_PATHS = 500`, `HUB_LABELS = ("PricingCategory", "ProductFamily")`, `MAX_EXAMPLE_SKUS = 5`, `MAX_MEMBER_NAMES = 30`.
  - `app.graph.schemas`: `CommunityStats(community_id, size, families, dominant_category, dominant_category_share, discontinued_count, requirement_count, example_sku_ids, member_names, member_hash)`; `CommunityRunSummary(community_count, largest_community_size)`; `LocalResult(center, nodes, edges, truncated)` where `nodes = [{"id", "label"}]` and `edges = [{"type", "source", "target"}]`.
  - `app.graph.helper`: `member_hash(sku_ids) -> str` (SHA-256 hex of the sorted ids joined by newlines), `build_community_stats(rows: list[dict]) -> list[CommunityStats]` (rows have `sku_id, name, category, discontinued, community, family, has_requirements`).
  - `app.graph.service`: `run_communities(client, ns) -> CommunityRunSummary`, `global_stats(client, ns) -> list[CommunityStats]`, `local_query(client, ns, node_id, hops=2) -> LocalResult`, `class NodeNotFound(Exception)`.

- [ ] **Step 1: Write the failing helper tests**

Append to `backend/tests/app/graph/test_helper.py` (add `from app.graph.helper import build_community_stats, member_hash`):

```python
def _row(sku_id, community, *, category="Cat-A", discontinued=False, family="Fam", has_requirements=False, name=None):
    return {"sku_id": sku_id, "name": name or f"name {sku_id}", "category": category, "discontinued": discontinued,
            "community": community, "family": family, "has_requirements": has_requirements}


def test_member_hash_ignores_order_and_changes_with_membership():
    assert member_hash(["b", "a", "c"]) == member_hash(["c", "a", "b"])
    assert member_hash(["a", "b"]) != member_hash(["a", "b", "c"])
    assert len(member_hash(["a"])) == 64


def test_community_stats_summarise_each_community():
    rows = [
        _row("S1", 7, category="Cat-A", family="Fam One", has_requirements=True),
        _row("S2", 7, category="Cat-A", family="Fam One", discontinued=True),
        _row("S3", 7, category="Cat-B", family="Fam Two"),
        _row("S9", 3, category="Cat-B", family="Fam Nine"),
    ]

    stats = build_community_stats(rows)

    assert [s.community_id for s in stats] == [3, 7]
    seven = stats[1]
    assert seven.size == 3
    assert seven.families == ("Fam One", "Fam Two")
    assert (seven.dominant_category, seven.dominant_category_share) == ("Cat-A", 0.667)
    assert seven.discontinued_count == 1 and seven.requirement_count == 1
    assert seven.example_sku_ids == ("S1", "S2", "S3")
    assert seven.member_names == ("name S1", "name S2", "name S3")
    assert seven.member_hash == member_hash(["S1", "S2", "S3"])


def test_dominant_category_ties_break_alphabetically_and_missing_families_are_skipped():
    rows = [_row("S1", 1, category="Cat-B", family=None), _row("S2", 1, category="Cat-A", family=None)]

    stat = build_community_stats(rows)[0]

    assert stat.dominant_category == "Cat-A"
    assert stat.families == ()


def test_example_skus_and_member_names_are_capped_and_sorted():
    rows = [_row(f"S{i:02d}", 1) for i in range(40, 0, -1)]

    stat = build_community_stats(rows)[0]

    assert stat.size == 40
    assert stat.example_sku_ids == ("S01", "S02", "S03", "S04", "S05")
    assert len(stat.member_names) == 30
```

Run `pytest tests/app/graph/test_helper.py -v`. Expected: the four new tests FAIL (`ImportError`).

- [ ] **Step 2: Implement constants, schemas and helper**

Append to `backend/app/graph/constant.py`:

```python
# A fixed seed makes Leiden deterministic; without it two runs can label communities differently.
LEIDEN_SEED = 42
LEIDEN_GAMMA = 1.0
LOCAL_MAX_HOPS = 2
LOCAL_MAX_NODES = 50
LOCAL_MAX_PATHS = 500
# Hubs appear in a local result only as leaves. Walking through one would return every member of the category or family.
HUB_LABELS = ("PricingCategory", "ProductFamily")
MAX_EXAMPLE_SKUS = 5
MAX_MEMBER_NAMES = 30
```

Append to `backend/app/graph/schemas.py`:

```python
@dataclass(frozen=True)
class CommunityStats:
    community_id: int
    size: int
    families: tuple[str, ...]
    dominant_category: str
    dominant_category_share: float
    discontinued_count: int
    requirement_count: int
    example_sku_ids: tuple[str, ...]
    member_names: tuple[str, ...]
    member_hash: str


@dataclass(frozen=True)
class CommunityRunSummary:
    community_count: int
    largest_community_size: int


@dataclass(frozen=True)
class LocalResult:
    center: str
    nodes: list[dict]
    edges: list[dict]
    truncated: bool
```

Append to `backend/app/graph/helper.py` (add the imports at the top: `import hashlib`, `from collections import Counter`, `from app.graph.constant import MAX_EXAMPLE_SKUS, MAX_MEMBER_NAMES`, `from app.graph.schemas import CommunityStats`):

```python
def member_hash(sku_ids) -> str:
    """Identity of a community by its members, so a relabeled community still finds its cached summary."""
    return hashlib.sha256("\n".join(sorted(sku_ids)).encode("utf-8")).hexdigest()


def build_community_stats(rows: list[dict]) -> list[CommunityStats]:
    by_community: dict[int, list[dict]] = {}
    for row in rows:
        by_community.setdefault(row["community"], []).append(row)

    stats = []
    for community_id in sorted(by_community):
        members = sorted(by_community[community_id], key=lambda m: m["sku_id"])
        categories = Counter(m["category"] for m in members)
        dominant, count = sorted(categories.items(), key=lambda item: (-item[1], item[0]))[0]
        stats.append(CommunityStats(
            community_id=community_id, size=len(members),
            families=tuple(sorted({m["family"] for m in members if m["family"]})),
            dominant_category=dominant, dominant_category_share=round(count / len(members), 3),
            discontinued_count=sum(1 for m in members if m["discontinued"]),
            requirement_count=sum(1 for m in members if m["has_requirements"]),
            example_sku_ids=tuple(m["sku_id"] for m in members[:MAX_EXAMPLE_SKUS]),
            member_names=tuple(m["name"] for m in members[:MAX_MEMBER_NAMES]),
            member_hash=member_hash(m["sku_id"] for m in members),
        ))
    return stats
```

Run `pytest tests/app/graph/test_helper.py -v`. Expected: PASS.

- [ ] **Step 3: Add the planted-cluster seed to the test support**

Append to `backend/tests/graph_support.py` (add `from app.reference_data.repository import set_sku_family, upsert_family, upsert_requirement, upsert_sku` to its imports):

```python
def seed_clusters(session) -> None:
    """Two disconnected clusters of four SKUs, one family each, all in Cat-L. SKU-L-X4 is discontinued and
    SKU-L-X1 requires SKU-L-X2. Leiden must put each cluster in its own community."""
    upsert_family(session, family_id="FAM-L-X", name="Xylo Widget", category="Cat-L")
    upsert_family(session, family_id="FAM-L-Y", name="Yarrow Gadget", category="Cat-L")
    session.flush()
    for prefix in ("X", "Y"):
        for i in range(1, 5):
            upsert_sku(
                session, sku_id=f"SKU-L-{prefix}{i}", name=f"unit {prefix}{i}", category="Cat-L", list_price=1.0,
                discontinued=(prefix == "X" and i == 4), replaced_by=None, in_stock=True,
            )
    session.flush()
    for prefix in ("X", "Y"):
        for i in range(1, 5):
            set_sku_family(session, f"SKU-L-{prefix}{i}", f"FAM-L-{prefix}")
    upsert_requirement(session, sku_id="SKU-L-X1", required_sku_id="SKU-L-X2")
    session.flush()
```

- [ ] **Step 4: Write the failing community and local tests**

Create `backend/tests/app/graph/test_communities.py`:

```python
import uuid

import pytest

from app.graph.constant import LOCAL_MAX_NODES
from app.graph.helper import member_hash
from app.graph.repository import node_key
from app.graph.service import NodeNotFound, global_stats, local_query, run_communities
from app.reference_data.repository import upsert_requirement, upsert_sku
from tests.app.estimate.seed import seed_structure, seed_world
from tests.graph_support import graph_node, seed_clusters


def _sku(session, sku_id, category, *, discontinued=False):
    upsert_sku(session, sku_id=sku_id, name=f"unit {sku_id}", category=category, list_price=1.0,
               discontinued=discontinued, replaced_by=None, in_stock=True)


def _community_of(client, ns, sku_id):
    rows = client.read("MATCH (n {key: $key}) RETURN n.community_id AS community", key=node_key(ns, sku_id))
    return rows[0]["community"]


def _partition(client, ns):
    rows = client.read("MATCH (s:SKU {ns: $ns}) WHERE s.community_id IS NOT NULL RETURN s.community_id AS c, s.id AS id", ns=ns)
    groups: dict[int, set[str]] = {}
    for row in rows:
        groups.setdefault(row["c"], set()).add(row["id"])
    return {frozenset(members) for members in groups.values()}


def test_disconnected_clusters_land_in_separate_communities(db_session, graph_client, graph_ns, make_reader):
    seed_clusters(db_session)
    make_reader()

    summary = run_communities(graph_client, graph_ns)

    x = {_community_of(graph_client, graph_ns, f"SKU-L-X{i}") for i in range(1, 5)}
    y = {_community_of(graph_client, graph_ns, f"SKU-L-Y{i}") for i in range(1, 5)}
    assert len(x) == 1 and len(y) == 1 and x != y
    assert summary.community_count >= 2
    assert summary.largest_community_size >= 4
    assert _community_of(graph_client, graph_ns, "FAM-L-X") == next(iter(x))


def test_a_fixed_seed_gives_the_same_partition_on_every_run(db_session, graph_client, graph_ns, make_reader):
    seed_clusters(db_session)
    make_reader()

    run_communities(graph_client, graph_ns)
    first = _partition(graph_client, graph_ns)
    run_communities(graph_client, graph_ns)

    assert _partition(graph_client, graph_ns) == first


def test_the_gds_projection_is_dropped_after_a_run(db_session, graph_client, graph_ns, make_reader):
    seed_clusters(db_session)
    make_reader()

    run_communities(graph_client, graph_ns)

    exists = graph_client.read("CALL gds.graph.exists($name) YIELD exists RETURN exists", name=f"leiden-{graph_ns}")
    assert exists == [{"exists": False}]


def test_a_second_run_clears_assignments_from_the_first(db_session, graph_client, graph_ns, make_reader):
    seed_clusters(db_session)
    make_reader()
    graph_client.write("MATCH (n {key: $key}) SET n.community_id = 9999", key=node_key(graph_ns, "Cat-L"))

    run_communities(graph_client, graph_ns)

    assert "community_id" not in graph_node(graph_client, graph_ns, "Cat-L")["props"]
    assert _community_of(graph_client, graph_ns, "SKU-L-X1") != 9999


def test_an_empty_namespace_has_no_communities(graph_client, graph_ns):
    summary = run_communities(graph_client, graph_ns)

    assert summary.community_count == 0 and summary.largest_community_size == 0


def test_global_stats_describe_a_planted_cluster(db_session, graph_client, graph_ns, make_reader):
    seed_clusters(db_session)
    make_reader()
    run_communities(graph_client, graph_ns)

    stats = global_stats(graph_client, graph_ns)

    x = next(s for s in stats if "SKU-L-X1" in s.example_sku_ids)
    y = next(s for s in stats if "SKU-L-Y1" in s.example_sku_ids)
    assert x.size == 4 and x.families == ("Xylo Widget",)
    assert (x.dominant_category, x.dominant_category_share) == ("Cat-L", 1.0)
    assert x.discontinued_count == 1 and x.requirement_count == 1
    assert x.example_sku_ids == ("SKU-L-X1", "SKU-L-X2", "SKU-L-X3", "SKU-L-X4")
    assert x.member_hash == member_hash(x.example_sku_ids)
    assert y.discontinued_count == 0 and y.requirement_count == 0


def test_global_stats_are_empty_before_communities_are_computed(db_session, graph_client, graph_ns, make_reader):
    seed_world(db_session)
    make_reader()

    assert global_stats(graph_client, graph_ns) == []


def _ids(result):
    return {n["id"] for n in result.nodes}


def test_one_hop_lists_direct_neighbours_with_hubs_as_leaves(db_session, graph_client, graph_ns, make_reader):
    seed_world(db_session)
    make_reader()

    result = local_query(graph_client, graph_ns, "SKU-E-B1", hops=1)

    assert result.center == "SKU-E-B1"
    assert _ids(result) == {"SKU-E-B1", "SKU-E-A1", "Cat-E-B"}
    assert {"type": "REQUIRES", "source": "SKU-E-B1", "target": "SKU-E-A1"} in result.edges
    assert {"type": "PRICED_IN", "source": "SKU-E-B1", "target": "Cat-E-B"} in result.edges
    assert result.truncated is False
    labels = {n["id"]: n["label"] for n in result.nodes}
    assert labels["SKU-E-B1"] == "SKU" and labels["Cat-E-B"] == "PricingCategory"


def test_two_hops_pass_through_a_sku_but_not_through_a_hub(db_session, graph_client, graph_ns, make_reader):
    seed_world(db_session)
    seed_structure(db_session)
    for i in range(1, 6):
        _sku(db_session, f"SKU-L-H{i}", "Cat-L-HUB")
    db_session.flush()
    make_reader()

    through_sku = local_query(graph_client, graph_ns, "SKU-E-B1", hops=2)
    through_hub = local_query(graph_client, graph_ns, "SKU-L-H1", hops=2)

    assert {"SKU-E-OLD", "FAM-E-A"} <= _ids(through_sku)
    assert "Cat-L-HUB" in _ids(through_hub)
    assert _ids(through_hub).isdisjoint({f"SKU-L-H{i}" for i in range(2, 6)})


def test_a_hub_centre_returns_at_most_the_node_cap_and_says_it_was_truncated(db_session, graph_client, graph_ns, make_reader):
    """(Review Focus) A pricing category with more members than the cap."""
    for i in range(LOCAL_MAX_NODES + 10):
        _sku(db_session, f"SKU-L-B{i:03d}", "Cat-L-BIG")
    db_session.flush()
    make_reader()

    result = local_query(graph_client, graph_ns, "Cat-L-BIG", hops=1)

    assert result.truncated is True
    assert len(result.nodes) == LOCAL_MAX_NODES
    assert "Cat-L-BIG" in _ids(result)
    kept = _ids(result)
    assert all(e["source"] in kept and e["target"] in kept for e in result.edges)


def test_an_unknown_id_raises_node_not_found(db_session, graph_client, graph_ns, make_reader):
    seed_world(db_session)
    make_reader()

    with pytest.raises(NodeNotFound):
        local_query(graph_client, graph_ns, "SKU-NOPE")


def test_an_id_that_exists_only_in_another_namespace_is_not_found(db_session, graph_client, graph_ns, make_reader):
    """(Review Focus) The namespace is part of the lookup key."""
    other = f"test-other-{uuid.uuid4().hex[:8]}"
    graph_client.write("CREATE (:SKU {ns: $ns, key: $key, id: 'OTHER-ONLY'})", ns=other, key=node_key(other, "OTHER-ONLY"))
    try:
        seed_world(db_session)
        make_reader()

        with pytest.raises(NodeNotFound):
            local_query(graph_client, graph_ns, "OTHER-ONLY")
    finally:
        graph_client.write("MATCH (n {ns: $ns}) DETACH DELETE n", ns=other)


def test_hops_are_clamped_to_between_one_and_the_maximum(db_session, graph_client, graph_ns, make_reader):
    """(Review Focus) hops of 0 or 99 must not disable or unbound the walk."""
    for i in range(1, 5):
        _sku(db_session, f"SKU-L-C{i}", "Cat-L-CHAIN")
    db_session.flush()
    for i in range(1, 4):
        upsert_requirement(db_session, sku_id=f"SKU-L-C{i}", required_sku_id=f"SKU-L-C{i + 1}")
    db_session.flush()
    make_reader()

    zero = local_query(graph_client, graph_ns, "SKU-L-C1", hops=0)
    huge = local_query(graph_client, graph_ns, "SKU-L-C1", hops=99)

    assert "SKU-L-C2" in _ids(zero) and "SKU-L-C3" not in _ids(zero)
    assert "SKU-L-C3" in _ids(huge) and "SKU-L-C4" not in _ids(huge)


def test_an_isolated_node_returns_just_itself(db_session, graph_client, graph_ns, make_reader):
    seed_world(db_session)
    make_reader()
    graph_client.write("CREATE (:Site {ns: $ns, key: $key, id: 'SITE-LONELY'})", ns=graph_ns, key=node_key(graph_ns, "SITE-LONELY"))

    result = local_query(graph_client, graph_ns, "SITE-LONELY")

    assert result.nodes == [{"id": "SITE-LONELY", "label": "Site"}]
    assert result.edges == [] and result.truncated is False
```

- [ ] **Step 5: Run to verify failure**

Run: `pytest tests/app/graph/test_communities.py -v`. Expected: collection error (`NodeNotFound` etc. missing).

- [ ] **Step 6: Implement the repository functions**

Add `HUB_LABELS, LEIDEN_GAMMA, LEIDEN_SEED, LOCAL_MAX_PATHS` to the `app.graph.constant` import in `backend/app/graph/repository.py` and append:

```python
def _projection_name(ns: str) -> str:
    return f"leiden-{ns}"


def _drop_projection(client: GraphClient, name: str) -> None:
    client.write("CALL gds.graph.drop($name, false) YIELD graphName RETURN graphName", name=name)


def run_leiden(client: GraphClient, ns: str) -> list[dict]:
    """Leiden over this namespace's SKUs and families. Pricing categories are left out: with five hubs they would
    make every community just a category. Returns [{"key", "label", "community"}]."""
    name = _projection_name(ns)
    _drop_projection(client, name)
    try:
        projected = client.write(
            "MATCH (a)-[r:IN_FAMILY|REQUIRES|REPLACED_BY]->(b) WHERE a.ns = $ns AND b.ns = $ns "
            "WITH gds.graph.project($name, a, b, {relationshipType: type(r)}, {undirectedRelationshipTypes: ['*']}) AS g "
            "RETURN g.graphName AS name",
            name=name, ns=ns,
        )
        # Aggregating over zero matches still returns one row, with a null name and no projection created.
        if not projected or projected[0]["name"] is None:
            return []
        return client.read(
            "CALL gds.leiden.stream($name, {randomSeed: $seed, gamma: $gamma, concurrency: 1}) YIELD nodeId, communityId "
            "RETURN gds.util.asNode(nodeId).key AS key, labels(gds.util.asNode(nodeId))[0] AS label, "
            "communityId AS community ORDER BY key",
            name=name, seed=LEIDEN_SEED, gamma=LEIDEN_GAMMA,
        )
    finally:
        _drop_projection(client, name)


def clear_communities(client: GraphClient, ns: str) -> None:
    client.write("MATCH (n {ns: $ns}) WHERE n.community_id IS NOT NULL REMOVE n.community_id", ns=ns)


def write_communities(client: GraphClient, ns: str, assignments: list[dict]) -> None:
    for batch in _batches(assignments):
        client.write(
            "UNWIND $rows AS row MATCH (n {key: row.key}) SET n.community_id = row.community", rows=batch,
        )


def fetch_community_members(client: GraphClient, ns: str) -> list[dict]:
    return client.read(
        "MATCH (s:SKU {ns: $ns}) WHERE s.community_id IS NOT NULL "
        "OPTIONAL MATCH (s)-[:IN_FAMILY]->(f:ProductFamily) "
        "RETURN s.id AS sku_id, s.name AS name, s.category AS category, s.discontinued AS discontinued, "
        "s.community_id AS community, f.name AS family, EXISTS { (s)-[:REQUIRES]->() } AS has_requirements "
        "ORDER BY s.id",
        ns=ns,
    )


def fetch_node(client: GraphClient, ns: str, node_id: str) -> dict | None:
    rows = client.read(
        "MATCH (n {key: $key}) RETURN n.id AS id, labels(n)[0] AS label", key=node_key(ns, node_id),
    )
    return rows[0] if rows else None


def fetch_local_paths(client: GraphClient, ns: str, node_id: str, hops: int) -> list[dict]:
    """Paths of 1 to `hops` relationships from a node, never passing through a hub node. Nearer paths first."""
    if not isinstance(hops, int):
        raise ValueError("hops must be an integer")
    not_hub = " AND ".join(f"NOT x:{label}" for label in HUB_LABELS)
    return client.read(
        f"MATCH p = (s {{key: $key}})-[*1..{hops}]-(m) "
        f"WHERE m.ns = $ns AND all(x IN nodes(p)[1..-1] WHERE {not_hub}) "
        "RETURN [n IN nodes(p) | {id: n.id, label: labels(n)[0]}] AS nodes, "
        "[r IN relationships(p) | {type: type(r), source: startNode(r).id, target: endNode(r).id}] AS edges "
        f"ORDER BY length(p), m.id LIMIT {LOCAL_MAX_PATHS}",
        key=node_key(ns, node_id), ns=ns,
    )
```

- [ ] **Step 7: Implement the service functions**

In `backend/app/graph/service.py` extend the imports (`from collections import Counter`; the repository names `clear_communities, fetch_community_members, fetch_local_paths, fetch_node, run_leiden, write_communities`; `from app.graph.constant import LOCAL_MAX_HOPS, LOCAL_MAX_NODES`; `from app.graph.helper import build_community_stats, match_site`; `from app.graph.schemas import CommunityRunSummary, CommunityStats, LocalResult, RebuildSummary`) and append:

```python
class NodeNotFound(Exception):
    pass


def run_communities(client: GraphClient, ns: str) -> CommunityRunSummary:
    assignments = run_leiden(client, ns)
    clear_communities(client, ns)
    write_communities(client, ns, assignments)
    sku_sizes = Counter(a["community"] for a in assignments if a["label"] == "SKU")
    return CommunityRunSummary(
        community_count=len(sku_sizes), largest_community_size=max(sku_sizes.values(), default=0),
    )


def global_stats(client: GraphClient, ns: str) -> list[CommunityStats]:
    return build_community_stats(fetch_community_members(client, ns))


def local_query(client: GraphClient, ns: str, node_id: str, hops: int = LOCAL_MAX_HOPS) -> LocalResult:
    center = fetch_node(client, ns, node_id)
    if center is None:
        raise NodeNotFound(f"no node {node_id} in the graph")
    hops = max(1, min(int(hops), LOCAL_MAX_HOPS))

    nodes: dict[str, dict] = {center["id"]: center}
    truncated = False
    kept_paths = []
    for row in fetch_local_paths(client, ns, node_id, hops):
        new = [n for n in row["nodes"] if n["id"] not in nodes]
        # A path is added whole or not at all, so the result never holds a node cut off from the centre.
        if len(nodes) + len(new) > LOCAL_MAX_NODES:
            truncated = True
            continue
        nodes.update({n["id"]: n for n in new})
        kept_paths.append(row)

    edges: dict[tuple[str, str, str], dict] = {}
    for row in kept_paths:
        for edge in row["edges"]:
            edges[(edge["source"], edge["type"], edge["target"])] = edge
    return LocalResult(center=node_id, nodes=list(nodes.values()), edges=list(edges.values()), truncated=truncated)
```

- [ ] **Step 8: Run to verify pass**

Run: `pytest tests/app/graph -v`, then the full suite `pytest -q`. Expected: all PASS. Report in your handoff how many communities Leiden finds on a namespace built from the full real dataset (a one-off script: load the dev Postgres reference data with a session, `rebuild_graph` into a `test-probe-...` namespace, `run_communities`, print `community_count` and `largest_community_size`, then drop the namespace). This number sets the summary cost in Task 8; do not run it against `main`.

- [ ] **Step 9: Commit**

```bash
git add backend/app/graph/constant.py backend/app/graph/schemas.py backend/app/graph/helper.py backend/app/graph/repository.py backend/app/graph/service.py backend/tests/graph_support.py backend/tests/app/graph/test_helper.py backend/tests/app/graph/test_communities.py
git commit -m "feat: add Leiden communities, global community statistics, and hub-safe local fan-out"
```

---

### Task 8: Community summaries (client, Postgres cache, gated job)

**Files:**
- Create: `backend/core/llm/openai_summary_client.py`, `backend/app/retrieval/repository.py`, `backend/app/retrieval/summarizer.py`, `backend/scripts/summarize_communities.py`, `backend/tests/core/test_openai_summary_client.py`, `backend/tests/app/retrieval/__init__.py` (empty), `backend/tests/app/retrieval/test_summarizer.py`
- Modify: `backend/tests/graph_support.py`

**Interfaces:**
- Consumes: Task 3 `CommunitySummary`; Task 7 `CommunityStats`, `member_hash`.
- Produces:
  - `core.llm.openai_summary_client`: `SUMMARY_MODEL = "gpt-4o-mini"`, `SUMMARY_SYSTEM`, `SummaryError`, `OpenAISummaryClient(client=None).summarize(prompt: str) -> str`.
  - `app.retrieval.repository`: `get_summaries(session, hashes: list[str]) -> dict[str, str]`, `save_summary(session, *, member_hash, summary, model) -> None`.
  - `app.retrieval.summarizer`: `MIN_SUMMARY_SIZE = 3`, `build_summary_prompt(stats) -> str`, `pending_summaries(session, stats_list) -> list[CommunityStats]`, `estimate_input_tokens(pending) -> int`, `SummaryRun(generated, cached, skipped_small)`, `summarize_communities(session, summarizer, stats_list, on_saved) -> SummaryRun`, `run_summary_job(session, stats_list, summarizer_factory, *, yes, out, on_saved) -> SummaryRun | None` (dry run unless `yes`; the factory is not called on a dry run).
  - `tests.graph_support.FakeSummarizer` (records `.prompts`, returns a distinct text per call).

- [ ] **Step 1: Write the failing client tests**

Create `backend/tests/core/test_openai_summary_client.py`:

```python
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.llm.openai_summary_client import SUMMARY_MODEL, SUMMARY_SYSTEM, OpenAISummaryClient, SummaryError


def _openai(content="  A tidy cluster.  ", choices=True):
    message = SimpleNamespace(content=content)
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)] if choices else [])
    create = MagicMock(return_value=response)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), create


def test_summarize_returns_stripped_text_and_sends_the_system_prompt_and_model():
    openai, create = _openai()

    text = OpenAISummaryClient(client=openai).summarize("stats here")

    assert text == "A tidy cluster."
    kwargs = create.call_args.kwargs
    assert kwargs["model"] == SUMMARY_MODEL
    assert kwargs["messages"] == [
        {"role": "system", "content": SUMMARY_SYSTEM}, {"role": "user", "content": "stats here"},
    ]


def test_no_choices_is_a_summary_error():
    openai, _ = _openai(choices=False)

    with pytest.raises(SummaryError):
        OpenAISummaryClient(client=openai).summarize("x")


@pytest.mark.parametrize("content", [None, "", "   "])
def test_empty_content_is_a_summary_error(content):
    openai, _ = _openai(content=content)

    with pytest.raises(SummaryError):
        OpenAISummaryClient(client=openai).summarize("x")


def test_an_api_failure_is_wrapped():
    openai, create = _openai()
    create.side_effect = RuntimeError("boom")

    with pytest.raises(SummaryError, match="boom"):
        OpenAISummaryClient(client=openai).summarize("x")
```

- [ ] **Step 2: Run to verify failure, then implement the client**

Run: `pytest tests/core/test_openai_summary_client.py -v`. Expected: collection error.

Create `backend/core/llm/openai_summary_client.py`:

```python
from openai import OpenAI

SUMMARY_MODEL = "gpt-4o-mini"

SUMMARY_SYSTEM = (
    "You summarize one cluster of products from a plumbing and HVAC supply catalog. State only what the statistics "
    "and member names you are given show. Do not infer purchase behavior, prices, customers, or anything that is "
    "not listed. Write two or three plain sentences."
)


class SummaryError(Exception):
    pass


class OpenAISummaryClient:
    def __init__(self, client: OpenAI | None = None) -> None:
        self._client = client or OpenAI()

    def summarize(self, prompt: str) -> str:
        try:
            response = self._client.chat.completions.create(
                model=SUMMARY_MODEL,
                messages=[{"role": "system", "content": SUMMARY_SYSTEM}, {"role": "user", "content": prompt}],
            )
        except Exception as exc:
            raise SummaryError(f"OpenAI summary call failed: {exc}") from exc

        if not response.choices:
            raise SummaryError("OpenAI returned no choices")
        content = response.choices[0].message.content
        if not content or not content.strip():
            raise SummaryError("OpenAI returned an empty summary")
        return content.strip()
```

Run again: PASS.

- [ ] **Step 3: Add the fake summarizer**

Append to `backend/tests/graph_support.py`:

```python
class FakeSummarizer:
    """Records every prompt and returns a distinct summary per call. Never touches the network."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def summarize(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return f"Fake summary number {len(self.prompts)}."
```

- [ ] **Step 4: Write the failing summarizer tests**

Create `backend/tests/app/retrieval/__init__.py` (empty) and `backend/tests/app/retrieval/test_summarizer.py`:

```python
import pytest

from app.graph.helper import member_hash
from app.graph.schemas import CommunityStats
from app.retrieval.repository import get_summaries, save_summary
from app.retrieval.summarizer import (
    MIN_SUMMARY_SIZE, build_summary_prompt, estimate_input_tokens, pending_summaries, run_summary_job,
    summarize_communities,
)
from core.llm.openai_summary_client import SUMMARY_MODEL, SummaryError
from tests.graph_support import FakeSummarizer


def _stats(tag, size=4, community_id=1):
    ids = [f"SKU-SUM-{tag}{i}" for i in range(size)]
    return CommunityStats(
        community_id=community_id, size=size, families=(f"Family {tag}",), dominant_category="Cat-S",
        dominant_category_share=0.75, discontinued_count=1, requirement_count=2, example_sku_ids=tuple(ids[:5]),
        member_names=tuple(f"name {i}" for i in ids), member_hash=member_hash(ids),
    )


def test_prompt_contains_the_statistics_and_member_names():
    prompt = build_summary_prompt(_stats("A"))

    assert "4 SKUs" in prompt
    assert "Family A" in prompt
    assert "Cat-S" in prompt and "75%" in prompt
    assert "Discontinued SKUs: 1" in prompt and "required parts: 2" in prompt
    assert "name SKU-SUM-A0" in prompt


def test_pending_skips_small_communities_and_cached_ones(db_session):
    cached, fresh, small = _stats("C"), _stats("F"), _stats("S", size=MIN_SUMMARY_SIZE - 1)
    save_summary(db_session, member_hash=cached.member_hash, summary="already", model=SUMMARY_MODEL)

    pending = pending_summaries(db_session, [cached, fresh, small])

    assert [s.member_hash for s in pending] == [fresh.member_hash]


def test_summarize_saves_each_summary_and_reports_counts(db_session):
    fresh, cached, small = _stats("F"), _stats("C"), _stats("S", size=MIN_SUMMARY_SIZE - 1)
    save_summary(db_session, member_hash=cached.member_hash, summary="already", model=SUMMARY_MODEL)
    summarizer, saved = FakeSummarizer(), []

    run = summarize_communities(db_session, summarizer, [fresh, cached, small], on_saved=lambda: saved.append(1))

    assert (run.generated, run.cached, run.skipped_small) == (1, 1, 1)
    assert len(summarizer.prompts) == 1 and len(saved) == 1
    assert get_summaries(db_session, [fresh.member_hash]) == {fresh.member_hash: "Fake summary number 1."}


def test_a_second_run_makes_no_calls(db_session):
    stats = [_stats("A"), _stats("B", community_id=2)]
    summarizer = FakeSummarizer()
    summarize_communities(db_session, summarizer, stats, on_saved=lambda: None)

    again = summarize_communities(db_session, summarizer, stats, on_saved=lambda: None)

    assert len(summarizer.prompts) == 2
    assert (again.generated, again.cached) == (0, 2)


def test_a_relabeled_community_reuses_its_cached_summary(db_session):
    first = _stats("R", community_id=1)
    relabeled = _stats("R", community_id=99)
    summarizer = FakeSummarizer()
    summarize_communities(db_session, summarizer, [first], on_saved=lambda: None)

    summarize_communities(db_session, summarizer, [relabeled], on_saved=lambda: None)

    assert len(summarizer.prompts) == 1


def test_only_new_communities_are_sent_to_the_model(db_session):
    old, new = _stats("O"), _stats("N", community_id=2)
    summarizer = FakeSummarizer()
    summarize_communities(db_session, summarizer, [old], on_saved=lambda: None)

    summarize_communities(db_session, summarizer, [old, new], on_saved=lambda: None)

    assert len(summarizer.prompts) == 2
    assert "Family N" in summarizer.prompts[1]


def test_a_model_failure_keeps_the_summaries_already_saved(db_session):
    first, second = _stats("A"), _stats("B", community_id=2)

    class FailsOnSecond:
        def __init__(self):
            self.calls = 0

        def summarize(self, prompt):
            self.calls += 1
            if self.calls == 2:
                raise SummaryError("boom")
            return "first summary"

    saved = []
    with pytest.raises(SummaryError):
        summarize_communities(db_session, FailsOnSecond(), [first, second], on_saved=lambda: saved.append(1))

    assert saved == [1]
    assert list(get_summaries(db_session, [first.member_hash, second.member_hash])) == [first.member_hash]


def test_estimate_input_tokens_grows_with_the_pending_list(db_session):
    one = estimate_input_tokens([_stats("A")])
    two = estimate_input_tokens([_stats("A"), _stats("B")])

    assert 0 < one < two
    assert estimate_input_tokens([]) == 0


def test_a_dry_run_reports_the_plan_and_never_builds_the_client(db_session):
    stats = [_stats("A"), _stats("B", community_id=2)]
    lines, built = [], []

    result = run_summary_job(
        db_session, stats, lambda: built.append(1) or FakeSummarizer(), yes=False, out=lines.append,
        on_saved=lambda: None,
    )

    assert result is None and built == []
    text = "\n".join(lines)
    assert "2 communities need a summary" in text
    assert SUMMARY_MODEL in text
    assert "dry run" in text and "--yes" in text


def test_the_job_with_yes_builds_the_client_and_summarizes(db_session):
    stats = [_stats("A")]
    summarizer, lines = FakeSummarizer(), []

    result = run_summary_job(
        db_session, stats, lambda: summarizer, yes=True, out=lines.append, on_saved=lambda: None,
    )

    assert result.generated == 1 and len(summarizer.prompts) == 1
    assert any("generated 1" in line for line in lines)


def test_the_job_with_nothing_pending_makes_no_client(db_session):
    stats = [_stats("A")]
    save_summary(db_session, member_hash=stats[0].member_hash, summary="done", model=SUMMARY_MODEL)
    built = []

    result = run_summary_job(
        db_session, stats, lambda: built.append(1) or FakeSummarizer(), yes=True, out=lambda line: None,
        on_saved=lambda: None,
    )

    assert built == [] and result.generated == 0
```

- [ ] **Step 5: Run to verify failure, then implement**

Run: `pytest tests/app/retrieval/test_summarizer.py -v`. Expected: collection error.

Create `backend/app/retrieval/repository.py`:

```python
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.retrieval.models import CommunitySummary


def get_summaries(session: Session, hashes: list[str]) -> dict[str, str]:
    if not hashes:
        return {}
    rows = session.execute(
        select(CommunitySummary.member_hash, CommunitySummary.summary).where(CommunitySummary.member_hash.in_(hashes))
    )
    return {member_hash: summary for member_hash, summary in rows}


def save_summary(session: Session, *, member_hash: str, summary: str, model: str) -> None:
    row = session.get(CommunitySummary, member_hash)
    if row is None:
        row = CommunitySummary(member_hash=member_hash)
        session.add(row)
    row.summary = summary
    row.model = model
    session.flush()
```

Create `backend/app/retrieval/summarizer.py`:

```python
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.graph.schemas import CommunityStats
from app.retrieval.repository import get_summaries, save_summary
from core.llm.openai_summary_client import SUMMARY_MODEL, SUMMARY_SYSTEM

# Communities smaller than this are not worth a paid summary; their statistics already say everything.
MIN_SUMMARY_SIZE = 3
CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class SummaryRun:
    generated: int
    cached: int
    skipped_small: int


def build_summary_prompt(stats: CommunityStats) -> str:
    return (
        f"Community of {stats.size} SKUs.\n"
        f"Product families: {', '.join(stats.families) or 'none'}\n"
        f"Dominant pricing category: {stats.dominant_category} ({stats.dominant_category_share:.0%} of members)\n"
        f"Discontinued SKUs: {stats.discontinued_count}\n"
        f"SKUs with required parts: {stats.requirement_count}\n"
        f"Member names ({len(stats.member_names)} shown): {'; '.join(stats.member_names)}\n"
    )


def pending_summaries(session: Session, stats_list: list[CommunityStats]) -> list[CommunityStats]:
    candidates = [s for s in stats_list if s.size >= MIN_SUMMARY_SIZE]
    cached = get_summaries(session, [s.member_hash for s in candidates])
    return [s for s in candidates if s.member_hash not in cached]


def estimate_input_tokens(pending: list[CommunityStats]) -> int:
    return sum((len(SUMMARY_SYSTEM) + len(build_summary_prompt(s))) // CHARS_PER_TOKEN for s in pending)


def summarize_communities(
    session: Session, summarizer, stats_list: list[CommunityStats], on_saved: Callable[[], None],
) -> SummaryRun:
    """Summarize only the communities with no cached summary. `on_saved` runs after each save so the caller can
    commit: a failure part-way must not throw away summaries that were already paid for."""
    pending = pending_summaries(session, stats_list)
    for stats in pending:
        text = summarizer.summarize(build_summary_prompt(stats))
        save_summary(session, member_hash=stats.member_hash, summary=text, model=SUMMARY_MODEL)
        on_saved()
    eligible = sum(1 for s in stats_list if s.size >= MIN_SUMMARY_SIZE)
    return SummaryRun(generated=len(pending), cached=eligible - len(pending), skipped_small=len(stats_list) - eligible)


def run_summary_job(
    session: Session, stats_list: list[CommunityStats], summarizer_factory: Callable[[], object], *,
    yes: bool, out: Callable[[str], None], on_saved: Callable[[], None],
) -> SummaryRun | None:
    """A dry run unless `yes`: report the plan and cost estimate, and only then build the paid client."""
    pending = pending_summaries(session, stats_list)
    out(
        f"{len(pending)} communities need a summary; estimated {estimate_input_tokens(pending)} input tokens "
        f"with model {SUMMARY_MODEL}"
    )
    if not yes:
        out("dry run: pass --yes to call the API")
        return None
    if not pending:
        return summarize_communities(session, None, stats_list, on_saved)
    run = summarize_communities(session, summarizer_factory(), stats_list, on_saved)
    out(f"generated {run.generated}, reused {run.cached} cached, skipped {run.skipped_small} small")
    return run
```

Create `backend/scripts/summarize_communities.py`:

```python
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI

from app.graph.service import global_stats
from app.retrieval.summarizer import run_summary_job
from core.config.settings import Settings
from core.db.session import make_engine, make_session_factory
from core.graph.client import get_graph_client
from core.llm.openai_summary_client import OpenAISummaryClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize graph communities with an LLM (dry run unless --yes)")
    parser.add_argument("--yes", action="store_true", help="actually call the OpenAI API (costs money)")
    args = parser.parse_args()

    settings = Settings()
    session = make_session_factory(make_engine(settings.database_url))()
    try:
        stats = global_stats(get_graph_client(), settings.graph_namespace)
        if not stats:
            print("no communities found; run POST /v1/graph/rebuild first")
            return
        run_summary_job(
            session, stats, lambda: OpenAISummaryClient(client=OpenAI(api_key=settings.openai_api_key)),
            yes=args.yes, out=print, on_saved=session.commit,
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
```

Note `run_summary_job` with nothing pending and `yes`: `summarize_communities(session, None, ...)` never calls the summarizer because nothing is pending, which is why passing `None` is safe there; that is the only path that does so.

- [ ] **Step 6: Run to verify pass**

Run: `pytest tests/core/test_openai_summary_client.py tests/app/retrieval/test_summarizer.py -v`, then the full suite. Expected: PASS. Do not run `scripts/summarize_communities.py` with `--yes`. A bare `--help` run (`.venv/Scripts/python.exe scripts/summarize_communities.py --help`) must print usage and exit 0.

- [ ] **Step 7: Commit**

```bash
git add backend/core/llm/openai_summary_client.py backend/app/retrieval/repository.py backend/app/retrieval/summarizer.py backend/scripts/summarize_communities.py backend/tests/graph_support.py backend/tests/core/test_openai_summary_client.py backend/tests/app/retrieval/__init__.py backend/tests/app/retrieval/test_summarizer.py
git commit -m "feat: add cached, cost-gated LLM summaries for graph communities"
```

---

### Task 9: SKU embeddings and the vector arm

**Files:**
- Modify: `backend/core/llm/openai_embedding_client.py`, `backend/app/retrieval/repository.py`, `backend/tests/graph_support.py`
- Create: `backend/app/retrieval/vector.py`, `backend/scripts/embed_skus.py`, `backend/tests/core/test_openai_embedding_client.py`, `backend/tests/app/retrieval/test_vector.py`

**Interfaces:**
- Consumes: Task 3 `SkuEmbedding`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS`.
- Produces:
  - `core.llm.openai_embedding_client`: `EmbeddingError`, `OpenAIEmbeddingClient(client=None).embed(texts: list[str]) -> list[list[float]]` (order preserved, count and dimension validated).
  - `app.retrieval.repository`: `skus_missing_embedding(session, model) -> list[tuple[Sku, str | None]]` (SKU and its family name), `save_embeddings(session, model, items: list[tuple[str, list[float]]])`, `has_embeddings(session) -> bool`, `nearest_skus(session, vector, k, exclude_sku_id=None) -> list[tuple[Sku, float]]`, `sku_with_family(session, sku_id) -> tuple[Sku, str | None] | None`.
  - `app.retrieval.vector`: `Embedder` protocol, `EmbeddingsNotBuilt(Exception)`, `EMBED_BATCH_SIZE = 100`, `DEFAULT_K = 5`, `sku_embedding_text(name, category, family_name) -> str`, `estimate_embedding_tokens(pending) -> int`, `embed_pending_skus(session, embedder, on_batch_saved) -> int`, `vector_search(session, embedder, text, k=5, exclude_sku_id=None) -> list[dict]`, `embedding_text_for_sku(session, sku_id) -> str | None`, `run_embedding_job(session, embedder_factory, *, yes, out, on_batch_saved) -> int | None`.
  - `tests.graph_support.FakeEmbedder` (deterministic bag-of-words vectors, records `.calls`).

- [ ] **Step 1: Write the failing client tests**

Create `backend/tests/core/test_openai_embedding_client.py`:

```python
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.llm.openai_embedding_client import (
    EMBEDDING_DIMENSIONS, EMBEDDING_MODEL, EmbeddingError, OpenAIEmbeddingClient,
)


def _vector(value):
    return [value] * EMBEDDING_DIMENSIONS


def _openai(items):
    create = MagicMock(return_value=SimpleNamespace(data=items))
    return SimpleNamespace(embeddings=SimpleNamespace(create=create)), create


def _item(index, value):
    return SimpleNamespace(index=index, embedding=_vector(value))


def test_embed_returns_vectors_in_input_order_even_if_the_api_shuffles_them():
    openai, create = _openai([_item(1, 0.2), _item(0, 0.1)])

    vectors = OpenAIEmbeddingClient(client=openai).embed(["first", "second"])

    assert vectors[0][0] == 0.1 and vectors[1][0] == 0.2
    assert create.call_args.kwargs == {"model": EMBEDDING_MODEL, "input": ["first", "second"]}


def test_embedding_nothing_makes_no_call():
    openai, create = _openai([])

    assert OpenAIEmbeddingClient(client=openai).embed([]) == []
    create.assert_not_called()


def test_a_count_mismatch_is_an_error():
    openai, _ = _openai([_item(0, 0.1)])

    with pytest.raises(EmbeddingError, match="1 embeddings for 2 inputs"):
        OpenAIEmbeddingClient(client=openai).embed(["a", "b"])


def test_missing_data_is_an_error():
    openai = SimpleNamespace(embeddings=SimpleNamespace(create=MagicMock(return_value=SimpleNamespace(data=None))))

    with pytest.raises(EmbeddingError):
        OpenAIEmbeddingClient(client=openai).embed(["a"])


def test_a_wrong_dimension_is_an_error():
    bad = SimpleNamespace(index=0, embedding=[0.1, 0.2])
    openai, _ = _openai([bad])

    with pytest.raises(EmbeddingError, match="dimension"):
        OpenAIEmbeddingClient(client=openai).embed(["a"])


def test_an_api_failure_is_wrapped():
    openai, create = _openai([])
    create.side_effect = RuntimeError("boom")

    with pytest.raises(EmbeddingError, match="boom"):
        OpenAIEmbeddingClient(client=openai).embed(["a"])
```

- [ ] **Step 2: Run to verify failure, then implement the client**

Run: `pytest tests/core/test_openai_embedding_client.py -v`. Expected: FAIL (`ImportError`).

Replace `backend/core/llm/openai_embedding_client.py`:

```python
from openai import OpenAI

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536


class EmbeddingError(Exception):
    pass


class OpenAIEmbeddingClient:
    def __init__(self, client: OpenAI | None = None) -> None:
        self._client = client or OpenAI()

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = self._client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
        except Exception as exc:
            raise EmbeddingError(f"OpenAI embedding call failed: {exc}") from exc

        items = sorted(response.data or [], key=lambda item: item.index)
        if len(items) != len(texts):
            raise EmbeddingError(f"OpenAI returned {len(items)} embeddings for {len(texts)} inputs")
        vectors = [list(item.embedding) for item in items]
        for vector in vectors:
            if len(vector) != EMBEDDING_DIMENSIONS:
                raise EmbeddingError(f"OpenAI returned a vector of dimension {len(vector)}, expected {EMBEDDING_DIMENSIONS}")
        return vectors
```

Run again: PASS.

- [ ] **Step 3: Add the fake embedder**

Append to `backend/tests/graph_support.py` (add `import math, re, zlib` and `from core.llm.openai_embedding_client import EMBEDDING_DIMENSIONS`):

```python
class FakeEmbedder:
    """Deterministic bag-of-words vectors: texts sharing words are close under cosine distance. Records every
    batch it was asked to embed. Never touches the network."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self._vector(text) for text in texts]

    @staticmethod
    def _vector(text: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIMENSIONS
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            vector[zlib.crc32(token.encode("utf-8")) % EMBEDDING_DIMENSIONS] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]
```

- [ ] **Step 4: Write the failing vector tests**

Create `backend/tests/app/retrieval/test_vector.py`:

```python
import pytest
from sqlalchemy import delete, select

from app.reference_data.models import Sku
from app.retrieval.models import SkuEmbedding
from app.retrieval.repository import has_embeddings, skus_missing_embedding
from app.retrieval.vector import (
    EMBED_BATCH_SIZE, EmbeddingsNotBuilt, embed_pending_skus, embedding_text_for_sku, estimate_embedding_tokens,
    run_embedding_job, sku_embedding_text, vector_search,
)
from core.llm.openai_embedding_client import EMBEDDING_MODEL
from tests.app.estimate.seed import seed_structure, seed_world
from tests.graph_support import FakeEmbedder


def _world(db_session):
    seed_world(db_session)
    seed_structure(db_session)


def test_embedding_text_joins_name_category_and_family():
    assert sku_embedding_text("Zorpwidget 9000", "Cat-E-A", "Zorpwidget Alpha") == "Zorpwidget 9000 | Cat-E-A | Zorpwidget Alpha"
    assert sku_embedding_text("Loose Part", "Cat-X", None) == "Loose Part | Cat-X | no family"


def test_a_sku_without_an_embedding_is_pending(db_session):
    _world(db_session)

    pending = {sku.sku_id: family for sku, family in skus_missing_embedding(db_session, EMBEDDING_MODEL)}

    assert pending["SKU-E-A1"] == "Zorpwidget Alpha"
    assert pending["SKU-E-B1"] is None


def test_embedding_pending_skus_saves_vectors_in_batches_and_is_idempotent(db_session):
    _world(db_session)
    embedder, saved = FakeEmbedder(), []

    first = embed_pending_skus(db_session, embedder, on_batch_saved=lambda: saved.append(1))
    second = embed_pending_skus(db_session, embedder, on_batch_saved=lambda: saved.append(1))

    assert first >= 8 and second == 0
    assert all(len(batch) <= EMBED_BATCH_SIZE for batch in embedder.calls)
    assert len(saved) == len(embedder.calls)
    row = db_session.get(SkuEmbedding, "SKU-E-A1")
    assert row.model == EMBEDDING_MODEL and len(row.embedding) == 1536
    assert not [sku for sku, _ in skus_missing_embedding(db_session, EMBEDDING_MODEL)]


def test_a_sku_embedded_with_another_model_is_pending_again_and_replaced(db_session):
    _world(db_session)
    embed_pending_skus(db_session, FakeEmbedder(), on_batch_saved=lambda: None)
    db_session.get(SkuEmbedding, "SKU-E-A1").model = "older-model"
    db_session.flush()

    assert "SKU-E-A1" in {sku.sku_id for sku, _ in skus_missing_embedding(db_session, EMBEDDING_MODEL)}
    embed_pending_skus(db_session, FakeEmbedder(), on_batch_saved=lambda: None)

    assert db_session.get(SkuEmbedding, "SKU-E-A1").model == EMBEDDING_MODEL


def test_search_returns_the_closest_skus_first(db_session):
    _world(db_session)
    embedder = FakeEmbedder()
    embed_pending_skus(db_session, embedder, on_batch_saved=lambda: None)

    matches = vector_search(db_session, embedder, "zorpwidget alpha 9000")

    assert matches[0]["sku_id"] == "SKU-E-A1"
    assert matches[0]["distance"] < 0.5
    assert set(matches[0]) == {"sku_id", "name", "category", "list_price", "discontinued", "in_stock", "distance"}
    assert [m["distance"] for m in matches] == sorted(m["distance"] for m in matches)
    assert len(matches) <= 5


def test_search_can_exclude_the_sku_it_started_from(db_session):
    _world(db_session)
    embedder = FakeEmbedder()
    embed_pending_skus(db_session, embedder, on_batch_saved=lambda: None)

    matches = vector_search(db_session, embedder, "zorpwidget alpha 9000", exclude_sku_id="SKU-E-A1")

    assert "SKU-E-A1" not in [m["sku_id"] for m in matches]


def test_search_with_no_embeddings_raises_a_clear_error(db_session):
    db_session.execute(delete(SkuEmbedding))
    db_session.flush()

    assert has_embeddings(db_session) is False
    with pytest.raises(EmbeddingsNotBuilt, match="embed_skus"):
        vector_search(db_session, FakeEmbedder(), "anything")


def test_embedding_text_for_a_known_sku_uses_its_family(db_session):
    _world(db_session)

    assert embedding_text_for_sku(db_session, "SKU-E-A1") == "Zorpwidget Alpha 9000 | Cat-E-A | Zorpwidget Alpha"
    assert embedding_text_for_sku(db_session, "SKU-NOPE") is None


def test_token_estimate_grows_with_the_pending_list(db_session):
    _world(db_session)
    pending = skus_missing_embedding(db_session, EMBEDDING_MODEL)

    assert 0 < estimate_embedding_tokens(pending[:1]) < estimate_embedding_tokens(pending[:5])
    assert estimate_embedding_tokens([]) == 0


def test_a_dry_run_reports_the_plan_and_never_builds_the_client(db_session):
    _world(db_session)
    lines, built = [], []

    result = run_embedding_job(
        db_session, lambda: built.append(1) or FakeEmbedder(), yes=False, out=lines.append, on_batch_saved=lambda: None,
    )

    assert result is None and built == []
    text = "\n".join(lines)
    assert "SKUs need an embedding" in text and EMBEDDING_MODEL in text
    assert "dry run" in text and "--yes" in text
    assert db_session.get(SkuEmbedding, "SKU-E-A1") is None


def test_the_job_with_yes_builds_the_client_and_embeds(db_session):
    _world(db_session)
    embedder = FakeEmbedder()

    result = run_embedding_job(db_session, lambda: embedder, yes=True, out=lambda line: None, on_batch_saved=lambda: None)

    assert result >= 8 and embedder.calls
    assert db_session.get(SkuEmbedding, "SKU-E-A1") is not None
```

- [ ] **Step 5: Run to verify failure, then implement**

Run: `pytest tests/app/retrieval/test_vector.py -v`. Expected: collection error.

Append to `backend/app/retrieval/repository.py` (extend the imports: `from sqlalchemy import and_, select`, `from app.reference_data.models import ProductFamily, Sku`, `from app.retrieval.models import CommunitySummary, SkuEmbedding`):

```python
def skus_missing_embedding(session: Session, model: str) -> list[tuple[Sku, str | None]]:
    """SKUs with no embedding from this model, with their family name (None when they have no family)."""
    rows = session.execute(
        select(Sku, ProductFamily.name)
        .outerjoin(ProductFamily, Sku.family_id == ProductFamily.family_id)
        .outerjoin(SkuEmbedding, and_(SkuEmbedding.sku_id == Sku.sku_id, SkuEmbedding.model == model))
        .where(SkuEmbedding.sku_id.is_(None))
        .order_by(Sku.sku_id)
    )
    return [(sku, family_name) for sku, family_name in rows]


def save_embeddings(session: Session, model: str, items: list[tuple[str, list[float]]]) -> None:
    for sku_id, vector in items:
        row = session.get(SkuEmbedding, sku_id)
        if row is None:
            row = SkuEmbedding(sku_id=sku_id)
            session.add(row)
        row.embedding = vector
        row.model = model
    session.flush()


def has_embeddings(session: Session) -> bool:
    return session.scalar(select(SkuEmbedding.sku_id).limit(1)) is not None


def nearest_skus(
    session: Session, vector: list[float], k: int, exclude_sku_id: str | None = None,
) -> list[tuple[Sku, float]]:
    distance = SkuEmbedding.embedding.cosine_distance(vector)
    statement = select(Sku, distance).join(SkuEmbedding, SkuEmbedding.sku_id == Sku.sku_id)
    if exclude_sku_id is not None:
        statement = statement.where(Sku.sku_id != exclude_sku_id)
    rows = session.execute(statement.order_by(distance, Sku.sku_id).limit(k))
    return [(sku, float(value)) for sku, value in rows]


def sku_with_family(session: Session, sku_id: str) -> tuple[Sku, str | None] | None:
    row = session.execute(
        select(Sku, ProductFamily.name)
        .outerjoin(ProductFamily, Sku.family_id == ProductFamily.family_id)
        .where(Sku.sku_id == sku_id)
    ).first()
    return (row[0], row[1]) if row else None
```

Create `backend/app/retrieval/vector.py`:

```python
from collections.abc import Callable
from typing import Protocol

from sqlalchemy.orm import Session

from app.reference_data.models import Sku
from app.retrieval.repository import (
    has_embeddings, nearest_skus, save_embeddings, sku_with_family, skus_missing_embedding,
)
from core.llm.openai_embedding_client import EMBEDDING_MODEL

EMBED_BATCH_SIZE = 100
DEFAULT_K = 5
CHARS_PER_TOKEN = 4


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class EmbeddingsNotBuilt(Exception):
    pass


def sku_embedding_text(name: str, category: str, family_name: str | None) -> str:
    return f"{name} | {category} | {family_name or 'no family'}"


def estimate_embedding_tokens(pending: list[tuple[Sku, str | None]]) -> int:
    return sum(len(sku_embedding_text(sku.name, sku.category, family)) // CHARS_PER_TOKEN + 1 for sku, family in pending)


def embed_pending_skus(session: Session, embedder: Embedder, on_batch_saved: Callable[[], None]) -> int:
    """Embed every SKU that has no embedding from the current model. `on_batch_saved` runs after each batch so the
    caller can commit; a failure part-way keeps the batches already paid for."""
    pending = skus_missing_embedding(session, EMBEDDING_MODEL)
    for start in range(0, len(pending), EMBED_BATCH_SIZE):
        batch = pending[start:start + EMBED_BATCH_SIZE]
        vectors = embedder.embed([sku_embedding_text(sku.name, sku.category, family) for sku, family in batch])
        save_embeddings(session, EMBEDDING_MODEL, [(sku.sku_id, vector) for (sku, _), vector in zip(batch, vectors)])
        on_batch_saved()
    return len(pending)


def embedding_text_for_sku(session: Session, sku_id: str) -> str | None:
    found = sku_with_family(session, sku_id)
    if found is None:
        return None
    sku, family_name = found
    return sku_embedding_text(sku.name, sku.category, family_name)


def vector_search(
    session: Session, embedder: Embedder, text: str, k: int = DEFAULT_K, exclude_sku_id: str | None = None,
) -> list[dict]:
    if not has_embeddings(session):
        raise EmbeddingsNotBuilt("SKU embeddings are not built; run scripts/embed_skus.py")
    [vector] = embedder.embed([text])
    return [
        {
            "sku_id": sku.sku_id, "name": sku.name, "category": sku.category, "list_price": sku.list_price,
            "discontinued": sku.discontinued, "in_stock": sku.in_stock, "distance": round(distance, 4),
        }
        for sku, distance in nearest_skus(session, vector, k, exclude_sku_id)
    ]


def run_embedding_job(
    session: Session, embedder_factory: Callable[[], Embedder], *, yes: bool, out: Callable[[str], None],
    on_batch_saved: Callable[[], None],
) -> int | None:
    """A dry run unless `yes`: report the plan and cost estimate, and only then build the paid client."""
    pending = skus_missing_embedding(session, EMBEDDING_MODEL)
    out(f"{len(pending)} SKUs need an embedding; estimated {estimate_embedding_tokens(pending)} tokens with model {EMBEDDING_MODEL}")
    if not yes:
        out("dry run: pass --yes to call the API")
        return None
    if not pending:
        return 0
    count = embed_pending_skus(session, embedder_factory(), on_batch_saved)
    out(f"embedded {count} SKUs")
    return count
```

Create `backend/scripts/embed_skus.py`:

```python
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI

from app.retrieval.vector import run_embedding_job
from core.config.settings import Settings
from core.db.session import make_engine, make_session_factory
from core.llm.openai_embedding_client import OpenAIEmbeddingClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Embed SKU names for vector search (dry run unless --yes)")
    parser.add_argument("--yes", action="store_true", help="actually call the OpenAI API (costs money)")
    args = parser.parse_args()

    settings = Settings()
    session = make_session_factory(make_engine(settings.database_url))()
    try:
        run_embedding_job(
            session, lambda: OpenAIEmbeddingClient(client=OpenAI(api_key=settings.openai_api_key)),
            yes=args.yes, out=print, on_batch_saved=session.commit,
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run to verify pass**

Run: `pytest tests/core/test_openai_embedding_client.py tests/app/retrieval/test_vector.py -v`, then the full suite. Expected: PASS. Do not run `scripts/embed_skus.py --yes`; `--help` must print usage and exit 0. In your handoff, report the SKU count and token estimate the dry run prints against the dev database (run `.venv/Scripts/python.exe scripts/embed_skus.py` with no flag, with `DATABASE_URL` and `OPENAI_API_KEY=unused` inline).

- [ ] **Step 7: Commit**

```bash
git add backend/core/llm/openai_embedding_client.py backend/app/retrieval/repository.py backend/app/retrieval/vector.py backend/scripts/embed_skus.py backend/tests/graph_support.py backend/tests/core/test_openai_embedding_client.py backend/tests/app/retrieval/test_vector.py
git commit -m "feat: add SKU embeddings, a cost-gated embedding job, and pgvector similarity search"
```

---

### Task 10: Shared SQL search, the rule-based router, the knowledge service, and the retrieval and graph endpoints

**Files:**
- Create: `backend/app/reference_data/search.py`, `backend/app/retrieval/router.py`, `backend/app/retrieval/service.py`, `backend/api/v1/retrieval/__init__.py` (empty), `backend/api/v1/retrieval/request.py`, `backend/api/v1/retrieval/response.py`, `backend/api/v1/retrieval/route.py`, `backend/api/v1/graph/__init__.py` (empty), `backend/api/v1/graph/response.py`, `backend/api/v1/graph/route.py`, `backend/tests/app/reference_data/test_search.py`, `backend/tests/app/retrieval/test_router.py`, `backend/tests/app/retrieval/test_service.py`, `backend/tests/api/v1/test_retrieval_route.py`, `backend/tests/api/v1/test_graph_route.py`
- Modify: `backend/app/estimate/tools.py` (use the shared search), `backend/main.py`

**Interfaces:**
- Consumes: Tasks 5 to 9.
- Produces:
  - `app.reference_data.search`: `CUSTOMER_MATCH_THRESHOLD = 80`, `SKU_SEARCH_CUTOFF = 60`, `SKU_SEARCH_LIMIT = 5`, `CUSTOMER_SEARCH_LIMIT = 3`, `find_skus(session, query) -> list[Sku]`, `find_customers(session, query) -> list[Customer]`. An exact id wins; otherwise fuzzy by name, best first, ties broken by id.
  - `app.retrieval.router`: `Route` (`sql`, `graph_local`, `graph_global`, `vector`), `RouteDecision(route, rule, entity_id)`, `route_question(question) -> RouteDecision`.
  - `app.retrieval.service`: `RetrievalResult(route: Route, rule: str, evidence: dict)`, `KnowledgeService(session, graph, embedder)` with `.ask(question) -> RetrievalResult`.
  - `api.v1.retrieval.route`: `POST /v1/retrieval/ask` and `get_embedding_client()`. `api.v1.graph.route`: `POST /v1/graph/rebuild`.

- [ ] **Step 1: Write the failing search tests**

Create `backend/tests/app/reference_data/test_search.py`:

```python
from app.reference_data.repository import upsert_sku
from app.reference_data.search import find_customers, find_skus
from tests.app.estimate.seed import seed_world


def test_an_exact_sku_id_wins_over_any_fuzzy_match(db_session):
    seed_world(db_session)

    assert [s.sku_id for s in find_skus(db_session, "SKU-E-A1")] == ["SKU-E-A1"]


def test_fuzzy_name_search_ranks_the_best_match_first(db_session):
    seed_world(db_session)

    assert find_skus(db_session, "Zorpwidget Alpha 9000")[0].sku_id == "SKU-E-A1"


def test_name_ties_break_by_sku_id(db_session):
    seed_world(db_session)
    for sku_id in ("SKU-TIE-2", "SKU-TIE-1"):
        upsert_sku(db_session, sku_id=sku_id, name="Quillfargle Tiebreak Unit", category="Cat-TIE", list_price=5.0,
                   discontinued=False, replaced_by=None, in_stock=True)
    db_session.flush()

    ids = [s.sku_id for s in find_skus(db_session, "Quillfargle Tiebreak Unit")]

    assert ids.index("SKU-TIE-1") < ids.index("SKU-TIE-2")


def test_an_unrelated_query_matches_nothing(db_session):
    seed_world(db_session)

    assert find_skus(db_session, "qqqqzzzz nothing like this") == []
    assert find_customers(db_session, "qqqqzzzz nothing like this") == []


def test_customer_lookup_by_id_and_by_fuzzy_name(db_session):
    seed_world(db_session)

    assert [c.customer_id for c in find_customers(db_session, "CUST-E1")] == ["CUST-E1"]
    assert find_customers(db_session, "vexthorn mechanical")[0].customer_id == "CUST-E1"
```

Run: `pytest tests/app/reference_data/test_search.py -v`. Expected: collection error.

- [ ] **Step 2: Implement the shared search and use it from the tools**

Create `backend/app/reference_data/search.py`:

```python
from rapidfuzz import fuzz, process
from sqlalchemy.orm import Session

from app.reference_data.models import Customer, Sku
from app.reference_data.repository import all_customers, all_skus, get_customer, get_sku

# Looser than intake's 90: callers here read the candidate list and judge, they do not auto-resolve.
CUSTOMER_MATCH_THRESHOLD = 80
SKU_SEARCH_CUTOFF = 60
SKU_SEARCH_LIMIT = 5
CUSTOMER_SEARCH_LIMIT = 3


def find_skus(session: Session, query: str) -> list[Sku]:
    exact = get_sku(session, query)
    if exact is not None:
        return [exact]
    names = {s.sku_id: s.name for s in all_skus(session)}
    hits = process.extract(
        query, names, scorer=fuzz.WRatio, processor=str.lower, limit=SKU_SEARCH_LIMIT, score_cutoff=SKU_SEARCH_CUTOFF,
    )
    return [get_sku(session, key) for _, _, key in hits]


def find_customers(session: Session, query: str) -> list[Customer]:
    exact = get_customer(session, query)
    if exact is not None:
        return [exact]
    names = {c.customer_id: c.name for c in all_customers(session)}
    hits = process.extract(
        query, names, scorer=fuzz.token_sort_ratio, processor=str.lower, limit=CUSTOMER_SEARCH_LIMIT,
        score_cutoff=CUSTOMER_MATCH_THRESHOLD,
    )
    return [get_customer(session, key) for _, _, key in hits]
```

In `backend/app/estimate/tools.py`: delete the three constants `CUSTOMER_MATCH_THRESHOLD`, `SKU_SEARCH_CUTOFF`, `SKU_SEARCH_LIMIT` and the `rapidfuzz` import (grep the repo first, `grep -rn "CUSTOMER_MATCH_THRESHOLD\|SKU_SEARCH_" backend`, and repoint any other importer to `app.reference_data.search`). Import `find_customers, find_skus` from `app.reference_data.search`, drop `all_customers, all_skus, get_customer, get_sku` from the repository import only if no longer used in the file (`get_sku` is still used by `check_stock`, `get_related_parts` and `predict_price`; keep what is used). Replace the bodies:

```python
def lookup_customer(ctx: ToolContext, *, query: str) -> dict:
    return {"matches": [_customer_entry(ctx, c) for c in find_customers(ctx.session, query)]}


def search_price_book(ctx: ToolContext, *, query: str) -> dict:
    return {"results": [_sku_entry(ctx.session, s) for s in find_skus(ctx.session, query)]}
```

Run: `pytest tests/app/reference_data/test_search.py tests/app/estimate/test_tools.py -v`. Expected: PASS (the existing tool tests still pass unchanged).

- [ ] **Step 3: Write the failing router tests**

Create `backend/tests/app/retrieval/test_router.py`:

```python
import pytest

from app.retrieval.router import Route, route_question


@pytest.mark.parametrize("question, route, rule, entity", [
    ("which product groups have the most discontinued items", Route.GRAPH_GLOBAL, "portfolio_phrasing", None),
    ("Which PRODUCT GROUPS are most exposed", Route.GRAPH_GLOBAL, "portfolio_phrasing", None),
    ("give me the biggest groups across the catalog", Route.GRAPH_GLOBAL, "portfolio_phrasing", None),
    ("something like a 3 ton condenser", Route.VECTOR, "similarity_phrasing", None),
    ("similar to SKU-0001", Route.VECTOR, "similarity_phrasing", "SKU-0001"),
    ("an alternative to sku-0542", Route.VECTOR, "similarity_phrasing", "SKU-0542"),
    ("what is SKU-0542 replaced by", Route.GRAPH_LOCAL, "id_with_relationship_phrasing", "SKU-0542"),
    ("what parts does sku-0601 require", Route.GRAPH_LOCAL, "id_with_relationship_phrasing", "SKU-0601"),
    ("what does CTR-0004 cover", Route.GRAPH_LOCAL, "id_with_relationship_phrasing", "CTR-0004"),
    ("how is CUST-0001 connected to its contracts", Route.GRAPH_LOCAL, "id_with_relationship_phrasing", "CUST-0001"),
    ("price of SKU-0001", Route.SQL, "id_lookup", "SKU-0001"),
    ("CUST-0001 details", Route.SQL, "id_lookup", "CUST-0001"),
    ("show CTR-0004", Route.SQL, "id_lookup", "CTR-0004"),
    ("info on SITE-0001", Route.GRAPH_LOCAL, "non_sql_id", "SITE-0001"),
    ("what is FAM-0003", Route.GRAPH_LOCAL, "non_sql_id", "FAM-0003"),
    ("brass elbow 1 in", Route.SQL, "name_search", None),
    ("", Route.SQL, "name_search", None),
    ("   ", Route.SQL, "name_search", None),
])
def test_questions_are_routed_by_rule(question, route, rule, entity):
    decision = route_question(question)

    assert (decision.route, decision.rule, decision.entity_id) == (route, rule, entity)


def test_portfolio_phrasing_beats_similarity_and_ids():
    """(Review Focus) A question matching several rules takes the first in precedence order."""
    decision = route_question("which product groups are similar to SKU-0001")

    assert decision.route is Route.GRAPH_GLOBAL and decision.entity_id == "SKU-0001"


def test_similarity_beats_relationship_phrasing():
    decision = route_question("an alternative to SKU-0001 that replaces it")

    assert decision.route is Route.VECTOR


def test_ids_are_uppercased_and_letter_ids_are_recognised():
    """(Review Focus) Lowercase ids and the test-data style ids with letters."""
    assert route_question("price of sku-e-a1").entity_id == "SKU-E-A1"
    assert route_question("price of Sku-0001, please").entity_id == "SKU-0001"


def test_an_id_embedded_in_a_longer_word_is_not_an_id():
    assert route_question("the SKU-0001x thing").entity_id == "SKU-0001X"
    assert route_question("MYSKU-0001").entity_id is None


def test_unicode_text_around_an_id_still_routes():
    decision = route_question("prix de SKU-0001 s'il vous plaît, très vite")

    assert (decision.route, decision.entity_id) == (Route.SQL, "SKU-0001")
```

- [ ] **Step 4: Run to verify failure, then implement the router**

Run: `pytest tests/app/retrieval/test_router.py -v`. Expected: collection error.

Create `backend/app/retrieval/router.py`:

```python
import re
from dataclasses import dataclass
from enum import Enum


class Route(str, Enum):
    SQL = "sql"
    GRAPH_LOCAL = "graph_local"
    GRAPH_GLOBAL = "graph_global"
    VECTOR = "vector"


@dataclass(frozen=True)
class RouteDecision:
    route: Route
    rule: str
    entity_id: str | None


ID_PATTERN = re.compile(r"\b(?:SKU|CUST|CTR|SITE|PRJ|FAM)-[A-Z0-9]+(?:-[A-Z0-9]+)*\b", re.IGNORECASE)
# The ids that have a plain Postgres lookup. Sites, projects and families exist only as graph nodes.
SQL_ID_PREFIXES = ("SKU", "CUST", "CTR")
PORTFOLIO = re.compile(
    r"\b(?:which product groups|product groups|across the catalog|most exposed|portfolio|clusters|communities|"
    r"themes|biggest groups|catalog overview)\b",
    re.IGNORECASE,
)
SIMILARITY = re.compile(
    r"\b(?:similar to|alternatives? to|something like|something for|equivalent to|comparable to|looks like)\b",
    re.IGNORECASE,
)
RELATIONSHIP = re.compile(
    r"\b(?:replac\w*|require\w*|goes with|covers?|covered|contracts?|connected|related|neighbou?rs|linked)\b",
    re.IGNORECASE,
)


def route_question(question: str) -> RouteDecision:
    """Pick where a question is answered. Free and deterministic; the precedence is the design: portfolio phrasing,
    then similarity, then an id with relationship phrasing, then an id, then a name."""
    match = ID_PATTERN.search(question)
    entity_id = match.group(0).upper() if match else None

    if PORTFOLIO.search(question):
        return RouteDecision(Route.GRAPH_GLOBAL, "portfolio_phrasing", entity_id)
    if SIMILARITY.search(question):
        return RouteDecision(Route.VECTOR, "similarity_phrasing", entity_id)
    if entity_id and RELATIONSHIP.search(question):
        return RouteDecision(Route.GRAPH_LOCAL, "id_with_relationship_phrasing", entity_id)
    if entity_id:
        if entity_id.split("-")[0] in SQL_ID_PREFIXES:
            return RouteDecision(Route.SQL, "id_lookup", entity_id)
        return RouteDecision(Route.GRAPH_LOCAL, "non_sql_id", entity_id)
    return RouteDecision(Route.SQL, "name_search", None)
```

Run again: PASS. (If `test_an_id_embedded_in_a_longer_word_is_not_an_id` disagrees with how `\b` treats `SKU-0001x`, `[A-Z0-9]+` is greedy and case-insensitive so it captures `SKU-0001X`; that is the intended behavior and the test states it. `MYSKU-0001` has no word boundary before `SKU`, so it is not an id.)

- [ ] **Step 5: Write the failing knowledge service tests**

Create `backend/tests/app/retrieval/test_service.py`:

```python
from app.graph.helper import member_hash
from app.graph.service import run_communities
from app.retrieval.repository import save_summary
from app.retrieval.router import Route
from app.retrieval.service import KnowledgeService
from app.retrieval.vector import embed_pending_skus
from core.llm.openai_summary_client import SUMMARY_MODEL
from tests.app.estimate.seed import seed_structure, seed_world
from tests.graph_support import FakeEmbedder, seed_clusters


def _service(db_session, make_reader, embedder=None):
    reader = make_reader()
    return KnowledgeService(session=db_session, graph=reader, embedder=embedder or FakeEmbedder())


def _world(db_session):
    seed_world(db_session)
    seed_structure(db_session)


def test_an_id_question_is_answered_from_sql(db_session, make_reader):
    _world(db_session)
    service = _service(db_session, make_reader)

    sku = service.ask("price of SKU-E-A1")
    customer = service.ask("CUST-E1 details")
    contract = service.ask("show CTR-E1")

    assert sku.route is Route.SQL and sku.rule == "id_lookup"
    assert sku.evidence["skus"][0]["sku_id"] == "SKU-E-A1" and sku.evidence["skus"][0]["list_price"] == 100.0
    assert customer.evidence["customers"][0]["customer_id"] == "CUST-E1"
    assert contract.evidence["contracts"][0]["discount_pct"] == 10.0
    assert contract.evidence["contracts"][0]["covered_categories"] == ["Cat-E-A"]


def test_an_unknown_sql_id_returns_empty_evidence_not_an_error(db_session, make_reader):
    _world(db_session)

    result = _service(db_session, make_reader).ask("price of SKU-NOPE")

    assert result.evidence == {"skus": []}


def test_a_name_question_searches_skus_and_customers(db_session, make_reader):
    _world(db_session)

    result = _service(db_session, make_reader).ask("Zorpwidget Alpha 9000")

    assert result.rule == "name_search"
    assert result.evidence["skus"][0]["sku_id"] == "SKU-E-A1"
    assert result.evidence["customers"] == []


def test_an_empty_question_falls_back_to_an_empty_name_search(db_session, make_reader):
    _world(db_session)

    result = _service(db_session, make_reader).ask("")

    assert result.route is Route.SQL
    assert result.evidence["customers"] == []


def test_a_relationship_question_is_answered_from_the_graph_neighbourhood(db_session, make_reader):
    _world(db_session)

    result = _service(db_session, make_reader).ask("what does SKU-E-B1 require")

    assert result.route is Route.GRAPH_LOCAL
    assert result.evidence["center"] == "SKU-E-B1"
    assert "SKU-E-A1" in {n["id"] for n in result.evidence["nodes"]}
    assert result.evidence["truncated"] is False


def test_a_graph_question_about_an_unknown_id_reports_an_error(db_session, make_reader):
    _world(db_session)

    result = _service(db_session, make_reader).ask("what requires SKU-NOPE")

    assert result.route is Route.GRAPH_LOCAL
    assert "SKU-NOPE" in result.evidence["error"]


def test_a_portfolio_question_says_so_before_communities_exist(db_session, make_reader):
    _world(db_session)

    result = _service(db_session, make_reader).ask("which product groups are most exposed")

    assert result.route is Route.GRAPH_GLOBAL
    assert result.evidence["communities"] == []
    assert "rebuild" in result.evidence["note"]


def test_a_portfolio_question_returns_community_statistics_with_cached_summaries(db_session, graph_client, graph_ns, make_reader):
    seed_clusters(db_session)
    service = _service(db_session, make_reader)
    run_communities(graph_client, graph_ns)
    ids = [f"SKU-L-X{i}" for i in range(1, 5)]
    save_summary(db_session, member_hash=member_hash(ids), summary="The Xylo cluster.", model=SUMMARY_MODEL)

    result = service.ask("which product groups are most exposed")

    x = next(c for c in result.evidence["communities"] if "SKU-L-X1" in c["example_sku_ids"])
    y = next(c for c in result.evidence["communities"] if "SKU-L-Y1" in c["example_sku_ids"])
    assert x["summary"] == "The Xylo cluster." and x["size"] == 4 and x["discontinued_count"] == 1
    assert y["summary"] is None


def test_a_similarity_question_uses_the_vector_arm(db_session, make_reader):
    _world(db_session)
    embedder = FakeEmbedder()
    embed_pending_skus(db_session, embedder, on_batch_saved=lambda: None)
    service = _service(db_session, make_reader, embedder)

    result = service.ask("something like zorpwidget alpha 9000")

    assert result.route is Route.VECTOR and result.rule == "similarity_phrasing"
    assert result.evidence["matches"][0]["sku_id"] == "SKU-E-A1"


def test_similar_to_a_sku_embeds_that_skus_text_and_excludes_it(db_session, make_reader):
    _world(db_session)
    embedder = FakeEmbedder()
    embed_pending_skus(db_session, embedder, on_batch_saved=lambda: None)
    embedder.calls.clear()
    service = _service(db_session, make_reader, embedder)

    result = service.ask("similar to SKU-E-A1")

    assert embedder.calls == [["Zorpwidget Alpha 9000 | Cat-E-A | Zorpwidget Alpha"]]
    assert "SKU-E-A1" not in [m["sku_id"] for m in result.evidence["matches"]]
```

- [ ] **Step 6: Run to verify failure, then implement the service**

Run: `pytest tests/app/retrieval/test_service.py -v`. Expected: collection error.

Create `backend/app/retrieval/service.py`:

```python
from dataclasses import asdict, dataclass

from sqlalchemy.orm import Session

from app.graph.reader import GraphReader
from app.graph.service import NodeNotFound, global_stats, local_query
from app.reference_data.repository import get_contract, get_customer, get_sku
from app.reference_data.search import find_customers, find_skus
from app.retrieval.repository import get_summaries
from app.retrieval.router import Route, RouteDecision, route_question
from app.retrieval.vector import Embedder, embedding_text_for_sku, vector_search


@dataclass(frozen=True)
class RetrievalResult:
    route: Route
    rule: str
    evidence: dict


def _sku_evidence(sku) -> dict:
    return {
        "sku_id": sku.sku_id, "name": sku.name, "category": sku.category, "list_price": sku.list_price,
        "discontinued": sku.discontinued, "in_stock": sku.in_stock,
    }


def _customer_evidence(customer) -> dict:
    return {"customer_id": customer.customer_id, "name": customer.name, "account_tier": customer.account_tier}


def _contract_evidence(contract) -> dict:
    return {
        "contract_id": contract.contract_id, "customer_id": contract.customer_id,
        "discount_pct": contract.discount_pct, "covered_categories": list(contract.covered_categories),
        "effective_from": contract.effective_from.isoformat(), "effective_to": contract.effective_to.isoformat(),
    }


@dataclass(frozen=True)
class KnowledgeService:
    """Answers open-ended questions with evidence from the source that fits: Postgres, the graph, or vectors."""

    session: Session
    graph: GraphReader
    embedder: Embedder

    def ask(self, question: str) -> RetrievalResult:
        decision = route_question(question)
        if decision.route is Route.GRAPH_GLOBAL:
            evidence = self._global()
        elif decision.route is Route.GRAPH_LOCAL:
            evidence = self._local(decision)
        elif decision.route is Route.VECTOR:
            evidence = self._vector(decision, question)
        else:
            evidence = self._sql(decision, question)
        return RetrievalResult(route=decision.route, rule=decision.rule, evidence=evidence)

    def _sql(self, decision: RouteDecision, question: str) -> dict:
        if decision.entity_id is None:
            return {
                "skus": [_sku_evidence(s) for s in find_skus(self.session, question)],
                "customers": [_customer_evidence(c) for c in find_customers(self.session, question)],
            }
        prefix = decision.entity_id.split("-")[0]
        if prefix == "SKU":
            sku = get_sku(self.session, decision.entity_id)
            return {"skus": [_sku_evidence(sku)] if sku else []}
        if prefix == "CUST":
            customer = get_customer(self.session, decision.entity_id)
            return {"customers": [_customer_evidence(customer)] if customer else []}
        contract = get_contract(self.session, decision.entity_id)
        return {"contracts": [_contract_evidence(contract)] if contract else []}

    def _local(self, decision: RouteDecision) -> dict:
        try:
            return asdict(local_query(self.graph.client, self.graph.ns, decision.entity_id))
        except NodeNotFound as exc:
            return {"error": str(exc)}

    def _global(self) -> dict:
        stats = global_stats(self.graph.client, self.graph.ns)
        if not stats:
            return {"communities": [], "note": "no communities computed yet; run POST /v1/graph/rebuild"}
        summaries = get_summaries(self.session, [s.member_hash for s in stats])
        return {"communities": [{**asdict(s), "summary": summaries.get(s.member_hash)} for s in stats]}

    def _vector(self, decision: RouteDecision, question: str) -> dict:
        text, exclude = question, None
        if decision.entity_id and decision.entity_id.startswith("SKU-"):
            sku_text = embedding_text_for_sku(self.session, decision.entity_id)
            if sku_text is not None:
                text, exclude = sku_text, decision.entity_id
        return {"matches": vector_search(self.session, self.embedder, text, exclude_sku_id=exclude)}
```

Run: `pytest tests/app/retrieval -v`. Expected: PASS.

- [ ] **Step 7: Write the failing endpoint tests**

Create `backend/tests/api/v1/test_retrieval_route.py`:

```python
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from api.v1.retrieval.route import get_embedding_client
from app.retrieval.models import SkuEmbedding
from app.retrieval.vector import embed_pending_skus
from core.db.session import get_session
from core.graph.client import get_graph_client
from core.llm.openai_embedding_client import EmbeddingError
from main import app
from tests.app.estimate.seed import seed_structure, seed_world
from tests.graph_support import FailingGraphClient, FakeEmbedder


def _ask(db_session, question, embedder=None, overrides=None):
    app.dependency_overrides[get_session] = lambda: db_session
    app.dependency_overrides[get_embedding_client] = lambda: embedder or FakeEmbedder()
    for dependency, factory in (overrides or {}).items():
        app.dependency_overrides[dependency] = factory
    try:
        return TestClient(app).post("/v1/retrieval/ask", json={"question": question})
    finally:
        app.dependency_overrides.clear()


def _world(db_session, make_reader):
    seed_world(db_session)
    seed_structure(db_session)
    make_reader()


def test_ask_answers_an_id_question_from_sql(db_session, make_reader):
    _world(db_session, make_reader)

    response = _ask(db_session, "price of SKU-E-A1")

    body = response.json()
    assert response.status_code == 200
    assert (body["route"], body["rule"]) == ("sql", "id_lookup")
    assert body["evidence"]["skus"][0]["sku_id"] == "SKU-E-A1"


def test_ask_answers_a_relationship_question_from_the_graph(db_session, make_reader):
    _world(db_session, make_reader)

    body = _ask(db_session, "what does SKU-E-B1 require").json()

    assert body["route"] == "graph_local"
    assert "SKU-E-A1" in {n["id"] for n in body["evidence"]["nodes"]}


def test_ask_answers_a_similarity_question_from_vectors(db_session, make_reader):
    _world(db_session, make_reader)
    embedder = FakeEmbedder()
    embed_pending_skus(db_session, embedder, on_batch_saved=lambda: None)

    body = _ask(db_session, "similar to SKU-E-A1", embedder=embedder).json()

    assert body["route"] == "vector"
    assert "SKU-E-A1" not in [m["sku_id"] for m in body["evidence"]["matches"]]


def test_a_vector_question_before_embeddings_exist_is_a_409(db_session, make_reader):
    _world(db_session, make_reader)
    db_session.execute(delete(SkuEmbedding))
    db_session.flush()

    response = _ask(db_session, "something like a zorpwidget")

    assert response.status_code == 409
    assert "embed_skus" in response.json()["detail"]


def test_an_embedding_failure_is_a_502(db_session, make_reader):
    _world(db_session, make_reader)
    embed_pending_skus(db_session, FakeEmbedder(), on_batch_saved=lambda: None)

    class FailingEmbedder:
        def embed(self, texts):
            raise EmbeddingError("boom")

    response = _ask(db_session, "something like a zorpwidget", embedder=FailingEmbedder())

    assert response.status_code == 502


def test_a_graph_question_with_the_graph_down_is_a_503(db_session):
    seed_world(db_session)

    response = _ask(
        db_session, "what does SKU-E-B1 require", overrides={get_graph_client: lambda: FailingGraphClient()},
    )

    assert response.status_code == 503


def test_a_sql_question_still_works_with_the_graph_down(db_session):
    seed_world(db_session)

    response = _ask(db_session, "price of SKU-E-A1", overrides={get_graph_client: lambda: FailingGraphClient()})

    assert response.status_code == 200


@pytest.mark.parametrize("question", ["", "   ", "x" * 1001])
def test_empty_or_oversized_questions_are_rejected(db_session, question):
    """(Review Focus) Whitespace-only text is stripped to empty and rejected."""
    assert _ask(db_session, question).status_code == 422


def test_get_embedding_client_builds_openai_client_with_settings_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-from-settings")

    assert get_embedding_client()._client.api_key == "sk-test-from-settings"
```

Create `backend/tests/api/v1/test_graph_route.py`:

```python
from fastapi.testclient import TestClient

from app.intake.repository import save_quote_request
from core.db.session import get_session
from core.graph.client import get_graph_client
from main import app
from tests.app.estimate.seed import seed_structure, seed_world
from tests.graph_support import FailingGraphClient, graph_node


def _rebuild(db_session, overrides=None):
    app.dependency_overrides[get_session] = lambda: db_session
    for dependency, factory in (overrides or {}).items():
        app.dependency_overrides[dependency] = factory
    try:
        return TestClient(app).post("/v1/graph/rebuild")
    finally:
        app.dependency_overrides.clear()


def test_rebuild_reloads_the_graph_and_reports_counts_and_communities(db_session, graph_client, graph_ns):
    seed_world(db_session)
    seed_structure(db_session)
    request = save_quote_request(
        db_session, raw_email_text="x", parsed_json={}, content_fingerprint={"sku_ids": []},
        style_fingerprint={"tokens": []}, customer_id="CUST-E1",
    )

    response = _rebuild(db_session)

    body = response.json()
    assert response.status_code == 200
    assert body["namespace"] == graph_ns
    assert len(body["fingerprint"]) == 32
    assert body["node_counts"]["SKU"] >= 8 and body["edge_counts"]["REQUIRES"] >= 1
    assert body["community_count"] >= 1 and body["largest_community_size"] >= 1
    assert graph_node(graph_client, graph_ns, "SKU-E-A1") is not None
    assert graph_node(graph_client, graph_ns, str(request.id)) is not None


def test_rebuild_is_a_503_when_the_graph_is_down(db_session):
    seed_world(db_session)

    response = _rebuild(db_session, overrides={get_graph_client: lambda: FailingGraphClient()})

    assert response.status_code == 503
```

- [ ] **Step 8: Run to verify failure, then implement the routes**

Run: `pytest tests/api/v1/test_retrieval_route.py tests/api/v1/test_graph_route.py -v`. Expected: collection error.

Create `backend/api/v1/retrieval/__init__.py` (empty) and `backend/api/v1/retrieval/request.py`:

```python
from pydantic import BaseModel, ConfigDict, Field


class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=1000)
```

`backend/api/v1/retrieval/response.py`:

```python
from pydantic import BaseModel


class AskResponse(BaseModel):
    route: str
    rule: str
    evidence: dict
```

`backend/api/v1/retrieval/route.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.v1.retrieval.request import AskRequest
from api.v1.retrieval.response import AskResponse
from app.graph.reader import GraphReader
from app.retrieval.service import KnowledgeService
from app.retrieval.vector import EmbeddingsNotBuilt
from core.config.settings import Settings
from core.db.session import get_session
from core.graph.client import GraphClient, GraphUnavailable, get_graph_client, get_graph_namespace
from core.llm.openai_embedding_client import EmbeddingError, OpenAIEmbeddingClient

router = APIRouter(prefix="/v1/retrieval", tags=["retrieval"])


def get_embedding_client() -> OpenAIEmbeddingClient:
    from openai import OpenAI

    settings = Settings()
    return OpenAIEmbeddingClient(client=OpenAI(api_key=settings.openai_api_key))


@router.post("/ask", response_model=AskResponse)
def ask(
    body: AskRequest,
    session: Session = Depends(get_session),
    graph_client: GraphClient = Depends(get_graph_client),
    ns: str = Depends(get_graph_namespace),
    embedder: OpenAIEmbeddingClient = Depends(get_embedding_client),
) -> AskResponse:
    service = KnowledgeService(session=session, graph=GraphReader(graph_client, ns), embedder=embedder)
    try:
        result = service.ask(body.question)
    except GraphUnavailable as exc:
        raise HTTPException(status_code=503, detail="knowledge graph unavailable") from exc
    except EmbeddingsNotBuilt as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except EmbeddingError as exc:
        raise HTTPException(status_code=502, detail="embedding call failed") from exc
    return AskResponse(route=result.route.value, rule=result.rule, evidence=result.evidence)
```

`backend/api/v1/graph/__init__.py` (empty), `backend/api/v1/graph/response.py`:

```python
from pydantic import BaseModel


class RebuildResponse(BaseModel):
    namespace: str
    fingerprint: str
    node_counts: dict[str, int]
    edge_counts: dict[str, int]
    community_count: int
    largest_community_size: int
```

`backend/api/v1/graph/route.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.v1.graph.response import RebuildResponse
from app.graph.service import rebuild_graph, run_communities
from core.db.session import get_session
from core.graph.client import GraphClient, GraphUnavailable, get_graph_client, get_graph_namespace

router = APIRouter(prefix="/v1/graph", tags=["graph"])


@router.post("/rebuild", response_model=RebuildResponse)
def rebuild(
    session: Session = Depends(get_session),
    graph_client: GraphClient = Depends(get_graph_client),
    ns: str = Depends(get_graph_namespace),
) -> RebuildResponse:
    try:
        summary = rebuild_graph(session, graph_client, ns)
        communities = run_communities(graph_client, ns)
    except GraphUnavailable as exc:
        raise HTTPException(status_code=503, detail="knowledge graph unavailable") from exc
    return RebuildResponse(
        namespace=summary.namespace, fingerprint=summary.fingerprint, node_counts=summary.node_counts,
        edge_counts=summary.edge_counts, community_count=communities.community_count,
        largest_community_size=communities.largest_community_size,
    )
```

In `backend/main.py` add the imports `from api.v1.graph.route import router as graph_router`, `from api.v1.retrieval.route import router as retrieval_router` and `app.include_router(graph_router)`, `app.include_router(retrieval_router)`.

- [ ] **Step 9: Run to verify pass**

Run: `pytest tests/api/v1 tests/app/retrieval tests/app/reference_data -v`, then the full suite `pytest -q`. Expected: all PASS.

- [ ] **Step 10: Commit**

```bash
git add backend/app/reference_data/search.py backend/app/estimate/tools.py backend/app/retrieval/router.py backend/app/retrieval/service.py backend/api/v1/retrieval/__init__.py backend/api/v1/retrieval/request.py backend/api/v1/retrieval/response.py backend/api/v1/retrieval/route.py backend/api/v1/graph/__init__.py backend/api/v1/graph/response.py backend/api/v1/graph/route.py backend/main.py backend/tests/app/reference_data/test_search.py backend/tests/app/retrieval/test_router.py backend/tests/app/retrieval/test_service.py backend/tests/api/v1/test_retrieval_route.py backend/tests/api/v1/test_graph_route.py
git commit -m "feat: add the hybrid retrieval router, knowledge service, and retrieval and rebuild endpoints"
```

---

### Task 11: Graph-backed agent tools, `ToolContext`, the system prompt, and the new `run_estimate` signature

**Files:**
- Modify: `backend/app/estimate/tools.py`, `backend/app/estimate/prompts.py`, `backend/app/estimate/service.py`, `backend/api/v1/estimate/route.py`, `backend/tests/graph_support.py`, `backend/tests/app/estimate/test_tools.py`, `backend/tests/app/estimate/test_prompts.py`, `backend/tests/app/estimate/test_graph.py`, `backend/tests/app/estimate/test_service.py`, `backend/tests/api/v1/test_estimate_route.py`, `backend/tests/test_phase3_acceptance.py`
- Create: `backend/tests/app/estimate/test_graph_tools.py`

**Interfaces:**
- Consumes: Task 5 `GraphReader`, Task 10 `KnowledgeService`, Task 9 `EmbeddingsNotBuilt`, `EmbeddingError`.
- Produces:
  - `app.estimate.tools.ToolContext(session, as_of, graph, knowledge, request_customer_id, request_sku_ids)`, all required, no defaults (`request_customer_id: str | None`, `request_sku_ids: tuple[str, ...]`).
  - Tool handlers (each `(ctx, **string_args) -> dict`): `get_related_parts(ctx, *, sku_id)` returning `{"sku_id", "discontinued", "replacement_chain": [sku_id], "replacement": entry | None, "live_sku_id": str | None, "required_parts": [entry], "evidence_path": [str]}` where `entry = {"sku_id", "name", "discontinued", "in_stock"}` and `required_parts` are those of the live SKU; `check_contract_coverage(ctx, *, customer_id, sku_id)` returning `{"customer_id", "sku_id", "sku_category", "contracts": [{"contract_id", "discount_pct", "covered", "active_on_as_of", "discount_applies", "reason", "evidence_path"}]}`; `ask_knowledge(ctx, *, question)` returning `{"route", "rule", "evidence"}`. Any graph, embedding or vector-index failure returns `{"error": str}` and never raises.
  - `run_estimate(session, quote_request_id, as_of, llm_client, graph, embedder)`; a `GraphReader` and an `Embedder` are now required.
  - `TOOL_SPECS` names: `lookup_customer, search_price_book, check_stock, get_related_parts, check_contract_coverage, predict_price, ask_knowledge, submit_draft`.
  - `tests.graph_support`: `make_ctx(session, graph, *, as_of=AS_OF, customer_id=None, sku_ids=(), embedder=None) -> ToolContext`, `FailingGraphReader` (every method raises `GraphUnavailable`), `TogglableReader(inner)` (delegates until `.down = True`, then raises `GraphUnavailable`).

- [ ] **Step 1: Add the test doubles**

Append to `backend/tests/graph_support.py` (add `from app.estimate.tools import ToolContext`, `from app.retrieval.service import KnowledgeService`, `from tests.app.estimate.seed import AS_OF`):

```python
def make_ctx(session, graph, *, as_of=AS_OF, customer_id=None, sku_ids=(), embedder=None) -> ToolContext:
    knowledge = KnowledgeService(session=session, graph=graph, embedder=embedder or FakeEmbedder())
    return ToolContext(
        session=session, as_of=as_of, graph=graph, knowledge=knowledge, request_customer_id=customer_id,
        request_sku_ids=tuple(sku_ids),
    )


class FailingGraphReader:
    """A reader whose graph is down."""

    client = None
    ns = "down"

    def sku_chain(self, sku_id):
        raise GraphUnavailable("Neo4j is unavailable: test double")

    def required_parts(self, sku_id):
        raise GraphUnavailable("Neo4j is unavailable: test double")

    def contract_coverage(self, customer_id, sku_id, as_of):
        raise GraphUnavailable("Neo4j is unavailable: test double")

    def stored_fingerprint(self):
        raise GraphUnavailable("Neo4j is unavailable: test double")


class TogglableReader:
    """Delegates to a real reader until `down` is set, then behaves like a graph outage. Lets a test take the graph
    away in the middle of an agent run."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.down = False

    @property
    def client(self):
        return self._inner.client

    @property
    def ns(self):
        return self._inner.ns

    def _check(self) -> None:
        if self.down:
            raise GraphUnavailable("Neo4j went away mid-run: test double")

    def sku_chain(self, sku_id):
        self._check()
        return self._inner.sku_chain(sku_id)

    def required_parts(self, sku_id):
        self._check()
        return self._inner.required_parts(sku_id)

    def contract_coverage(self, customer_id, sku_id, as_of):
        self._check()
        return self._inner.contract_coverage(customer_id, sku_id, as_of)

    def stored_fingerprint(self):
        self._check()
        return self._inner.stored_fingerprint()
```

(`make_ctx` cannot be imported until `ToolContext` has the new fields in step 5; do steps 2 to 7 before running the suite.)

- [ ] **Step 2: Write the failing graph tool tests**

Create `backend/tests/app/estimate/test_graph_tools.py`:

```python
from datetime import date

import pytest
from sqlalchemy import delete

from app.estimate.tools import (
    TOOL_SPECS, ToolContext, ask_knowledge, check_contract_coverage, get_related_parts, handle_tool,
)
from app.reference_data.models import Sku
from app.reference_data.repository import upsert_sku
from app.retrieval.models import SkuEmbedding
from tests.app.estimate.seed import AS_OF, seed_chain_world, seed_world
from tests.graph_support import FailingGraphReader, UnusedGraph, make_ctx


def _ctx(db_session, make_reader, **kwargs):
    seed_world(db_session)
    seed_chain_world(db_session)
    return make_ctx(db_session, make_reader(), **kwargs)


A1 = {"sku_id": "SKU-E-A1", "name": "Zorpwidget Alpha 9000", "discontinued": False, "in_stock": True}


def test_a_live_sku_is_its_own_live_sku_and_lists_its_required_parts(db_session, make_reader):
    result = get_related_parts(_ctx(db_session, make_reader), sku_id="SKU-E-B1")

    assert result == {
        "sku_id": "SKU-E-B1", "discontinued": False, "replacement_chain": [], "replacement": None,
        "live_sku_id": "SKU-E-B1", "required_parts": [A1], "evidence_path": ["SKU-E-B1"],
    }


def test_a_discontinued_sku_returns_its_live_replacement(db_session, make_reader):
    result = get_related_parts(_ctx(db_session, make_reader), sku_id="SKU-E-OLD")

    assert result["discontinued"] is True
    assert result["replacement"] == A1
    assert result["replacement_chain"] == ["SKU-E-A1"]
    assert result["live_sku_id"] == "SKU-E-A1"
    assert result["required_parts"] == []
    assert result["evidence_path"] == ["SKU-E-OLD", "REPLACED_BY", "SKU-E-A1"]


def test_a_two_hop_chain_reports_every_hop(db_session, make_reader):
    result = get_related_parts(_ctx(db_session, make_reader), sku_id="SKU-E-OLD2")

    assert result["replacement_chain"] == ["SKU-E-OLD", "SKU-E-A1"]
    assert result["live_sku_id"] == "SKU-E-A1"


def test_required_parts_come_from_the_live_end_of_the_chain(db_session, make_reader):
    seed_world(db_session)
    upsert_sku(db_session, sku_id="SKU-L-OLDB", name="Old B", category="Cat-E-B", list_price=1.0,
               discontinued=True, replaced_by=None, in_stock=False)
    db_session.flush()
    db_session.get(Sku, "SKU-L-OLDB").replaced_by = "SKU-E-B1"
    db_session.flush()

    result = get_related_parts(make_ctx(db_session, make_reader()), sku_id="SKU-L-OLDB")

    assert result["live_sku_id"] == "SKU-E-B1"
    assert [p["sku_id"] for p in result["required_parts"]] == ["SKU-E-A1"]


def test_a_discontinued_sku_with_no_replacement_has_no_live_sku(db_session, make_reader):
    result = get_related_parts(_ctx(db_session, make_reader), sku_id="SKU-E-DEAD")

    assert result["live_sku_id"] is None and result["replacement"] is None
    assert result["required_parts"] == [] and result["discontinued"] is True


def test_a_replacement_cycle_returns_no_live_sku(db_session, make_reader):
    result = get_related_parts(_ctx(db_session, make_reader), sku_id="SKU-E-CYC1")

    assert result["live_sku_id"] is None


def test_a_live_sku_requiring_a_discontinued_part_reports_it_as_discontinued(db_session, make_reader):
    result = get_related_parts(_ctx(db_session, make_reader), sku_id="SKU-E-NEEDOLD")

    assert [(p["sku_id"], p["discontinued"]) for p in result["required_parts"]] == [("SKU-E-OLD", True)]


def test_related_parts_for_an_unknown_sku_is_an_error(db_session, make_reader):
    assert get_related_parts(_ctx(db_session, make_reader), sku_id="SKU-NOPE") == {"error": "unknown SKU SKU-NOPE"}


def test_related_parts_with_the_graph_down_returns_an_error_and_does_not_raise(db_session):
    seed_world(db_session)

    result = get_related_parts(make_ctx(db_session, FailingGraphReader()), sku_id="SKU-E-A1")

    assert "knowledge graph unavailable" in result["error"]


def test_coverage_says_the_discount_applies_for_a_covered_active_contract(db_session, make_reader):
    result = check_contract_coverage(_ctx(db_session, make_reader), customer_id="CUST-E1", sku_id="SKU-E-A1")

    assert result["sku_category"] == "Cat-E-A"
    [contract] = result["contracts"]
    assert contract["contract_id"] == "CTR-E1" and contract["discount_pct"] == 10.0
    assert contract["covered"] is True and contract["active_on_as_of"] is True
    assert contract["discount_applies"] is True
    assert "is covered by contract CTR-E1" in contract["reason"] and "active" in contract["reason"]
    assert contract["evidence_path"] == ["CUST-E1", "HOLDS", "CTR-E1", "COVERS", "Cat-E-A", "PRICED_IN", "SKU-E-A1"]


def test_coverage_says_no_discount_for_an_uncovered_category(db_session, make_reader):
    result = check_contract_coverage(_ctx(db_session, make_reader), customer_id="CUST-E1", sku_id="SKU-E-B1")

    [contract] = result["contracts"]
    assert contract["covered"] is False and contract["discount_applies"] is False
    assert "category Cat-E-B is not covered by contract CTR-E1" in contract["reason"]
    assert "Cat-E-A" in contract["reason"]
    assert contract["evidence_path"] == ["CUST-E1", "HOLDS", "CTR-E1"]


def test_coverage_says_no_discount_when_the_contract_is_not_active(db_session, make_reader):
    ctx = _ctx(db_session, make_reader, as_of=date(2026, 1, 1))

    [contract] = check_contract_coverage(ctx, customer_id="CUST-E1", sku_id="SKU-E-A1")["contracts"]

    assert contract["covered"] is True and contract["active_on_as_of"] is False
    assert contract["discount_applies"] is False
    assert "not active on 2026-01-01" in contract["reason"]


def test_coverage_for_a_customer_without_contracts_is_empty(db_session, make_reader):
    result = check_contract_coverage(_ctx(db_session, make_reader), customer_id="CUST-E2", sku_id="SKU-E-A1")

    assert result["contracts"] == [] and result["sku_category"] is None


def test_coverage_for_an_unknown_sku_is_an_error(db_session, make_reader):
    result = check_contract_coverage(_ctx(db_session, make_reader), customer_id="CUST-E1", sku_id="SKU-NOPE")

    assert result == {"error": "unknown SKU SKU-NOPE"}


def test_coverage_with_the_graph_down_returns_an_error(db_session):
    seed_world(db_session)

    result = check_contract_coverage(make_ctx(db_session, FailingGraphReader()), customer_id="CUST-E1", sku_id="SKU-E-A1")

    assert "knowledge graph unavailable" in result["error"]


def test_ask_knowledge_returns_the_route_rule_and_evidence(db_session, make_reader):
    result = ask_knowledge(_ctx(db_session, make_reader), question="what does SKU-E-B1 require")

    assert (result["route"], result["rule"]) == ("graph_local", "id_with_relationship_phrasing")
    assert "SKU-E-A1" in {n["id"] for n in result["evidence"]["nodes"]}


def test_ask_knowledge_reports_a_missing_vector_index_as_an_error(db_session, make_reader):
    ctx = _ctx(db_session, make_reader)
    db_session.execute(delete(SkuEmbedding))
    db_session.flush()

    result = ask_knowledge(ctx, question="something like a zorpwidget")

    assert "embed_skus" in result["error"]


def test_ask_knowledge_with_the_graph_down_returns_an_error(db_session):
    seed_world(db_session)

    result = ask_knowledge(make_ctx(db_session, FailingGraphReader()), question="what does SKU-E-B1 require")

    assert "unavailable" in result["error"]


def test_handle_tool_dispatches_the_new_tools_and_rejects_non_string_arguments(db_session, make_reader):
    ctx = _ctx(db_session, make_reader)

    assert handle_tool(ctx, "get_related_parts", {"sku_id": "SKU-E-OLD"})["live_sku_id"] == "SKU-E-A1"
    assert handle_tool(ctx, "check_contract_coverage", {"customer_id": "CUST-E1", "sku_id": "SKU-E-A1"})["contracts"]
    assert handle_tool(ctx, "check_contract_coverage", {"customer_id": 1, "sku_id": "SKU-E-A1"}) == {
        "error": "bad arguments for check_contract_coverage: customer_id must be a string",
    }
    assert "bad arguments" in handle_tool(ctx, "ask_knowledge", {})["error"]


def test_tool_context_requires_every_request_anchor():
    """The customer and SKU anchors have no default, so a caller cannot forget them (a Phase 3 gap)."""
    with pytest.raises(TypeError):
        ToolContext(session=None, as_of=AS_OF, graph=UnusedGraph(), knowledge=None)


def test_tool_specs_describe_the_new_tools_with_string_parameters():
    specs = {s["function"]["name"]: s["function"] for s in TOOL_SPECS}

    assert specs["check_contract_coverage"]["parameters"]["required"] == ["customer_id", "sku_id"]
    assert specs["ask_knowledge"]["parameters"]["required"] == ["question"]
    assert "live_sku_id" in specs["get_related_parts"]["description"]
```

- [ ] **Step 3: Update the existing tool and prompt tests**

In `backend/tests/app/estimate/test_tools.py`:
- Replace the import of `ToolContext` and `get_related_parts` and the `_ctx` helper with:

```python
from app.estimate.tools import (
    TOOL_SPECS, check_stock, handle_tool, lookup_customer, predict_price, search_price_book,
)
from tests.graph_support import UnusedGraph, make_ctx
```

```python
def _ctx(session, as_of=AS_OF):
    return make_ctx(session, UnusedGraph(), as_of=as_of)
```

- Delete `test_get_related_parts_returns_replacement_for_discontinued_sku` and `test_get_related_parts_returns_required_parts` (superseded by `test_graph_tools.py`).
- In `test_tool_specs_name_every_handler_plus_submit_draft` set the expected names to `{"lookup_customer", "search_price_book", "check_stock", "get_related_parts", "check_contract_coverage", "predict_price", "ask_knowledge", "submit_draft"}`.

In `backend/tests/app/estimate/test_prompts.py` extend the phrase list in `test_system_prompt_states_the_policy` to `("submit_draft", "get_related_parts", "predict_price", "discount", "flags", "check_contract_coverage", "live_sku_id", "ask_knowledge")`.

- [ ] **Step 4: Run to verify failure**

Run: `pytest tests/app/estimate/test_graph_tools.py tests/app/estimate/test_prompts.py -v`. Expected: FAIL (the new handlers, fields and prompt phrases do not exist).

- [ ] **Step 5: Implement `tools.py`**

Replace the contents of `backend/app/estimate/tools.py` with:

```python
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.estimate.pricing import PEER_MIN, predict_price_for_sku
from app.estimate.schemas import EstimateDraft
from app.graph.reader import GraphReader
from app.graph.schemas import ChainNode, ContractCoverage, RequiredPart
from app.reference_data.models import Customer, Sku
from app.reference_data.repository import contracts_for_customer, get_sku, latest_realized_price
from app.reference_data.search import find_customers, find_skus
from app.retrieval.service import KnowledgeService
from app.retrieval.vector import EmbeddingsNotBuilt
from core.graph.client import GraphError
from core.llm.openai_embedding_client import EmbeddingError


@dataclass(frozen=True)
class ToolContext:
    session: Session
    as_of: date
    graph: GraphReader
    knowledge: KnowledgeService
    # The customer intake resolved for the quote request. Guardrails anchor on it because the draft's own
    # customer_id is written by the model and cannot vouch for itself.
    request_customer_id: str | None
    # The SKUs intake resolved from the request lines by code. The graph guardrail anchors on them for the same
    # reason: the draft's own lines are model output, so dropping a requested line must not pass unnoticed.
    request_sku_ids: tuple[str, ...]


def _sku_entry(session: Session, sku: Sku) -> dict:
    return {
        "sku_id": sku.sku_id, "name": sku.name, "category": sku.category, "list_price": sku.list_price,
        "last_realized_price": latest_realized_price(session, sku.sku_id),
        "discontinued": sku.discontinued, "in_stock": sku.in_stock,
    }


def _part_entry(part: ChainNode | RequiredPart) -> dict:
    return {"sku_id": part.sku_id, "name": part.name, "discontinued": part.discontinued, "in_stock": part.in_stock}


def _customer_entry(ctx: ToolContext, customer: Customer) -> dict:
    contracts = contracts_for_customer(ctx.session, customer.customer_id)
    return {
        "customer_id": customer.customer_id, "name": customer.name, "account_tier": customer.account_tier,
        "contracts": [
            {
                "contract_id": c.contract_id, "discount_pct": c.discount_pct,
                "covered_categories": list(c.covered_categories),
                "effective_from": c.effective_from.isoformat(), "effective_to": c.effective_to.isoformat(),
                "active_on_as_of": c.effective_from <= ctx.as_of <= c.effective_to,
            }
            for c in contracts
        ],
    }


def lookup_customer(ctx: ToolContext, *, query: str) -> dict:
    return {"matches": [_customer_entry(ctx, c) for c in find_customers(ctx.session, query)]}


def search_price_book(ctx: ToolContext, *, query: str) -> dict:
    return {"results": [_sku_entry(ctx.session, s) for s in find_skus(ctx.session, query)]}


def check_stock(ctx: ToolContext, *, sku_id: str) -> dict:
    sku = get_sku(ctx.session, sku_id)
    if sku is None:
        return {"error": f"unknown SKU {sku_id}"}
    return {"sku_id": sku.sku_id, "in_stock": sku.in_stock, "discontinued": sku.discontinued}


def get_related_parts(ctx: ToolContext, *, sku_id: str) -> dict:
    try:
        chain = ctx.graph.sku_chain(sku_id)
        if chain is None:
            return {"error": f"unknown SKU {sku_id}"}
        live = chain.live_end
        required = ctx.graph.required_parts(live.sku_id) if live is not None else []
    except GraphError as exc:
        return {"error": f"knowledge graph unavailable: {exc}"}
    return {
        "sku_id": sku_id,
        "discontinued": chain.nodes[0].discontinued,
        "replacement_chain": [node.sku_id for node in chain.nodes[1:]],
        "replacement": _part_entry(live) if live is not None and live.sku_id != sku_id else None,
        "live_sku_id": live.sku_id if live is not None else None,
        "required_parts": [_part_entry(part) for part in required],
        "evidence_path": chain.evidence_path,
    }


def _coverage_reason(coverage: ContractCoverage, as_of: date) -> str:
    category, contract = coverage.sku_category, coverage.contract_id
    if not coverage.covered:
        covered = ", ".join(coverage.covered_categories) or "no categories"
        return f"category {category} is not covered by contract {contract}; it covers {covered}"
    if not coverage.active_on_as_of:
        return f"category {category} is covered by contract {contract} but the contract is not active on {as_of.isoformat()}"
    return f"category {category} is covered by contract {contract} and the contract is active on {as_of.isoformat()}"


def check_contract_coverage(ctx: ToolContext, *, customer_id: str, sku_id: str) -> dict:
    try:
        coverage = ctx.graph.contract_coverage(customer_id, sku_id, ctx.as_of)
    except GraphError as exc:
        return {"error": f"knowledge graph unavailable: {exc}"}
    if coverage and coverage[0].sku_category is None:
        return {"error": f"unknown SKU {sku_id}"}
    return {
        "customer_id": customer_id,
        "sku_id": sku_id,
        "sku_category": coverage[0].sku_category if coverage else None,
        "contracts": [
            {
                "contract_id": c.contract_id, "discount_pct": c.discount_pct, "covered": c.covered,
                "active_on_as_of": c.active_on_as_of, "discount_applies": c.covered and c.active_on_as_of,
                "reason": _coverage_reason(c, ctx.as_of),
                "evidence_path": (
                    [customer_id, "HOLDS", c.contract_id, "COVERS", c.sku_category, "PRICED_IN", sku_id]
                    if c.covered else [customer_id, "HOLDS", c.contract_id]
                ),
            }
            for c in coverage
        ],
    }


def predict_price(ctx: ToolContext, *, sku_id: str) -> dict:
    sku = get_sku(ctx.session, sku_id)
    if sku is None:
        return {"error": f"unknown SKU {sku_id}"}
    if sku.list_price is not None:
        return {"error": f"SKU {sku_id} has a list price; use search_price_book instead of predicting"}
    prediction = predict_price_for_sku(ctx.session, sku)
    if prediction is None:
        return {"error": f"fewer than {PEER_MIN} priced peers in category {sku.category}; cannot predict"}
    return {
        "sku_id": sku_id, "price_source": "predicted", "predicted_price": prediction.price,
        "low": prediction.low, "high": prediction.high, "peer_count": prediction.peer_count,
    }


def ask_knowledge(ctx: ToolContext, *, question: str) -> dict:
    try:
        result = ctx.knowledge.ask(question)
    except (GraphError, EmbeddingsNotBuilt, EmbeddingError) as exc:
        return {"error": str(exc)}
    return {"route": result.route.value, "rule": result.rule, "evidence": result.evidence}


TOOL_HANDLERS: dict[str, Callable[..., dict]] = {
    "lookup_customer": lookup_customer,
    "search_price_book": search_price_book,
    "check_stock": check_stock,
    "get_related_parts": get_related_parts,
    "check_contract_coverage": check_contract_coverage,
    "predict_price": predict_price,
    "ask_knowledge": ask_knowledge,
}


def handle_tool(ctx: ToolContext, name: str, arguments: dict) -> dict:
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return {"error": f"unknown tool {name}"}
    try:
        inspect.signature(handler).bind(ctx, **arguments)
    except TypeError as exc:
        return {"error": f"bad arguments for {name}: {exc}"}
    # Every tool parameter is a string. A wrong-typed value would reach a text column in Postgres, which aborts
    # the whole transaction and poisons the session for the rest of the run.
    for arg_name, value in arguments.items():
        if not isinstance(value, str):
            return {"error": f"bad arguments for {name}: {arg_name} must be a string"}
    return handler(ctx, **arguments)


def _function_spec(name: str, description: str, parameters: dict) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}


def _string_params(descriptions: dict[str, str]) -> dict:
    return {
        "type": "object",
        "properties": {name: {"type": "string", "description": text} for name, text in descriptions.items()},
        "required": list(descriptions),
    }


TOOL_SPECS: list[dict] = [
    _function_spec(
        "lookup_customer",
        "Find a customer by id or name. Returns matches with their contracts (discount_pct, covered_categories, "
        "effective dates, and whether the contract is active on the quote date).",
        _string_params({"query": "customer id (CUST-....) or customer name"}),
    ),
    _function_spec(
        "search_price_book",
        "Find SKUs by id or name. Returns list_price (null means unpriced), last realized price, discontinued and "
        "in_stock flags.",
        _string_params({"query": "SKU id (SKU-....) or product name as written in the email"}),
    ),
    _function_spec(
        "check_stock", "Check whether a SKU is in stock and whether it is discontinued.",
        _string_params({"sku_id": "SKU id"}),
    ),
    _function_spec(
        "get_related_parts",
        "Walk the knowledge graph from a SKU. Follows the full replacement chain of a discontinued SKU and returns "
        "live_sku_id (the SKU to quote; null when no live replacement exists), plus the required_parts of that live "
        "SKU. Call it again on any required part that is discontinued.",
        _string_params({"sku_id": "SKU id"}),
    ),
    _function_spec(
        "check_contract_coverage",
        "Ask the knowledge graph whether a customer's contract covers a SKU's pricing category. Returns, per "
        "contract, discount_applies (covered and active on the quote date), the contract's discount_pct, and why.",
        _string_params({"customer_id": "customer id", "sku_id": "SKU id"}),
    ),
    _function_spec(
        "predict_price",
        "Estimate a price for a SKU that has no list price, from same-category peers. The result is a prediction, "
        "not a looked-up price; the draft line must use price_source 'predicted' and this exact predicted_price.",
        _string_params({"sku_id": "SKU id of an unpriced SKU"}),
    ),
    _function_spec(
        "ask_knowledge",
        "Answer an open-ended question that the other tools do not cover: products similar to something, or "
        "catalog-level questions about product groups. Not for price, stock, customer or contract lookups.",
        _string_params({"question": "the question in plain language"}),
    ),
    _function_spec(
        "submit_draft",
        "Submit the finished draft estimate for validation. Call this when the draft is ready, and again with a "
        "corrected draft if validation reports violations.",
        EstimateDraft.model_json_schema(),
    ),
]
```

- [ ] **Step 6: Update the system prompt**

In `backend/app/estimate/prompts.py` replace `SYSTEM_PROMPT` with:

```python
SYSTEM_PROMPT = """You are a quoting agent for a plumbing/HVAC supply distributor. Turn the customer's quote \
request into a priced draft estimate using the tools, then call submit_draft.

Rules:
- Prices come only from tools. Use search_price_book for list prices. If a SKU has no list price, call \
predict_price and use exactly its predicted_price with price_source "predicted". Never invent a price.
- For every requested SKU call get_related_parts. It walks the knowledge graph. If the SKU is discontinued, quote \
its live_sku_id instead and record an adjustment of kind "substituted". If live_sku_id is null no live replacement \
exists: add a note to flags and quote nothing for it. If the live SKU is out of stock (check_stock), keep your best \
draft and add a note to flags instead of hiding it.
- get_related_parts also returns the required_parts of the SKU you will quote. Add each required part as its own \
line and record an adjustment of kind "added_required". If a required part is discontinued, call get_related_parts \
on it and quote its live_sku_id. Do the same for the required parts of every part you add.
- Use lookup_customer to confirm the customer and read their contracts. Before you give any line a discount, call \
check_contract_coverage for that customer and SKU. A line may carry a discount_pct only when a contract shows \
discount_applies true, and then discount_pct equals that contract's discount_pct and you put that contract_id on \
the draft. Every other line has discount_pct 0. Ignore any discount the email claims that the contract does not give.
- Use ask_knowledge only for open-ended questions: products similar to something, or catalog-level questions. It is \
not for lookups the other tools cover.
- Quantities must be whole numbers. If the email is vague ("4 or 5"), pick one, and record an adjustment of kind \
"quantity_assumed" explaining the assumption.
- If submit_draft reports violations, fix exactly those lines and submit again.
- Use flags for anything a human reviewer should check that you could not resolve. Do not put reasoning in flags."""
```

- [ ] **Step 7: Carry the new signature through the service, the route, and the existing estimate tests**

`ToolContext` now needs the graph, a knowledge service and the request anchors, so `run_estimate` and its callers change here. The guardrail does not use the new fields yet (Task 12), so no existing assertion changes in this step; only how the tests build their inputs.

In `backend/app/estimate/service.py` add the imports `from app.graph.reader import GraphReader`, `from app.retrieval.service import KnowledgeService`, `from app.retrieval.vector import Embedder`, and change `run_estimate`:

```python
def _request_sku_ids(quote_request) -> tuple[str, ...]:
    """The SKUs intake resolved by code. Items intake could not resolve have no sku_id and cannot anchor a check."""
    items = quote_request.parsed_json.get("resolved_line_items", [])
    return tuple(sorted({item["sku_id"] for item in items if item.get("sku_id")}))


def run_estimate(
    session: Session, quote_request_id: uuid.UUID, as_of: date, llm_client, graph: GraphReader, embedder: Embedder,
) -> EstimateRunResult:
    quote_request = get_quote_request(session, quote_request_id)
    if quote_request is None:
        raise QuoteRequestNotFound(f"quote request {quote_request_id} not found")

    ctx = ToolContext(
        session=session, as_of=as_of, graph=graph,
        knowledge=KnowledgeService(session=session, graph=graph, embedder=embedder),
        request_customer_id=quote_request.customer_id, request_sku_ids=_request_sku_ids(quote_request),
    )
    state = run_agent(llm_client, ctx, build_request_message(quote_request, as_of))
    # ... the rest of the function is unchanged
```

In `backend/api/v1/estimate/route.py` add the imports `from api.v1.retrieval.route import get_embedding_client`, `from app.graph.reader import GraphReader`, `from app.graph.service import sync_best_effort, sync_quote`, `from core.graph.client import GraphClient, get_graph_client, get_graph_namespace`, `from core.llm.openai_embedding_client import OpenAIEmbeddingClient`, and update `create_estimate`:

```python
@router.post("", response_model=EstimateResponse)
def create_estimate(
    body: EstimateRequest,
    session: Session = Depends(get_session),
    llm_client: OpenAIAgentClient = Depends(get_agent_client),
    graph_client: GraphClient = Depends(get_graph_client),
    ns: str = Depends(get_graph_namespace),
    embedder: OpenAIEmbeddingClient = Depends(get_embedding_client),
) -> EstimateResponse:
    try:
        run = run_estimate(
            session, body.quote_request_id, body.as_of or DATASET_AS_OF, llm_client,
            GraphReader(graph_client, ns), embedder,
        )
    except QuoteRequestNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AgentError as exc:
        raise HTTPException(status_code=502, detail="agent failed to produce an estimate") from exc

    session.commit()
    sync_best_effort("estimate draft", sync_quote, session, graph_client, ns, run.row.id)
    # ... the return statement is unchanged
```

In `backend/tests/app/estimate/test_graph.py` replace the `_run` helper with a fixture and convert the tests to use it. Imports: drop `ToolContext`; add `import pytest`, `from tests.graph_support import make_ctx`, and keep from `tests.app.estimate.seed` only `seed_chain_world, seed_world` (`AS_OF` is no longer used here):

```python
@pytest.fixture
def run(db_session, make_reader):
    def _run(turns, *, sku_ids=("SKU-E-A1",), wrap_reader=None):
        seed_world(db_session)
        seed_chain_world(db_session)
        reader = make_reader()
        if wrap_reader is not None:
            reader = wrap_reader(reader)
        llm = ScriptedLLM(turns)
        ctx = make_ctx(db_session, reader, customer_id="CUST-E1", sku_ids=sku_ids)
        state = run_agent(llm, ctx, "please quote 1 SKU-E-A1")
        return state, llm

    return _run
```

Mechanical rule for every existing test in the file: the parameter `db_session` becomes `run`, and `_run(db_session, X)` becomes `run(X)` (for example `state, llm = run([submit_turn(...)])`). Delete the old `_run`. No test in the file uses `db_session` for anything else.

In `backend/tests/app/estimate/test_service.py` add `from tests.graph_support import FakeEmbedder, UnusedGraph` and this helper:

```python
def _run(db_session, make_reader, request_id, llm):
    return run_estimate(db_session, request_id, AS_OF, llm, make_reader(), FakeEmbedder())
```

Every test that calls `run_estimate(db_session, request.id, AS_OF, llm)` gains the `make_reader` parameter and calls `_run(db_session, make_reader, request.id, llm)` after `seed_world` and `_quote_request`. `test_run_estimate_rejects_unknown_quote_request` calls `run_estimate(db_session, uuid.uuid4(), AS_OF, ScriptedLLM([]), UnusedGraph(), FakeEmbedder())` directly. `test_run_estimate_propagates_agent_error_and_saves_nothing` uses `_run` with `FailingLLM()`.

In `backend/tests/test_phase3_acceptance.py` add `from tests.graph_support import FakeEmbedder, make_ctx`. Every test that runs the agent or calls a tool also takes `make_reader` and builds `graph = make_reader()` right after `_load_world(db_session)`. Calls become `run_estimate(db_session, request.id, DATASET_AS_OF, llm, graph, FakeEmbedder())`, and `ToolContext(session=db_session, as_of=DATASET_AS_OF)` becomes `make_ctx(db_session, graph, as_of=DATASET_AS_OF)`. Replace the `ToolContext, get_related_parts` import with `from app.estimate.tools import get_related_parts`. No assertion changes.

Add two route tests to `backend/tests/api/v1/test_estimate_route.py` (add `from core.graph.client import get_graph_client` and `from tests.graph_support import FailingGraphClient, graph_node`):

```python
def test_estimate_endpoint_syncs_the_quote_into_the_graph(db_session, graph_client, graph_ns, make_reader):
    seed_world(db_session)
    make_reader()
    row = _request_row(db_session)
    draft = {"customer_id": "CUST-E1", "contract_id": "CTR-E1", "lines": [
        {"sku_id": "SKU-E-A1", "quantity": 2, "unit_price": 100.0, "price_source": "list", "discount_pct": 10.0}]}

    response = _post(db_session, ScriptedLLM([submit_turn(draft)]), {"quote_request_id": str(row.id)})

    assert response.status_code == 200
    assert graph_node(graph_client, graph_ns, response.json()["estimate_id"])["labels"] == ["Quote"]


def test_estimate_endpoint_still_answers_when_the_graph_sync_fails(db_session, make_reader):
    seed_world(db_session)
    make_reader()
    row = _request_row(db_session)
    draft = {"customer_id": "CUST-E1", "contract_id": "CTR-E1", "lines": [
        {"sku_id": "SKU-E-A1", "quantity": 1, "unit_price": 100.0, "price_source": "list", "discount_pct": 0.0}]}
    app.dependency_overrides[get_graph_client] = lambda: FailingGraphClient()
    try:
        response = _post(db_session, ScriptedLLM([submit_turn(draft)]), {"quote_request_id": str(row.id)})
    finally:
        app.dependency_overrides.pop(get_graph_client, None)

    assert response.status_code == 200
```

(`_post` clears every override in its own `finally`, so the failing client is set before calling it and cleared by it; the extra `pop` is a harmless safety.)

- [ ] **Step 8: Run to verify pass**

Run the full suite `pytest -q`. Expected: all PASS. Also confirm no leftover graph data: after the run, a one-off `graph_client.read("MATCH (n) WHERE n.ns STARTS WITH 'test-' RETURN count(n) AS c")` returns 0.

- [ ] **Step 9: Commit**

```bash
git add backend/app/estimate/tools.py backend/app/estimate/prompts.py backend/app/estimate/service.py backend/api/v1/estimate/route.py backend/tests/graph_support.py backend/tests/app/estimate/test_graph_tools.py backend/tests/app/estimate/test_tools.py backend/tests/app/estimate/test_prompts.py backend/tests/app/estimate/test_graph.py backend/tests/app/estimate/test_service.py backend/tests/api/v1/test_estimate_route.py backend/tests/test_phase3_acceptance.py
git commit -m "feat: give the agent graph-backed related-parts, contract coverage, and knowledge tools"
```

---

### Task 12: The `graph_integrity` guardrail, the freshness check, and fail-closed agent wiring

**Files:**
- Modify: `backend/app/estimate/guardrails.py`, `backend/app/estimate/graph.py`, `backend/tests/app/estimate/test_graph.py`, `backend/tests/app/estimate/test_service.py`, `backend/tests/api/v1/test_estimate_route.py`, `backend/tests/test_phase3_acceptance.py`
- Create: `backend/tests/app/estimate/test_graph_integrity.py`

**Interfaces:**
- Consumes: Task 5 `GraphReader`, Task 4 `reference_fingerprint`, Task 11 `ToolContext`, `make_ctx`, `FailingGraphReader`, `TogglableReader`.
- Produces:
  - `app.estimate.guardrails.GraphCheck(violations: list[Violation], unreplaceable: list[str])`.
  - `check_graph_integrity(reader, draft, request_sku_ids) -> GraphCheck`. It raises `GraphError` when the graph is unreachable; the caller decides what that means. Violations carry `guardrail="graph_integrity"`.
  - `graph_is_current(session, reader) -> bool`: the stored fingerprint equals the one recomputed from Postgres (False when the graph was never built). Raises `GraphError` when unreachable.
  - `run_agent` now returns a `needs_review` state without calling the model when the graph is unreachable or stale, and the guardrail node ends the run `needs_review` immediately (no retry) for an unreplaceable SKU or a graph that goes away mid-run.

- [ ] **Step 1: Write the failing guardrail tests**

Create `backend/tests/app/estimate/test_graph_integrity.py`:

```python
import pytest

from app.estimate.guardrails import check_graph_integrity, graph_is_current
from app.estimate.schemas import DraftLine, EstimateDraft
from app.reference_data.models import Sku
from app.reference_data.repository import upsert_requirement, upsert_sku
from core.graph.client import GraphUnavailable
from tests.app.estimate.seed import seed_chain_world, seed_world
from tests.graph_support import FailingGraphReader


def _draft(*sku_ids):
    return EstimateDraft(
        customer_id="CUST-E1", contract_id=None,
        lines=[DraftLine(sku_id=s, quantity=1, unit_price=1.0, price_source="list") for s in sku_ids],
    )


def _reader(db_session, make_reader):
    seed_world(db_session)
    seed_chain_world(db_session)
    return make_reader()


def _messages(check):
    return [v.message for v in check.violations]


def test_a_clean_draft_has_no_violations(db_session, make_reader):
    check = check_graph_integrity(_reader(db_session, make_reader), _draft("SKU-E-A1"), ("SKU-E-A1",))

    assert check.violations == [] and check.unreplaceable == []


def test_a_discontinued_line_is_a_violation_that_names_the_live_replacement(db_session, make_reader):
    check = check_graph_integrity(_reader(db_session, make_reader), _draft("SKU-E-OLD"), ())

    [violation] = check.violations
    assert violation.guardrail == "graph_integrity" and violation.line_index == 0
    assert "SKU-E-OLD is discontinued" in violation.message and "SKU-E-A1" in violation.message


def test_a_request_for_a_discontinued_sku_must_be_covered_by_its_live_replacement(db_session, make_reader):
    reader = _reader(db_session, make_reader)

    swapped = check_graph_integrity(reader, _draft("SKU-E-A1"), ("SKU-E-OLD",))
    left_in = check_graph_integrity(reader, _draft("SKU-E-OLD"), ("SKU-E-OLD",))

    assert swapped.violations == []
    assert any("the request asks for SKU-E-OLD; the draft must quote SKU-E-A1" in m for m in _messages(left_in))
    assert any("SKU-E-OLD is discontinued" in m for m in _messages(left_in))


def test_dropping_a_requested_line_is_caught(db_session, make_reader):
    """(Review Focus) The draft's own lines cannot vouch for what the customer asked; intake's SKUs can."""
    reader = _reader(db_session, make_reader)

    check = check_graph_integrity(reader, _draft("SKU-E-A1"), ("SKU-E-A1", "SKU-E-B1"))

    assert any("the request asks for SKU-E-B1; the draft must quote SKU-E-B1" in m for m in _messages(check))


def test_swapping_to_a_mid_chain_sku_that_is_still_discontinued_is_caught(db_session, make_reader):
    """(Review Focus) OLD2 is replaced by OLD, which is itself replaced by A1; quoting OLD is not enough."""
    check = check_graph_integrity(_reader(db_session, make_reader), _draft("SKU-E-OLD"), ("SKU-E-OLD2",))

    messages = _messages(check)
    assert any("SKU-E-OLD is discontinued" in m and "SKU-E-A1" in m for m in messages)
    assert any("the request asks for SKU-E-OLD2; the draft must quote SKU-E-A1" in m for m in messages)


def test_a_missing_required_part_is_a_violation_and_adding_it_clears_it(db_session, make_reader):
    reader = _reader(db_session, make_reader)

    missing = check_graph_integrity(reader, _draft("SKU-E-B1"), ())
    added = check_graph_integrity(reader, _draft("SKU-E-B1", "SKU-E-A1"), ())

    assert _messages(missing) == ["SKU-E-B1 requires SKU-E-A1; the draft must include SKU-E-A1"]
    assert missing.violations[0].line_index is None
    assert added.violations == []


def test_required_parts_are_enforced_transitively(db_session, make_reader):
    seed_world(db_session)
    for n in (1, 2, 3):
        upsert_sku(db_session, sku_id=f"SKU-L-T{n}", name=f"t{n}", category="Cat-L", list_price=1.0,
                   discontinued=False, replaced_by=None, in_stock=True)
    db_session.flush()
    upsert_requirement(db_session, sku_id="SKU-L-T1", required_sku_id="SKU-L-T2")
    upsert_requirement(db_session, sku_id="SKU-L-T2", required_sku_id="SKU-L-T3")
    db_session.flush()
    reader = make_reader()

    only_first = check_graph_integrity(reader, _draft("SKU-L-T1"), ())
    first_two = check_graph_integrity(reader, _draft("SKU-L-T1", "SKU-L-T2"), ())
    all_three = check_graph_integrity(reader, _draft("SKU-L-T1", "SKU-L-T2", "SKU-L-T3"), ())

    assert _messages(only_first) == ["SKU-L-T1 requires SKU-L-T2; the draft must include SKU-L-T2"]
    assert _messages(first_two) == ["SKU-L-T2 requires SKU-L-T3; the draft must include SKU-L-T3"]
    assert all_three.violations == []


def test_a_required_part_that_is_discontinued_must_be_quoted_as_its_live_replacement(db_session, make_reader):
    reader = _reader(db_session, make_reader)

    alone = check_graph_integrity(reader, _draft("SKU-E-NEEDOLD"), ())
    swapped = check_graph_integrity(reader, _draft("SKU-E-NEEDOLD", "SKU-E-A1"), ())
    left_in = check_graph_integrity(reader, _draft("SKU-E-NEEDOLD", "SKU-E-OLD"), ())

    assert _messages(alone) == ["SKU-E-NEEDOLD requires SKU-E-OLD; the draft must include SKU-E-A1"]
    assert swapped.violations == []
    assert any("SKU-E-OLD is discontinued" in m for m in _messages(left_in))
    assert any("the draft must include SKU-E-A1" in m for m in _messages(left_in))


def test_a_sku_with_no_live_replacement_is_unreplaceable_not_a_violation(db_session, make_reader):
    reader = _reader(db_session, make_reader)

    in_draft = check_graph_integrity(reader, _draft("SKU-E-DEAD"), ())
    in_request = check_graph_integrity(reader, _draft("SKU-E-A1"), ("SKU-E-DEAD",))

    assert in_draft.unreplaceable == ["SKU-E-DEAD"] and in_draft.violations == []
    assert in_request.unreplaceable == ["SKU-E-DEAD"]


def test_a_replacement_cycle_or_an_overlong_chain_is_unreplaceable(db_session, make_reader):
    """(Review Focus) Neither may loop or be treated as resolved."""
    reader = _reader(db_session, make_reader)

    cycle = check_graph_integrity(reader, _draft("SKU-E-A1"), ("SKU-E-CYC1",))
    deep = check_graph_integrity(reader, _draft("SKU-E-A1"), ("SKU-E-D0",))

    assert cycle.unreplaceable == ["SKU-E-CYC1"]
    assert deep.unreplaceable == ["SKU-E-D0"]


def test_a_required_part_with_no_live_replacement_is_unreplaceable(db_session, make_reader):
    seed_world(db_session)
    seed_chain_world(db_session)
    upsert_sku(db_session, sku_id="SKU-L-NEEDDEAD", name="needs dead", category="Cat-L", list_price=1.0,
               discontinued=False, replaced_by=None, in_stock=True)
    db_session.flush()
    upsert_requirement(db_session, sku_id="SKU-L-NEEDDEAD", required_sku_id="SKU-E-DEAD")
    db_session.flush()

    check = check_graph_integrity(make_reader(), _draft("SKU-L-NEEDDEAD"), ())

    assert check.unreplaceable == ["SKU-E-DEAD"]


def test_unreplaceable_skus_are_listed_once(db_session, make_reader):
    check = check_graph_integrity(
        _reader(db_session, make_reader), _draft("SKU-E-DEAD", "SKU-E-DEAD"), ("SKU-E-DEAD", "SKU-E-DEAD"),
    )

    assert check.unreplaceable == ["SKU-E-DEAD"]


def test_unknown_skus_and_lines_without_a_sku_are_left_to_the_other_guardrails(db_session, make_reader):
    reader = _reader(db_session, make_reader)
    draft = EstimateDraft(customer_id="CUST-E1", lines=[
        DraftLine(sku_id="SKU-NOPE", quantity=1, unit_price=1.0, price_source="list"),
        DraftLine(sku_id=None, quantity=1, unit_price=1.0, price_source="list"),
    ])

    check = check_graph_integrity(reader, draft, ("SKU-ALSO-NOPE",))

    assert check.violations == [] and check.unreplaceable == []


def test_an_unresolved_intake_item_cannot_be_anchored(db_session, make_reader):
    """Known gap, pinned so it is a decision and not an accident: intake items with no sku_id never reach
    request_sku_ids, so the graph cannot say the draft dropped them."""
    check = check_graph_integrity(_reader(db_session, make_reader), _draft("SKU-E-A1"), ())

    assert check.violations == []


def test_an_unreachable_graph_raises_instead_of_passing():
    with pytest.raises(GraphUnavailable):
        check_graph_integrity(FailingGraphReader(), _draft("SKU-E-A1"), ("SKU-E-A1",))


def test_the_graph_is_current_right_after_a_build(db_session, make_reader):
    reader = _reader(db_session, make_reader)

    assert graph_is_current(db_session, reader) is True


def test_the_graph_is_stale_once_postgres_moves_on(db_session, make_reader):
    """(Review Focus) A SKU discontinued after the build must not be approved by an old graph."""
    reader = _reader(db_session, make_reader)

    db_session.get(Sku, "SKU-E-A1").discontinued = True
    db_session.flush()

    assert graph_is_current(db_session, reader) is False


def test_a_graph_that_was_never_built_is_not_current(db_session, graph_client, graph_ns):
    from app.graph.reader import GraphReader

    seed_world(db_session)

    assert graph_is_current(db_session, GraphReader(graph_client, graph_ns)) is False


def test_freshness_check_propagates_an_outage(db_session):
    seed_world(db_session)

    with pytest.raises(GraphUnavailable):
        graph_is_current(db_session, FailingGraphReader())
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/app/estimate/test_graph_integrity.py -v`. Expected: collection error (`check_graph_integrity` missing).

- [ ] **Step 3: Implement the guardrail**

In `backend/app/estimate/guardrails.py` add the imports `from dataclasses import dataclass`, `from app.graph.reader import GraphReader`, and `reference_fingerprint` to the `app.reference_data.repository` import, then append:

```python
@dataclass(frozen=True)
class GraphCheck:
    violations: list[Violation]
    # SKUs whose replacement chain never reaches a live SKU. A retry cannot fix these, so the run ends for review.
    unreplaceable: list[str]


def graph_is_current(session: Session, reader: GraphReader) -> bool:
    """The graph stores the fingerprint of the reference data it was built from. If Postgres has moved on, the
    graph is stale and must not approve a draft."""
    stored = reader.stored_fingerprint()
    return stored is not None and stored == reference_fingerprint(session)


def check_graph_integrity(reader: GraphReader, draft: EstimateDraft, request_sku_ids: tuple[str, ...]) -> GraphCheck:
    """Discontinued lines, requested SKUs the draft dropped, and missing required parts, all read from the graph.
    Raises GraphError when the graph is unreachable; the caller must treat that as a failure, never as a pass."""
    violations: list[Violation] = []
    unreplaceable: list[str] = []
    present = {line.sku_id for line in draft.lines if line.sku_id is not None}

    def flag_unreplaceable(sku_id: str) -> None:
        if sku_id not in unreplaceable:
            unreplaceable.append(sku_id)

    for index, line in enumerate(draft.lines):
        if line.sku_id is None:
            continue
        chain = reader.sku_chain(line.sku_id)
        if chain is None or not chain.nodes[0].discontinued:
            continue
        if chain.live_end is None:
            flag_unreplaceable(line.sku_id)
        else:
            violations.append(Violation(
                guardrail="graph_integrity", line_index=index,
                message=f"SKU {line.sku_id} is discontinued; quote its live replacement {chain.live_end.sku_id} instead",
            ))

    # The request's SKUs were resolved by intake code, not written by the model, so they anchor what must be quoted.
    for requested in dict.fromkeys(request_sku_ids):
        chain = reader.sku_chain(requested)
        if chain is None:
            continue
        if chain.live_end is None:
            flag_unreplaceable(requested)
        elif chain.live_end.sku_id not in present:
            violations.append(Violation(
                guardrail="graph_integrity",
                message=f"the request asks for {requested}; the draft must quote {chain.live_end.sku_id}",
            ))

    # Parts the agent adds are lines too, so the next submission checks their requirements in turn.
    for sku_id in sorted(present):
        chain = reader.sku_chain(sku_id)
        if chain is None or chain.nodes[0].discontinued:
            continue
        for part in reader.required_parts(sku_id):
            part_chain = reader.sku_chain(part.sku_id)
            if part_chain is None:
                continue
            if part_chain.live_end is None:
                flag_unreplaceable(part.sku_id)
            elif part_chain.live_end.sku_id not in present:
                violations.append(Violation(
                    guardrail="graph_integrity",
                    message=f"{sku_id} requires {part.sku_id}; the draft must include {part_chain.live_end.sku_id}",
                ))

    return GraphCheck(violations=violations, unreplaceable=unreplaceable)
```

Run: `pytest tests/app/estimate/test_graph_integrity.py -v`. Expected: PASS.

- [ ] **Step 4: Write the failing agent-level tests**

Append to `backend/tests/app/estimate/test_graph.py` (add imports `from app.reference_data.models import Sku`, `from app.estimate.graph import run_agent`, `from tests.graph_support import FailingGraphReader, TogglableReader, make_ctx`, `from tests.app.estimate.seed import seed_world`):

```python
def test_a_discontinued_sku_left_in_the_draft_is_blocked_then_swapped(run):
    def corrected(messages):
        feedback = messages[-1]["content"]
        assert "SKU-E-OLD is discontinued" in feedback and "SKU-E-A1" in feedback
        return submit_turn(_draft([_line()]), call_id="call-2")

    stale = _draft([_line(sku_id="SKU-E-OLD", unit_price=80.0)])

    state, _ = run([submit_turn(stale), corrected], sku_ids=("SKU-E-OLD",))

    assert state["status"] == "ready"
    assert state["submissions"] == 2
    assert [line.sku_id for line in state["last_draft"].lines] == ["SKU-E-A1"]


def test_a_missing_required_part_is_blocked_then_added(run):
    def corrected(messages):
        assert "SKU-E-B1 requires SKU-E-A1" in messages[-1]["content"]
        return submit_turn(_draft([_line(sku_id="SKU-E-B1", unit_price=50.0), _line()]), call_id="call-2")

    without_part = _draft([_line(sku_id="SKU-E-B1", unit_price=50.0)])

    state, _ = run([submit_turn(without_part), corrected], sku_ids=("SKU-E-B1",))

    assert state["status"] == "ready"
    assert [line.sku_id for line in state["last_draft"].lines] == ["SKU-E-B1", "SKU-E-A1"]


def test_an_unreplaceable_sku_ends_needs_review_at_once_without_retries(run):
    """(Review Focus) No live replacement exists, so a retry cannot help."""
    dead = _draft([_line(sku_id="SKU-E-DEAD", unit_price=5.0)])

    state, llm = run([submit_turn(dead)], sku_ids=("SKU-E-DEAD",))

    assert state["status"] == "needs_review"
    assert state["submissions"] == 1 and state["retries"] == 0
    assert len(llm.calls) == 1
    assert "SKU-E-DEAD" in state["reason"] and "no live replacement" in state["reason"]


def test_a_graph_that_is_down_ends_the_run_before_any_model_call(db_session):
    """(Review Focus) Fail closed, and do not spend model calls on a run that cannot be verified."""
    seed_world(db_session)
    llm = ScriptedLLM([])
    ctx = make_ctx(db_session, FailingGraphReader(), customer_id="CUST-E1", sku_ids=("SKU-E-A1",))

    state = run_agent(llm, ctx, "please quote 1 SKU-E-A1")

    assert state["status"] == "needs_review"
    assert "knowledge graph unavailable" in state["reason"]
    assert llm.calls == [] and state["last_draft"] is None and state["submissions"] == 0


def test_a_stale_graph_ends_the_run_before_any_model_call(db_session, make_reader):
    """(Review Focus) The graph was built before Postgres changed."""
    seed_world(db_session)
    reader = make_reader()
    db_session.get(Sku, "SKU-E-A1").discontinued = True
    db_session.flush()
    llm = ScriptedLLM([])

    state = run_agent(llm, make_ctx(db_session, reader, customer_id="CUST-E1", sku_ids=("SKU-E-A1",)), "quote")

    assert state["status"] == "needs_review"
    assert "out of date" in state["reason"]
    assert llm.calls == [] and state["last_draft"] is None


def test_a_graph_that_goes_down_mid_run_ends_needs_review_and_keeps_the_draft(run):
    """(Review Focus) The freshness check passed, then Neo4j went away before the guardrails ran."""
    holder = {}

    def take_the_graph_away(messages):
        holder["reader"].down = True
        return submit_turn(_draft([_line()]))

    state, _ = run([take_the_graph_away], wrap_reader=lambda reader: holder.setdefault("reader", TogglableReader(reader)))

    assert state["status"] == "needs_review"
    assert "knowledge graph unavailable" in state["reason"]
    assert state["last_draft"] is not None and state["submissions"] == 1
```

- [ ] **Step 5: Run to verify failure**

Run: `pytest tests/app/estimate/test_graph.py -v`. Expected: the six new tests FAIL (the wiring does not exist). Some existing tests now pass only after step 7.

- [ ] **Step 6: Implement the wiring in `graph.py`**

In `backend/app/estimate/graph.py` change the imports (`from app.estimate.guardrails import check_graph_integrity, graph_is_current, run_guardrails`, `from core.graph.client import GraphError`), replace `guardrails_node`, and replace `run_agent`:

```python
    def guardrails_node(state: AgentState) -> dict:
        draft = state["pending_draft"]
        update: dict = {"pending_draft": None, "last_draft": draft, "submissions": state["submissions"] + 1}
        try:
            graph_check = check_graph_integrity(ctx.graph, draft, ctx.request_sku_ids)
        except GraphError as exc:
            return {**update, "violations": [], "status": "needs_review", "reason": f"knowledge graph unavailable: {exc}"}

        violations = run_guardrails(ctx.session, draft, ctx.as_of, ctx.request_customer_id) + graph_check.violations
        update["violations"] = violations
        if graph_check.unreplaceable:
            return {
                **update, "status": "needs_review",
                "reason": "no live replacement exists for " + ", ".join(graph_check.unreplaceable),
            }
        if not violations:
            if draft.flags:
                return {**update, "status": "needs_review", "reason": "draft carries flags for the reviewer"}
            return {**update, "status": "ready"}
        if state["retries"] >= MAX_GUARDRAIL_RETRIES:
            return {
                **update, "status": "needs_review",
                "reason": f"guardrail violations persisted after {MAX_GUARDRAIL_RETRIES} retries",
            }
        messages = state["messages"] + [{"role": "user", "content": _violation_message(violations)}]
        return {**update, "retries": state["retries"] + 1, "messages": messages}
```

```python
def _initial_state(request_message: str) -> AgentState:
    return {
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": request_message}],
        "tool_calls": [], "pending_draft": None, "last_draft": None, "violations": [],
        "retries": 0, "submissions": 0, "steps": 0, "status": None, "reason": None,
    }


def run_agent(llm, ctx: ToolContext, request_message: str) -> AgentState:
    initial = _initial_state(request_message)
    # Verify the graph before spending any model call: a run the guardrails cannot check must not start.
    try:
        current = graph_is_current(ctx.session, ctx.graph)
    except GraphError as exc:
        return {**initial, "status": "needs_review", "reason": f"knowledge graph unavailable: {exc}"}
    if not current:
        return {
            **initial, "status": "needs_review",
            "reason": "knowledge graph is out of date with the reference data; rebuild it",
        }
    return build_graph(llm, ctx).invoke(initial, config={"recursion_limit": RECURSION_LIMIT})
```

- [ ] **Step 7: Fix the existing tests the stricter guardrail now flags**

The guardrail is right and these drafts were incomplete. Change the drafts, never the assertions.

`backend/tests/app/estimate/test_graph.py`:
- `test_planted_bad_discount_is_blocked_then_corrected`: the corrected draft must also carry the required part, so it becomes `_draft([_line(sku_id="SKU-E-B1", unit_price=50.0), _line()])`.
- The predicted-price test (`test_predicted_price_from_the_tool_is_accepted_when_used_verbatim`) quotes only `SKU-E-GAP`, so call `run(..., sku_ids=())`; the same for `test_made_up_predicted_price_is_blocked_and_ends_needs_review`.

`backend/tests/app/estimate/test_service.py`: no change is expected (its drafts quote `SKU-E-A1`, which the request resolves). Add two tests, extending `_quote_request` with a `sku_id="SKU-E-A1"` parameter that fills `resolved_line_items` and `content_fingerprint`:

```python
def test_the_guardrail_is_anchored_on_the_skus_intake_resolved(db_session, make_reader):
    seed_world(db_session)
    seed_chain_world(db_session)
    request = _quote_request(db_session, sku_id="SKU-E-OLD")
    swapped = _good_draft()
    dropped = {**_good_draft(), "lines": [
        {"sku_id": "SKU-E-P1", "quantity": 1, "unit_price": 10.0, "price_source": "list", "discount_pct": 0.0}]}

    ready = _run(db_session, make_reader, request.id, ScriptedLLM([submit_turn(swapped)]))
    blocked = _run(db_session, make_reader, request.id, ScriptedLLM([submit_turn(dropped, call_id=f"c{i}") for i in range(4)]))

    assert ready.result.status == "ready"
    assert blocked.result.status == "needs_review"
    assert any("the request asks for SKU-E-OLD" in v.message for v in blocked.result.violations)
    stored = get_estimate_draft(db_session, blocked.row.id)
    assert any("the request asks for SKU-E-OLD" in v["message"] for v in stored.violations)


def test_a_stale_graph_is_persisted_as_needs_review_without_a_draft(db_session, graph_client, graph_ns):
    from app.graph.reader import GraphReader

    seed_world(db_session)
    request = _quote_request(db_session)

    run = run_estimate(db_session, request.id, AS_OF, ScriptedLLM([]), GraphReader(graph_client, graph_ns), FakeEmbedder())

    assert run.result.status == "needs_review" and "out of date" in run.result.reason
    assert run.result.draft is None and run.result.iterations == 0
    assert get_estimate_draft(db_session, run.row.id).draft is None
```

(add `seed_chain_world` to the seed import in that file.)

`backend/tests/api/v1/test_estimate_route.py`: every existing test that runs the agent and expects a draft to be produced (all except the 404 and the `get_agent_client` key tests) must build the graph first: add the `make_reader` fixture parameter and call `make_reader()` right after `seed_world(db_session)`. Add:

```python
def test_estimate_endpoint_reports_needs_review_when_the_graph_was_never_built(db_session):
    seed_world(db_session)
    row = _request_row(db_session)

    response = _post(db_session, ScriptedLLM([]), {"quote_request_id": str(row.id)})

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "needs_review" and "out of date" in body["reason"]
    assert body["draft"] is None


def test_estimate_endpoint_reports_needs_review_when_the_graph_is_down(db_session):
    seed_world(db_session)
    row = _request_row(db_session)
    app.dependency_overrides[get_graph_client] = lambda: FailingGraphClient()
    try:
        response = _post(db_session, ScriptedLLM([]), {"quote_request_id": str(row.id)})
    finally:
        app.dependency_overrides.pop(get_graph_client, None)

    assert response.status_code == 200
    assert "knowledge graph unavailable" in response.json()["reason"]
```

Update the two tests added in Task 11 (`syncs_the_quote`, `still_answers_when_the_graph_sync_fails`): they already call `make_reader()`, so they keep working; the second now returns `needs_review` because its reader also uses the failing client, and it still asserts only the 200.

`backend/tests/test_phase3_acceptance.py`:
- Add a helper that quotes a SKU together with its required parts (transitively), so a correct draft is still correct:

```python
def _with_required_parts(session, sku_id):
    """The SKU and every part it needs, transitively, in a stable order."""
    ordered, queue = [], [sku_id]
    while queue:
        current = queue.pop(0)
        if current not in ordered:
            ordered.append(current)
            queue.extend(required_sku_ids(session, current))
    return ordered
```

  (import `required_sku_ids` from `app.reference_data.repository`.)
- Rewrite `_draft_with_discount(session, case, discount_pct)` so the requested SKU carries the discount and each required part is a plain list-price line:

```python
def _draft_with_discount(session, case, discount_pct):
    entities = case["entities"]
    lines = []
    for position, sku_id in enumerate(_with_required_parts(session, entities["sku_id"])):
        sku = get_sku(session, sku_id)
        lines.append({"sku_id": sku.sku_id, "quantity": 1, "unit_price": sku.list_price, "price_source": "list",
                      "discount_pct": discount_pct if position == 0 else 0.0})
    return {"customer_id": entities["customer_id"], "contract_id": entities["contract_id"], "lines": lines}
```

- In `test_discount_on_a_covered_category_is_allowed_for_the_same_customers` pick a covered SKU that needs nothing (`and not required_sku_ids(db_session, s.sku_id)` in the generator), and make the request resolve that SKU: give `_quote_request(session, case, sku_id=None)` an optional `sku_id` that overrides `entities["sku_id"]` in `resolved_line_items` and `content_fingerprint`, and pass `sku_id=covered_sku.sku_id` in that test.

- [ ] **Step 8: Run to verify pass**

Run the full suite `pytest -q`. Expected: all PASS. If a Phase 3 test still fails, confirm the draft is genuinely incomplete under the new rule and fix the draft; if you cannot justify it that way, stop and report it as a finding.

- [ ] **Step 9: Commit**

```bash
git add backend/app/estimate/guardrails.py backend/app/estimate/graph.py backend/tests/app/estimate/test_graph_integrity.py backend/tests/app/estimate/test_graph.py backend/tests/app/estimate/test_service.py backend/tests/api/v1/test_estimate_route.py backend/tests/test_phase3_acceptance.py
git commit -m "feat: block left-in discontinued SKUs and missing required parts via the graph, failing closed"
```

---

### Task 13: Phase 4 acceptance test, docs, and the dev-environment load

**Files:**
- Create: `backend/tests/test_phase4_acceptance.py`
- Modify: `README.md`, `docs/roadmap.md`, `docs/adr/0002-neo4j-for-knowledge-graph.md`, `docs/gotchas.md`, `backend/README.md`

**Interfaces:**
- Consumes: everything above. Reads `backend/data/scenarios.json` (60 real emails with entities, as the Phase 3 acceptance test does).
- Produces: the proof of the Phase 4 goal, and the docs.

- [ ] **Step 1: Write the acceptance test**

Create `backend/tests/test_phase4_acceptance.py`:

```python
import json
from pathlib import Path

from app.estimate.constant import DATASET_AS_OF
from app.estimate.service import run_estimate
from app.intake.repository import save_quote_request
from app.reference_data.repository import contracts_for_customer, get_sku, required_sku_ids
from core.llm.openai_agent_client import AgentTurn, ToolCall
from load_data import load_catalog, load_customers, load_pricing, load_structure
from tests.graph_support import FakeEmbedder

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
FEEDBACK_PREFIX = "The draft failed validation"


def _load_world(session):
    load_catalog(session, json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8")))
    load_customers(session, json.loads((DATA_DIR / "customers.json").read_text(encoding="utf-8")))
    session.flush()
    load_pricing(session, json.loads((DATA_DIR / "pricing.json").read_text(encoding="utf-8")))
    load_structure(session, json.loads((DATA_DIR / "structure.json").read_text(encoding="utf-8")))
    session.flush()


def _cases(scenario_type):
    scenarios = json.loads((DATA_DIR / "scenarios.json").read_text(encoding="utf-8"))
    return [s for s in scenarios if s["scenario_type"] == scenario_type]


def _closure(session, sku_id):
    """The SKU and every part it needs, transitively, straight from Postgres (the test's own reference)."""
    ordered, queue = [], [sku_id]
    while queue:
        current = queue.pop(0)
        if current not in ordered:
            ordered.append(current)
            queue.extend(required_sku_ids(session, current))
    return ordered


def _line(sku, discount_pct=0.0):
    return {"sku_id": sku.sku_id, "quantity": 1, "unit_price": sku.list_price, "price_source": "list",
            "discount_pct": discount_pct}


def _submit(draft, call_id):
    return AgentTurn(content=None, tool_calls=[ToolCall(id=call_id, name="submit_draft", arguments=draft)])


class WalkingAgent:
    """A deterministic stand-in for the model that does what the system prompt says: ask the graph about the
    requested SKU and every required part, ask whether the customer's contract covers the SKU, then submit what the
    tools returned. With `naive_first` it submits the planted mistake first, so the test can see the guardrail
    block it. With `only_naive` it never learns, so the test can see the mistake never ends `ready`."""

    def __init__(self, session, case, *, naive_first=False, only_naive=False):
        entities = case["entities"]
        self._session = session
        self._scenario_type = case["scenario_type"]
        self._customer_id = entities["customer_id"]
        self._requested = entities["sku_id"]
        self._naive_first = naive_first
        self._only_naive = only_naive
        self._naive_sent = False
        self._ids = 0
        self.violation_feedback = None
        self.tool_names = []

    def next_turn(self, messages, tools):
        feedback = [m["content"] for m in messages if m["role"] == "user" and m["content"].startswith(FEEDBACK_PREFIX)]
        if feedback:
            self.violation_feedback = feedback[-1]
        if self._only_naive or (self._naive_first and not self._naive_sent):
            self._naive_sent = True
            return _submit(self._naive_draft(), self._next_id())

        related, coverage = self._tool_results(messages)
        calls, quoted = self._plan(related)
        if not calls and quoted[0] not in coverage:
            calls = [("check_contract_coverage", {"customer_id": self._customer_id, "sku_id": quoted[0]})]
        if calls:
            self.tool_names.extend(name for name, _ in calls)
            return AgentTurn(content=None, tool_calls=[
                ToolCall(id=self._next_id(), name=name, arguments=arguments) for name, arguments in calls
            ])
        return _submit(self._final_draft(quoted, coverage[quoted[0]]), self._next_id())

    def _next_id(self):
        self._ids += 1
        return f"walk-{self._ids}"

    @staticmethod
    def _tool_results(messages):
        related, coverage = {}, {}
        for message in messages:
            if message["role"] != "tool":
                continue
            payload = json.loads(message["content"])
            assert "error" not in payload, payload
            if "live_sku_id" in payload:
                related[payload["sku_id"]] = payload
            elif "contracts" in payload:
                coverage[payload["sku_id"]] = payload
        return related, coverage

    def _plan(self, related):
        """The tool calls still needed and, once none are, the SKUs to quote (requested SKU's live end first)."""
        calls, quoted, queue, seen = [], [], [self._requested], set()
        while queue:
            sku_id = queue.pop(0)
            if sku_id in seen:
                continue
            seen.add(sku_id)
            result = related.get(sku_id)
            if result is None:
                calls.append(("get_related_parts", {"sku_id": sku_id}))
                continue
            assert result["live_sku_id"] is not None, f"{sku_id} has no live replacement"
            if result["live_sku_id"] not in quoted:
                quoted.append(result["live_sku_id"])
            queue.extend(part["sku_id"] for part in result["required_parts"])
        return calls, quoted

    def _naive_draft(self):
        requested = get_sku(self._session, self._requested)
        if self._scenario_type == "discount_category_mismatch":
            contract = contracts_for_customer(self._session, self._customer_id)[0]
            return {"customer_id": self._customer_id, "contract_id": contract.contract_id,
                    "lines": [_line(requested, contract.discount_pct)]}
        return {"customer_id": self._customer_id, "contract_id": None, "lines": [_line(requested)]}

    def _final_draft(self, quoted, coverage):
        applying = next((c for c in coverage["contracts"] if c["discount_applies"]), None)
        lines = [
            _line(get_sku(self._session, sku_id), applying["discount_pct"] if applying and index == 0 else 0.0)
            for index, sku_id in enumerate(quoted)
        ]
        return {"customer_id": self._customer_id, "contract_id": applying["contract_id"] if applying else None,
                "lines": lines}


def _request(session, case):
    entities = case["entities"]
    return save_quote_request(
        session, raw_email_text=case["email_text"],
        parsed_json={"resolved_line_items": [
            {"sku_name_as_written": entities["sku_name"], "sku_id": entities["sku_id"], "quantity": "1"}]},
        content_fingerprint={"sku_ids": [entities["sku_id"]]}, style_fingerprint={"tokens": []},
        customer_id=entities["customer_id"], case_id=case["case_id"],
    )


def _run(session, graph, case, agent):
    return run_estimate(session, _request(session, case).id, DATASET_AS_OF, agent, graph, FakeEmbedder())


def _quoted_ids(run):
    return [line.sku_id for line in run.result.draft.lines]


def test_every_discontinued_swap_is_blocked_then_fixed_by_walking_the_graph(db_session, make_reader):
    _load_world(db_session)
    graph = make_reader()
    cases = _cases("discontinued_swap")
    assert len(cases) == 10

    for case in cases:
        agent = WalkingAgent(db_session, case, naive_first=True)

        run = _run(db_session, graph, case, agent)

        requested = case["entities"]["sku_id"]
        replacement = get_sku(db_session, requested).replaced_by
        assert run.result.status == "ready", case["case_id"]
        assert run.result.iterations == 2, case["case_id"]
        assert "discontinued" in agent.violation_feedback and requested in agent.violation_feedback, case["case_id"]
        assert requested not in _quoted_ids(run) and replacement in _quoted_ids(run), case["case_id"]
        assert "get_related_parts" in agent.tool_names, case["case_id"]


def test_every_missing_required_part_is_blocked_then_added_from_the_graph(db_session, make_reader):
    _load_world(db_session)
    graph = make_reader()
    cases = _cases("missing_required_part")
    assert len(cases) == 10

    for case in cases:
        agent = WalkingAgent(db_session, case, naive_first=True)

        run = _run(db_session, graph, case, agent)

        needed = _closure(db_session, case["entities"]["sku_id"])
        assert len(needed) >= 2, case["case_id"]
        assert run.result.status == "ready", case["case_id"]
        assert run.result.iterations == 2, case["case_id"]
        assert "requires" in agent.violation_feedback, case["case_id"]
        assert set(needed) <= set(_quoted_ids(run)), case["case_id"]
        assert "get_related_parts" in agent.tool_names, case["case_id"]


def test_every_wrong_category_discount_is_blocked_then_dropped_after_asking_the_graph(db_session, make_reader):
    _load_world(db_session)
    graph = make_reader()
    cases = _cases("discount_category_mismatch")
    assert len(cases) == 10

    for case in cases:
        agent = WalkingAgent(db_session, case, naive_first=True)

        run = _run(db_session, graph, case, agent)

        requested_line = run.result.draft.lines[0]
        assert run.result.status == "ready", case["case_id"]
        assert run.result.iterations == 2, case["case_id"]
        assert "not covered" in agent.violation_feedback, case["case_id"]
        assert requested_line.sku_id == case["entities"]["sku_id"] and requested_line.discount_pct == 0.0, case["case_id"]
        assert "check_contract_coverage" in agent.tool_names, case["case_id"]


def test_the_planted_mistakes_never_end_ready_even_if_the_agent_never_learns(db_session, make_reader):
    _load_world(db_session)
    graph = make_reader()

    for scenario_type in ("discontinued_swap", "missing_required_part", "discount_category_mismatch"):
        for case in _cases(scenario_type):
            run = _run(db_session, graph, case, WalkingAgent(db_session, case, only_naive=True))

            assert run.result.status == "needs_review", case["case_id"]
            assert run.result.violations, case["case_id"]
            assert run.result.iterations == 4, case["case_id"]
```

- [ ] **Step 2: Run the acceptance test**

Run: `pytest tests/test_phase4_acceptance.py -v`. Expected: all four PASS. If a case fails, read the assertion message (it names the case id): a real defect in the graph, a tool, the guardrail or the data is the likely cause. Do not weaken an assertion; diagnose, and report a finding if the fix belongs to an earlier task.

- [ ] **Step 3: Update the docs**

`README.md`: replace the paragraph under `## Status` with:

```
Proof of concept, in progress. Phases 1 to 4 are built: synthetic data generation, intake and dedupe, the pricing agent with code guardrails, and the Neo4j knowledge graph (the article's 10 node and 15 edge types, Leiden communities, local and global query modes, and a router over SQL, graph and vector search) with graph-backed guardrails that block a left-in discontinued SKU or a missing required part. No production data source exists; the dataset is generated to be structurally realistic (referential integrity, graph relationships, discontinued/substitute/required-part patterns) so every downstream component has something real to reason over.
```

`docs/roadmap.md`: under `## Phase 4: Knowledge graph`, after the "Why fourth, not first" line add:

```
Status: complete (see docs/superpowers/specs/2026-09-28-phase4-knowledge-graph-design.md). The full 10 node and 15 edge schema is built from Postgres as a rebuildable projection; Leiden, local and global modes, LLM community summaries (cached, cost-gated), the pgvector arm and the rule-based router are in. Embeddings and community summaries have not been generated against the real data: both scripts are dry runs until run with --yes.
```

`docs/adr/0002-neo4j-for-knowledge-graph.md`: append under `## Notes`:

```
Verified 2026-09-28: `neo4j:2026.09.0-community` with `NEO4J_PLUGINS='["graph-data-science"]'` starts cleanly and `gds.version()` returns 2026.09.0, so Leiden works on Community edition. The image tag is pinned in `docker-compose.yml` because an auto-fetched GDS build has failed on other Neo4j versions. Host ports 17474 and 17687 are used to avoid the defaults. See `docs/research/neo4j-gds-leiden-community.md`.
```

`docs/gotchas.md`: append:

```
## 2026-09-28 (Phase 4)

- `gds.graph.project` used as a Cypher aggregation returns one row with a null graph name, not zero rows, when the MATCH finds nothing. Check for the null before calling an algorithm on the projection, or it fails with "graph does not exist".
- `SET n += {prop: null}` removes the property in Neo4j instead of storing null. A SKU with no list price therefore has no `list_price` property; read it with `n.list_price IS NULL`.
- Community edition has no composite node keys. Uniqueness across namespaces is enforced on a single `key` property holding `<namespace>:<id>`.
- GDS Leiden only accepts undirected projections. Declare `undirectedRelationshipTypes: ['*']` when projecting, and set `randomSeed` (and `concurrency: 1`) if two runs must agree.
- `gds.graph.drop(name, false)` returns a deprecated `schema` column; `YIELD graphName` alone avoids the notification.
- A Cypher pattern in a `RETURN` needs `EXISTS { ... }` or `COLLECT { ... }`; a bare pattern expression is rejected by current Neo4j.
- `MERGE (a)-[r:T]->(b)` collapses two relationships of the same type between the same pair of nodes into one. PRICE_VARIANCE is written with delete-then-CREATE so two lines for one SKU stay two edges.
```

`backend/README.md`: append a section:

````
## Phase 4: knowledge graph

Neo4j 2026.09 Community with the GDS plugin runs in Docker on host ports 17474 (browser) and 17687 (Bolt); the defaults are avoided on purpose. Start it with `docker compose up -d neo4j` (or `docker start neo4j-estimate` if the container already exists). Postgres stays authoritative: the graph is a rebuildable, namespaced projection (`GRAPH_NAMESPACE`, default `main`).

Apply the schema and load the new reference data (product families, one project per site, contacts):

```
uv run alembic upgrade head
uv run python scripts/load_data.py
```

Build or refresh the graph and recompute the Leiden communities (an API call, not a script):

```
curl -X POST http://localhost:8000/v1/graph/rebuild
```

Ask a question; the router picks SQL, graph-local, graph-global or vector search and returns the evidence:

```
curl -X POST http://localhost:8000/v1/retrieval/ask -H "Content-Type: application/json" -d '{"question": "what does SKU-0601 require"}'
```

Two scripts call paid APIs, and both are dry runs until `--yes` is passed. Run them bare first to see the plan and the token estimate:

```
uv run python scripts/embed_skus.py          # SKU embeddings for the vector route
uv run python scripts/summarize_communities.py   # one LLM summary per community, cached in Postgres
```

Tests need Neo4j running. Each test gets its own graph namespace and drops it afterwards, so tests never touch the `main` graph. If Neo4j is down the suite fails with the command to start it.
````

- [ ] **Step 4: Dev-environment load (the only step allowed to touch the `main` graph)**

This applies the merged code to the developer's own local environment. It is free and idempotent. From `backend/` with `DATABASE_URL` and `OPENAI_API_KEY=unused` inline:

1. `alembic upgrade head` (already applied in Task 3; confirm it reports nothing to do).
2. `.venv/Scripts/python.exe scripts/load_data.py`: loads contacts, families and projects into the dev Postgres. Report the printed counts.
3. Build the dev graph and Leiden communities in namespace `main` with a one-off script (do not commit it):

```python
from core.config.settings import Settings
from core.db.session import make_engine, make_session_factory
from core.graph.client import get_graph_client
from app.graph.service import global_stats, rebuild_graph, run_communities

settings = Settings()
session = make_session_factory(make_engine(settings.database_url))()
client = get_graph_client()
summary = rebuild_graph(session, client, "main")
communities = run_communities(client, "main")
sizes = sorted((s.size for s in global_stats(client, "main")), reverse=True)
print(summary.node_counts, summary.edge_counts)
print(communities, "top sizes:", sizes[:10], "communities of at least 3:", sum(1 for s in sizes if s >= 3))
```

4. Run both cost-gated scripts bare, without `--yes`, and report their output: `scripts/embed_skus.py` and `scripts/summarize_communities.py`. This gives the owner the exact SKU count, community count and token estimates. Do not pass `--yes`.
5. Verify nothing was generated: `select count(*) from sku_embeddings` and `select count(*) from community_summaries` are both 0.

- [ ] **Step 5: Run the whole suite and commit**

Run `pytest -q` once more. Expected: all PASS; report the total (274 plus every test added by this plan). Then:

```bash
git add backend/tests/test_phase4_acceptance.py README.md docs/roadmap.md docs/adr/0002-neo4j-for-knowledge-graph.md docs/gotchas.md backend/README.md
git commit -m "test: prove the three planted mistakes are resolved through the graph; document Phase 4"
```

---

## Self-review (writing-plans checklist, run against the spec)

- **Spec coverage.** Data additions: Task 2 (families, projects, validation), Task 3 (migration 0004, tables, contacts, loader). Infrastructure and settings: Task 1. Full 10-node and 15-edge schema: Task 4 (reference edges and nodes), Task 6 (FOR_PROJECT, DUPLICATE_OF, REVISION_OF, VARIANT_OF, SUPERSEDES, PRICE_VARIANCE, QuoteRequest, Quote). Freshness fingerprint: Task 4 (compute and store), Task 12 (check). Namespaces and test isolation: Tasks 1, 4. Tools (`get_related_parts`, `check_contract_coverage`, `ask_knowledge`) and `ToolContext` gap: Task 11. Guardrail rules 1 to 4 and fail-closed: Task 12. Sync best-effort and hooks in intake, dedupe, estimate routes: Tasks 6 and 11. Leiden, local (hub rule, cap), global statistics: Task 7. Summaries with Postgres cache and cost gate: Task 8. Embeddings, vector arm, cost gate: Task 9. Router, knowledge service, endpoints: Task 10. Acceptance on the 30 real cases and the never-ready proof: Task 13. Docs and dev load: Task 13.
- **Placeholder scan.** No TBD, TODO or "handle edge cases" instructions; every code step carries code. The two places that say "the rest of the function is unchanged" (Task 11, `run_estimate` and the route return) point at code that already exists in the file and is not modified.
- **Type consistency.** `GraphReader` methods (`sku_chain`, `required_parts`, `contract_coverage`, `stored_fingerprint`) are used with the same names and shapes in Tasks 11 and 12 and in the test doubles (`FailingGraphReader`, `TogglableReader`). `merge_nodes`/`merge_edges` row shapes are the same in Tasks 4 and 6. `CommunityStats` fields match between Tasks 7, 8 and 10. `run_estimate(session, quote_request_id, as_of, llm_client, graph, embedder)` is the signature everywhere after Task 11. `RebuildSummary` is defined in Task 4 and returned by `rebuild_graph` in Task 6.
- **Review Focus.** Each of the five has a test marked "(Review Focus)" in Tasks 5, 6, 7, 10 and 12.
- **Known ordering hazard.** Task 5's `tests/conftest.py` imports `tests.graph_support`, which imports `app.graph.reader` (created in the same task, step 5). Task 11's `make_ctx` is added to `graph_support` after `ToolContext` has its final shape (step 5 of Task 11). Each task states which steps must run before the suite is run.
