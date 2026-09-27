# Phase 1 Synthetic Data Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the six-script Phase 1 pipeline (`config.py`, `catalog_gen.py`, `customer_gen.py`, `graph_export.py`, `scenario_gen.py`, `validate.py`) that produces a structurally realistic, deterministic synthetic dataset (catalog, customers, graph nodes/edges, 60 labeled scenario emails) for later phases to build on.

**Architecture:** Each generator is a plain Python module with pure functions (generate/select/build) plus a thin CLI wrapper, so every function is independently unit-testable without touching disk or the network. Randomness is deterministic via `random.Random(seed)`, with a distinct seed offset per generator so their draws don't correlate. `scenario_gen.py` never calls an LLM: it writes prompt files for a human to paste into a chat platform and ingests the pasted-back JSON.

**Tech Stack:** Python 3.11 (already pinned via `uv init`), stdlib only for the generators (`random`, `json`, `itertools`, `datetime`, `pathlib`, `argparse`), `pytest` as the only added dependency (dev-only, via `uv add --dev pytest`). No faker, no pandas, no pydantic, no LLM SDK: nothing here needs them, and the spec's LLM step is a manual copy/paste workflow, not an API call.

**Spec:** `docs/superpowers/specs/2026-09-27-phase1-synthetic-data-design.md` (read in full; this plan implements it exactly, including the `HAS_CONTRACT` edge added to the Graph Schema section during planning).

## Global Constraints

- Fixed seed = 42 for the whole pipeline; every generator must reseed from `config.seed` (offset per generator, documented in Task 1) so re-running with the same seed reproduces identical output.
- `sku_count` must be in [500, 800]; default 650. `customer_count` must be in [100, 150]; default 125. `scenarios_per_type` is fixed at 10 (60 total), not a tunable range.
- `scenario_gen.py` never calls an LLM API directly; it only writes prompt files and reads back human-pasted response files.
- No Postgres/Neo4j writes anywhere in this phase; everything is file-based under `backend/data/`.
- No generator overwrites existing output without an explicit `--force` flag.
- No em dash anywhere in any file (code, comments, docs). No emojis. No AI attribution in commit messages.
- Every generator fails loud (raises, does not default silently) on invalid config: zero/negative counts, missing seed.

## Review Focus

- **Empty or whitespace-only `email_text` in a pasted response.** A response entry with `"email_text": "  "` must be rejected by ingest, not accepted as a real answer. Covered in Task 7's ingest tests.
- **One malformed JSON response file must not abort the whole ingest run.** If `batch_002.json` fails to parse, `batch_001.json` and `batch_003.json` must still be processed and their valid cases accepted. Covered in Task 7.
- **Scenario case selection must be deterministic on its own inputs, not just on the catalog/customer generators.** Given the same generated catalog and customers, running `select_cases` twice with the same seed must produce identical case-to-entity assignments (same SKUs, same customers, same case_ids). Covered in Task 5.
- **A customer whose contract covers every category contributes zero discount-mismatch triples.** Case selection must tolerate some customers contributing nothing to the `discount_category_mismatch` pool and still succeed as long as the total pool across all customers reaches the required count; it must raise a clear error only when the whole pool is too small, not per-customer. Covered in Task 5.
- **A partial pipeline re-run must not leave a mismatched dataset.** If `backend/data/catalog.json` already exists and `customers.json` does not, running without `--force` must fail before writing anything else, not overwrite `customers.json` while silently leaving a stale `catalog.json` from a previous, different-seed run. Covered in Task 9.

---

## Task 0: Project scaffolding and pytest wiring

**Files:**
- Create: `backend/scripts/data_gen/__init__.py`
- Modify: `backend/pyproject.toml`
- Test: none (infrastructure only, verified by Task 1's test running successfully)

**Interfaces:**
- Produces: an importable `data_gen` package under `backend/scripts/`, and a working `uv run pytest` command from `backend/`.

- [ ] **Step 1: Create the empty package marker**

`backend/scripts/data_gen/__init__.py`:
```python
```
(empty file; makes `data_gen` importable as a package)

- [ ] **Step 2: Add pytest as a dev dependency**

Run from `backend/`: `uv add --dev pytest`

This adds `pytest` to `[tool.uv.dev-dependencies]` (or `[dependency-groups]` depending on the installed `uv` version) in `pyproject.toml` and updates `uv.lock`.

- [ ] **Step 3: Point pytest at the scripts package and the tests directory**

Add to `backend/pyproject.toml`:
```toml
[tool.pytest.ini_options]
pythonpath = ["scripts"]
testpaths = ["tests"]
```

- [ ] **Step 4: Verify pytest runs (even with zero tests)**

Run: `cd backend && uv run pytest`
Expected: `no tests ran` (exit code 5) with no import errors. If it reports an import error, `pythonpath` is misconfigured; fix before continuing.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/data_gen/__init__.py backend/pyproject.toml backend/uv.lock
git commit -m "chore: scaffold data_gen package and pytest config"
```

---

## Task 1: Config module

**Files:**
- Create: `backend/scripts/data_gen/config.py`
- Test: `backend/tests/data_gen/test_config.py`

**Interfaces:**
- Produces: `Config` (frozen dataclass with fields `seed: int`, `sku_count: int`, `customer_count: int`, `scenarios_per_type: int`), `DEFAULT: Config`, `validate_config(config: Config) -> None` (raises `ValueError` on any invalid field).

- [ ] **Step 1: Write the failing tests**

`backend/tests/data_gen/test_config.py`:
```python
import pytest

from data_gen.config import Config, DEFAULT, validate_config


def test_default_config_is_valid():
    validate_config(DEFAULT)


def test_rejects_zero_sku_count():
    bad = Config(seed=1, sku_count=0, customer_count=100, scenarios_per_type=10)
    with pytest.raises(ValueError):
        validate_config(bad)


def test_rejects_negative_customer_count():
    bad = Config(seed=1, sku_count=500, customer_count=-5, scenarios_per_type=10)
    with pytest.raises(ValueError):
        validate_config(bad)


def test_rejects_zero_scenarios_per_type():
    bad = Config(seed=1, sku_count=500, customer_count=100, scenarios_per_type=0)
    with pytest.raises(ValueError):
        validate_config(bad)


def test_rejects_missing_seed():
    bad = Config(seed=None, sku_count=500, customer_count=100, scenarios_per_type=10)
    with pytest.raises(ValueError):
        validate_config(bad)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/data_gen/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'data_gen.config'`

- [ ] **Step 3: Write the implementation**

`backend/scripts/data_gen/config.py`:
```python
import dataclasses


@dataclasses.dataclass(frozen=True)
class Config:
    seed: int
    sku_count: int
    customer_count: int
    scenarios_per_type: int


DEFAULT = Config(seed=42, sku_count=650, customer_count=125, scenarios_per_type=10)


def validate_config(config: Config) -> None:
    if config.seed is None:
        raise ValueError("seed must be set")
    if config.sku_count <= 0:
        raise ValueError("sku_count must be positive")
    if config.customer_count <= 0:
        raise ValueError("customer_count must be positive")
    if config.scenarios_per_type <= 0:
        raise ValueError("scenarios_per_type must be positive")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/data_gen/test_config.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/data_gen/config.py backend/tests/data_gen/test_config.py
git commit -m "feat: add data_gen config with validation"
```

---

## Task 2: Catalog generator

**Files:**
- Create: `backend/scripts/data_gen/catalog_gen.py`
- Test: `backend/tests/data_gen/test_catalog_gen.py`

**Interfaces:**
- Consumes: `Config` from Task 1 (`config.seed`, `config.sku_count`).
- Produces: `generate_catalog(config: Config) -> list[dict]` (each dict: `sku_id, name, category, list_price, discontinued, replaced_by, requires, in_stock`), `write_catalog(skus: list[dict], path: pathlib.Path, force: bool = False) -> None`, `CATEGORIES: list[str]` (used by `customer_gen.py` and `scenario_gen.py`).

- [ ] **Step 1: Write the failing tests**

`backend/tests/data_gen/test_catalog_gen.py`:
```python
from data_gen.catalog_gen import generate_catalog
from data_gen.config import Config


def _config(sku_count=650):
    return Config(seed=42, sku_count=sku_count, customer_count=125, scenarios_per_type=10)


def test_generates_requested_count():
    catalog = generate_catalog(_config())
    assert len(catalog) == 650


def test_every_replaced_by_target_exists_and_is_not_discontinued():
    catalog = generate_catalog(_config())
    by_id = {s["sku_id"]: s for s in catalog}
    discontinued_with_replacement = [s for s in catalog if s["discontinued"]]
    assert discontinued_with_replacement, "expected at least one discontinued SKU"
    for sku in discontinued_with_replacement:
        assert sku["replaced_by"] in by_id
        assert by_id[sku["replaced_by"]]["discontinued"] is False


def test_every_requires_target_exists():
    catalog = generate_catalog(_config())
    by_id = {s["sku_id"]: s for s in catalog}
    skus_with_requires = [s for s in catalog if s["requires"]]
    assert skus_with_requires, "expected at least one SKU with a requires link"
    for sku in skus_with_requires:
        for target in sku["requires"]:
            assert target in by_id


def test_deterministic_across_two_runs():
    first = generate_catalog(_config())
    second = generate_catalog(_config())
    assert first == second


def test_rejects_sku_count_larger_than_available_combinations():
    huge = _config(sku_count=1_000_000)
    try:
        generate_catalog(huge)
        assert False, "expected ValueError for an unreachable sku_count"
    except ValueError:
        pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/data_gen/test_catalog_gen.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'data_gen.catalog_gen'`

- [ ] **Step 3: Write the implementation**

`backend/scripts/data_gen/catalog_gen.py`:
```python
import argparse
import itertools
import json
import random
from pathlib import Path

from data_gen.config import DEFAULT, Config, validate_config

CATEGORIES = [
    "Plumbing-Fittings",
    "Plumbing-Fixtures",
    "HVAC-Parts",
    "HVAC-Equipment",
    "Electrical-Supplies",
]

BASE_NAMES = {
    "Plumbing-Fittings": ["Elbow", "Coupling", "Tee", "Union", "Adapter", "Cap", "Bushing", "Nipple"],
    "Plumbing-Fixtures": ["Faucet", "Valve", "Trap", "Drain", "Shutoff", "Sprayer", "Aerator", "Stopper"],
    "HVAC-Parts": ["Filter", "Belt", "Capacitor", "Contactor", "Thermostat", "Sensor", "Motor Mount", "Gasket"],
    "HVAC-Equipment": ["Condenser", "Blower", "Compressor", "Evaporator Coil", "Air Handler", "Heat Exchanger"],
    "Electrical-Supplies": ["Breaker", "Wire Nut", "Junction Box", "Conduit", "Outlet", "Switch", "Relay"],
}

MATERIALS = {
    "Plumbing-Fittings": ["Copper", "PVC", "Brass", "Galvanized"],
    "Plumbing-Fixtures": ["Chrome", "Brass", "Stainless", "Plastic"],
    "HVAC-Parts": ["OEM", "Universal", "Aftermarket"],
    "HVAC-Equipment": ["Residential", "Commercial", "High-Efficiency"],
    "Electrical-Supplies": ["Standard", "Heavy-Duty", "Weatherproof"],
}

SIZES = {
    "Plumbing-Fittings": ["1/2 in", "3/4 in", "1 in", "1-1/4 in", "1-1/2 in", "2 in"],
    "Plumbing-Fixtures": ["Standard", "Compact", "Wall-Mount", "Deck-Mount"],
    "HVAC-Parts": ["Small", "Medium", "Large", "16x20", "20x25"],
    "HVAC-Equipment": ["2 Ton", "3 Ton", "4 Ton", "5 Ton"],
    "Electrical-Supplies": ["15A", "20A", "30A", "50A"],
}


def _all_name_variants():
    variants = []
    for category in CATEGORIES:
        for material, base, size in itertools.product(MATERIALS[category], BASE_NAMES[category], SIZES[category]):
            variants.append((category, f"{material} {base} {size}"))
    return variants


def generate_catalog(config: Config) -> list[dict]:
    validate_config(config)
    rng = random.Random(config.seed)

    variants = _all_name_variants()
    rng.shuffle(variants)
    if len(variants) < config.sku_count:
        raise ValueError(f"not enough name combinations ({len(variants)}) for sku_count {config.sku_count}")
    chosen = variants[: config.sku_count]

    skus = []
    for i, (category, name) in enumerate(chosen):
        skus.append({
            "sku_id": f"SKU-{i + 1:04d}",
            "name": name,
            "category": category,
            "list_price": round(rng.uniform(2.0, 450.0), 2),
            "discontinued": False,
            "replaced_by": None,
            "requires": [],
            "in_stock": rng.random() > 0.05,
        })

    by_category: dict[str, list[dict]] = {}
    for sku in skus:
        by_category.setdefault(sku["category"], []).append(sku)

    discontinued_count = max(1, int(len(skus) * 0.05))
    for sku in rng.sample(skus, discontinued_count):
        same_category = [s for s in by_category[sku["category"]] if s["sku_id"] != sku["sku_id"]]
        if not same_category:
            continue
        replacement = rng.choice(same_category)
        sku["discontinued"] = True
        sku["replaced_by"] = replacement["sku_id"]
        sku["in_stock"] = False

    discontinued_ids = {s["sku_id"] for s in skus if s["discontinued"]}
    for sku in skus:
        if sku["replaced_by"] in discontinued_ids:
            fallback = [
                s for s in by_category[sku["category"]]
                if s["sku_id"] != sku["sku_id"] and s["sku_id"] not in discontinued_ids
            ]
            sku["replaced_by"] = rng.choice(fallback)["sku_id"] if fallback else None

    eligible = [s for s in skus if not s["discontinued"]]
    requires_count = int(len(eligible) * 0.15)
    for sku in rng.sample(eligible, requires_count):
        same_category = [
            s for s in by_category[sku["category"]]
            if s["sku_id"] != sku["sku_id"] and not s["discontinued"]
        ]
        if same_category:
            sku["requires"] = [rng.choice(same_category)["sku_id"]]

    skus.sort(key=lambda s: s["sku_id"])
    return skus


def write_catalog(skus: list[dict], path: Path, force: bool = False) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists; pass --force to overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(skus, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the synthetic SKU catalog")
    parser.add_argument("--out", type=Path, default=Path("data/catalog.json"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    catalog = generate_catalog(DEFAULT)
    write_catalog(catalog, args.out, force=args.force)
    print(f"wrote {len(catalog)} SKUs to {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/data_gen/test_catalog_gen.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/data_gen/catalog_gen.py backend/tests/data_gen/test_catalog_gen.py
git commit -m "feat: add catalog generator with discontinued/requires linking"
```

---

## Task 3: Customer generator

**Files:**
- Create: `backend/scripts/data_gen/customer_gen.py`
- Test: `backend/tests/data_gen/test_customer_gen.py`

**Interfaces:**
- Consumes: `Config` from Task 1, `catalog: list[dict]` (only `category` field is read) from Task 2.
- Produces: `generate_customers(config: Config, catalog: list[dict]) -> list[dict]` (each dict: `customer_id, name, account_tier, contacts, sites, contracts`), `write_customers(customers, path, force=False) -> None`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/data_gen/test_customer_gen.py`:
```python
from datetime import date

from data_gen.catalog_gen import generate_catalog
from data_gen.config import Config
from data_gen.customer_gen import generate_customers


def _config(customer_count=125):
    return Config(seed=42, sku_count=650, customer_count=customer_count, scenarios_per_type=10)


def _catalog():
    return generate_catalog(_config())


def test_generates_requested_count():
    customers = generate_customers(_config(), _catalog())
    assert len(customers) == 125


def test_every_customer_has_contact_site_and_contract():
    for customer in generate_customers(_config(), _catalog()):
        assert len(customer["contacts"]) >= 1
        assert len(customer["sites"]) >= 1
        assert len(customer["contracts"]) >= 1


def test_contract_effective_from_precedes_effective_to():
    for customer in generate_customers(_config(), _catalog()):
        for contract in customer["contracts"]:
            start = date.fromisoformat(contract["effective_from"])
            end = date.fromisoformat(contract["effective_to"])
            assert start < end


def test_deterministic_across_two_runs():
    catalog = _catalog()
    first = generate_customers(_config(), catalog)
    second = generate_customers(_config(), catalog)
    assert first == second


def test_rejects_customer_count_larger_than_available_combinations():
    huge = _config(customer_count=1_000_000)
    try:
        generate_customers(huge, _catalog())
        assert False, "expected ValueError for an unreachable customer_count"
    except ValueError:
        pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/data_gen/test_customer_gen.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'data_gen.customer_gen'`

- [ ] **Step 3: Write the implementation**

`backend/scripts/data_gen/customer_gen.py`:
```python
import argparse
import itertools
import json
import random
from datetime import date, timedelta
from pathlib import Path

from data_gen.config import DEFAULT, Config, validate_config

ACCOUNT_TIERS = ["Standard", "Preferred", "Enterprise"]

COMPANY_WORDS = [
    "Metro", "Summit", "Northgate", "Riverside", "Union", "Lakeview", "Cascade",
    "Ironclad", "Bluewater", "Highline", "Coastal", "Prairie", "Redstone", "Harbor",
]
COMPANY_SUFFIXES = ["Plumbing", "HVAC", "Mechanical", "Services", "Contractors", "Co", "Group"]

FIRST_NAMES = ["Meera", "Suresh", "Ravi", "Kiran", "Priya", "Anil", "Devika", "Arjun", "Nisha", "Vikram"]
LAST_NAMES = ["Patel", "Shah", "Menon", "Rao", "Reddy", "Iyer", "Kapoor", "Nair", "Gupta", "Joshi"]

STREET_NAMES = ["Oak St", "Main St", "5th Ave", "Industrial Pkwy", "Elm St", "Commerce Dr", "River Rd"]
CITY_STATE_ZIP = [
    ("Springfield", "IL", "62701"), ("Fairview", "TX", "75069"), ("Georgetown", "OH", "45121"),
    ("Madison", "WI", "53703"), ("Clinton", "IA", "52732"), ("Salem", "OR", "97301"),
    ("Bristol", "CT", "06010"), ("Ashland", "KY", "41101"), ("Greenville", "SC", "29601"),
    ("Milton", "PA", "17847"),
]


def generate_customers(config: Config, catalog: list[dict]) -> list[dict]:
    validate_config(config)
    # offset seed so customer draws don't correlate with catalog_gen's draws from the same base seed
    rng = random.Random(config.seed + 1)
    categories = sorted({sku["category"] for sku in catalog})

    company_names = list(itertools.product(COMPANY_WORDS, COMPANY_SUFFIXES))
    rng.shuffle(company_names)
    if len(company_names) < config.customer_count:
        raise ValueError(
            f"not enough company name combinations ({len(company_names)}) for customer_count {config.customer_count}"
        )

    customers = []
    contract_counter = 1
    site_counter = 1
    for i in range(config.customer_count):
        word, suffix = company_names[i]
        customer_id = f"CUST-{i + 1:04d}"

        contacts = []
        for _ in range(rng.randint(1, 3)):
            first = rng.choice(FIRST_NAMES)
            last = rng.choice(LAST_NAMES)
            contacts.append({
                "name": f"{first} {last}",
                "email": f"{first.lower()}.{last.lower()}@{word.lower()}{suffix.lower()}.example.com",
                "phone": f"555-{rng.randint(100, 999)}-{rng.randint(1000, 9999)}",
            })

        sites = []
        for _ in range(rng.randint(1, 2)):
            city, state, zip_code = rng.choice(CITY_STATE_ZIP)
            sites.append({
                "site_id": f"SITE-{site_counter:04d}",
                "address": f"{rng.randint(10, 9999)} {rng.choice(STREET_NAMES)}, {city}, {state}",
                "zip": zip_code,
            })
            site_counter += 1

        covered = rng.sample(categories, k=rng.randint(1, len(categories) - 1))
        effective_from = date(2023, 1, 1) + timedelta(days=rng.randint(0, 600))
        effective_to = effective_from + timedelta(days=rng.randint(365, 1095))
        contracts = [{
            "contract_id": f"CTR-{contract_counter:04d}",
            "discount_category": rng.choice(covered),
            "covered_categories": covered,
            "effective_from": effective_from.isoformat(),
            "effective_to": effective_to.isoformat(),
        }]
        contract_counter += 1

        customers.append({
            "customer_id": customer_id,
            "name": f"{word} {suffix}",
            "account_tier": rng.choice(ACCOUNT_TIERS),
            "contacts": contacts,
            "sites": sites,
            "contracts": contracts,
        })

    return customers


def write_customers(customers: list[dict], path: Path, force: bool = False) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists; pass --force to overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(customers, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the synthetic customer roster")
    parser.add_argument("--catalog", type=Path, default=Path("data/catalog.json"))
    parser.add_argument("--out", type=Path, default=Path("data/customers.json"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    catalog = json.loads(args.catalog.read_text())
    customers = generate_customers(DEFAULT, catalog)
    write_customers(customers, args.out, force=args.force)
    print(f"wrote {len(customers)} customers to {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/data_gen/test_customer_gen.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/data_gen/customer_gen.py backend/tests/data_gen/test_customer_gen.py
git commit -m "feat: add customer generator with contracts, sites, contacts"
```

---

## Task 4: Graph exporter

**Files:**
- Create: `backend/scripts/data_gen/graph_export.py`
- Test: `backend/tests/data_gen/test_graph_export.py`

**Interfaces:**
- Consumes: `catalog: list[dict]` from Task 2, `customers: list[dict]` from Task 3.
- Produces: `build_nodes(catalog, customers) -> list[dict]` (`{id, label, properties}`), `build_edges(catalog, customers) -> list[dict]` (`{from, to, type, properties}`), `write_graph(nodes, edges, nodes_path, edges_path, force=False) -> None`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/data_gen/test_graph_export.py`:
```python
from data_gen.catalog_gen import generate_catalog
from data_gen.config import Config
from data_gen.customer_gen import generate_customers
from data_gen.graph_export import build_edges, build_nodes


def _dataset():
    config = Config(seed=42, sku_count=650, customer_count=125, scenarios_per_type=10)
    catalog = generate_catalog(config)
    customers = generate_customers(config, catalog)
    return catalog, customers


def test_one_sku_node_per_catalog_entry():
    catalog, customers = _dataset()
    nodes = build_nodes(catalog, customers)
    sku_nodes = [n for n in nodes if n["label"] == "SKU"]
    assert len(sku_nodes) == len(catalog)


def test_one_customer_node_per_customer():
    catalog, customers = _dataset()
    nodes = build_nodes(catalog, customers)
    customer_nodes = [n for n in nodes if n["label"] == "Customer"]
    assert len(customer_nodes) == len(customers)


def test_one_belongs_to_edge_per_sku():
    catalog, customers = _dataset()
    edges = build_edges(catalog, customers)
    belongs_to = [e for e in edges if e["type"] == "BELONGS_TO"]
    assert len(belongs_to) == len(catalog)


def test_has_contract_edge_per_customer_contract():
    catalog, customers = _dataset()
    edges = build_edges(catalog, customers)
    has_contract = [e for e in edges if e["type"] == "HAS_CONTRACT"]
    total_contracts = sum(len(c["contracts"]) for c in customers)
    assert len(has_contract) == total_contracts


def test_replaced_by_edges_match_discontinued_skus():
    catalog, customers = _dataset()
    edges = build_edges(catalog, customers)
    replaced_by_edges = [e for e in edges if e["type"] == "REPLACED_BY"]
    discontinued_with_target = [s for s in catalog if s["discontinued"] and s["replaced_by"]]
    assert len(replaced_by_edges) == len(discontinued_with_target)


def test_covers_edges_point_to_covered_categories():
    catalog, customers = _dataset()
    edges = build_edges(catalog, customers)
    covers_edges = [e for e in edges if e["type"] == "COVERS"]
    total_covered = sum(len(ctr["covered_categories"]) for c in customers for ctr in c["contracts"])
    assert len(covers_edges) == total_covered
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/data_gen/test_graph_export.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'data_gen.graph_export'`

- [ ] **Step 3: Write the implementation**

`backend/scripts/data_gen/graph_export.py`:
```python
import argparse
import json
from pathlib import Path


def build_nodes(catalog: list[dict], customers: list[dict]) -> list[dict]:
    nodes = []
    for sku in catalog:
        nodes.append({
            "id": sku["sku_id"],
            "label": "SKU",
            "properties": {
                "name": sku["name"],
                "category": sku["category"],
                "list_price": sku["list_price"],
                "discontinued": sku["discontinued"],
                "in_stock": sku["in_stock"],
            },
        })

    for category in sorted({sku["category"] for sku in catalog}):
        nodes.append({"id": category, "label": "Category", "properties": {}})

    for customer in customers:
        nodes.append({
            "id": customer["customer_id"],
            "label": "Customer",
            "properties": {"name": customer["name"], "account_tier": customer["account_tier"]},
        })
        for contract in customer["contracts"]:
            nodes.append({
                "id": contract["contract_id"],
                "label": "Contract",
                "properties": {
                    "discount_category": contract["discount_category"],
                    "effective_from": contract["effective_from"],
                    "effective_to": contract["effective_to"],
                },
            })

    return nodes


def build_edges(catalog: list[dict], customers: list[dict]) -> list[dict]:
    edges = []
    for sku in catalog:
        if sku["discontinued"] and sku["replaced_by"]:
            edges.append({"from": sku["sku_id"], "to": sku["replaced_by"], "type": "REPLACED_BY", "properties": {}})
        for required_id in sku["requires"]:
            edges.append({"from": sku["sku_id"], "to": required_id, "type": "REQUIRES", "properties": {}})
        edges.append({"from": sku["sku_id"], "to": sku["category"], "type": "BELONGS_TO", "properties": {}})

    for customer in customers:
        for contract in customer["contracts"]:
            edges.append({
                "from": customer["customer_id"],
                "to": contract["contract_id"],
                "type": "HAS_CONTRACT",
                "properties": {},
            })
            for category in contract["covered_categories"]:
                edges.append({
                    "from": contract["contract_id"],
                    "to": category,
                    "type": "COVERS",
                    "properties": {},
                })

    return edges


def write_graph(nodes: list[dict], edges: list[dict], nodes_path: Path, edges_path: Path, force: bool = False) -> None:
    for path in (nodes_path, edges_path):
        if path.exists() and not force:
            raise FileExistsError(f"{path} already exists; pass --force to overwrite")
    nodes_path.parent.mkdir(parents=True, exist_ok=True)
    edges_path.parent.mkdir(parents=True, exist_ok=True)
    nodes_path.write_text(json.dumps(nodes, indent=2))
    edges_path.write_text(json.dumps(edges, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Export catalog/customer data to graph nodes and edges")
    parser.add_argument("--catalog", type=Path, default=Path("data/catalog.json"))
    parser.add_argument("--customers", type=Path, default=Path("data/customers.json"))
    parser.add_argument("--nodes-out", type=Path, default=Path("data/graph/nodes.json"))
    parser.add_argument("--edges-out", type=Path, default=Path("data/graph/edges.json"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    catalog = json.loads(args.catalog.read_text())
    customers = json.loads(args.customers.read_text())
    nodes = build_nodes(catalog, customers)
    edges = build_edges(catalog, customers)
    write_graph(nodes, edges, args.nodes_out, args.edges_out, force=args.force)
    print(f"wrote {len(nodes)} nodes and {len(edges)} edges")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/data_gen/test_graph_export.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/data_gen/graph_export.py backend/tests/data_gen/test_graph_export.py
git commit -m "feat: add graph exporter for nodes and edges"
```

---

## Task 5: Scenario case selection

**Files:**
- Create: `backend/scripts/data_gen/scenario_gen.py`
- Test: `backend/tests/data_gen/test_scenario_gen.py`

**Interfaces:**
- Consumes: `Config` from Task 1, `catalog: list[dict]` from Task 2, `customers: list[dict]` from Task 3.
- Produces: `SCENARIO_TYPES: list[str]`, `select_cases(config: Config, catalog: list[dict], customers: list[dict]) -> list[dict]` (each dict: `case_id, scenario_type, customer, entities`). This task only implements selection; prompt generation and ingest are Tasks 6 and 7 in the same file.

- [ ] **Step 1: Write the failing tests**

`backend/tests/data_gen/test_scenario_gen.py`:
```python
from data_gen.catalog_gen import generate_catalog
from data_gen.config import Config
from data_gen.customer_gen import generate_customers
from data_gen.scenario_gen import SCENARIO_TYPES, select_cases


def _dataset():
    config = Config(seed=42, sku_count=650, customer_count=125, scenarios_per_type=10)
    catalog = generate_catalog(config)
    customers = generate_customers(config, catalog)
    return config, catalog, customers


def test_selects_exactly_ten_cases_per_type():
    config, catalog, customers = _dataset()
    cases = select_cases(config, catalog, customers)
    counts = {}
    for case in cases:
        counts[case["scenario_type"]] = counts.get(case["scenario_type"], 0) + 1
    for scenario_type in SCENARIO_TYPES:
        assert counts.get(scenario_type) == 10, f"{scenario_type}: {counts.get(scenario_type)}"


def test_sixty_total_cases_no_duplicate_ids():
    config, catalog, customers = _dataset()
    cases = select_cases(config, catalog, customers)
    assert len(cases) == 60
    case_ids = [c["case_id"] for c in cases]
    assert len(case_ids) == len(set(case_ids))


def test_deterministic_given_same_catalog_and_customers():
    config, catalog, customers = _dataset()
    first = select_cases(config, catalog, customers)
    second = select_cases(config, catalog, customers)
    assert first == second


def test_duplicate_pair_cases_share_entities_except_role():
    config, catalog, customers = _dataset()
    cases = select_cases(config, catalog, customers)
    duplicates = [c for c in cases if c["scenario_type"] == "duplicate_pair"]
    by_pair = {}
    for case in duplicates:
        by_pair.setdefault(case["entities"]["pair_id"], []).append(case)
    for pair_id, pair_cases in by_pair.items():
        assert len(pair_cases) == 2
        roles = {c["entities"]["pair_role"] for c in pair_cases}
        assert roles == {"first", "second"}
        skus = {tuple(c["entities"]["sku_ids"]) for c in pair_cases}
        assert len(skus) == 1, f"pair {pair_id} disagrees on sku_ids"


def test_discount_mismatch_survives_a_fully_covered_customer():
    config, catalog, customers = _dataset()
    # simulate a customer whose contract covers every category: must not crash selection
    all_categories = sorted({sku["category"] for sku in catalog})
    customers[0]["contracts"][0]["covered_categories"] = all_categories
    cases = select_cases(config, catalog, customers)
    mismatch_cases = [c for c in cases if c["scenario_type"] == "discount_category_mismatch"]
    assert len(mismatch_cases) == 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/data_gen/test_scenario_gen.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'data_gen.scenario_gen'`

- [ ] **Step 3: Write the implementation (selection portion only; Tasks 6-7 append to this file)**

`backend/scripts/data_gen/scenario_gen.py`:
```python
import random

SCENARIO_TYPES = [
    "discontinued_swap",
    "missing_required_part",
    "discount_category_mismatch",
    "duplicate_pair",
    "revision_pair",
    "clean_distinct",
]


def _customer_contact(customer, rng):
    contact = rng.choice(customer["contacts"])
    return {"name": customer["name"], "contact": contact["name"]}


def _select_discontinued_swap(catalog, customers, rng, count, next_index):
    candidates = [s for s in catalog if s["discontinued"] and s["replaced_by"]]
    if len(candidates) < count:
        raise ValueError(f"need {count} discontinued SKUs with a replacement, found {len(candidates)}")
    cases = []
    for i, sku in enumerate(rng.sample(candidates, count)):
        customer = rng.choice(customers)
        cases.append({
            "case_id": f"sc-{next_index + i:04d}",
            "scenario_type": "discontinued_swap",
            "customer": _customer_contact(customer, rng),
            "entities": {"customer_id": customer["customer_id"], "sku_id": sku["sku_id"], "sku_name": sku["name"]},
        })
    return cases


def _select_missing_required_part(catalog, customers, rng, count, next_index):
    candidates = [s for s in catalog if s["requires"] and not s["discontinued"]]
    if len(candidates) < count:
        raise ValueError(f"need {count} SKUs with a required part, found {len(candidates)}")
    cases = []
    for i, sku in enumerate(rng.sample(candidates, count)):
        customer = rng.choice(customers)
        cases.append({
            "case_id": f"sc-{next_index + i:04d}",
            "scenario_type": "missing_required_part",
            "customer": _customer_contact(customer, rng),
            "entities": {"customer_id": customer["customer_id"], "sku_id": sku["sku_id"], "sku_name": sku["name"]},
        })
    return cases


def _select_discount_category_mismatch(catalog, customers, rng, count, next_index):
    skus_by_category = {}
    for sku in catalog:
        if not sku["discontinued"]:
            skus_by_category.setdefault(sku["category"], []).append(sku)

    triples = []
    for customer in customers:
        for contract in customer["contracts"]:
            uncovered = [c for c in skus_by_category if c not in contract["covered_categories"]]
            for category in uncovered:
                for sku in skus_by_category[category]:
                    triples.append((customer, contract, sku))

    if len(triples) < count:
        raise ValueError(f"need {count} discount-mismatch cases, found {len(triples)}")

    cases = []
    for i, (customer, contract, sku) in enumerate(rng.sample(triples, count)):
        cases.append({
            "case_id": f"sc-{next_index + i:04d}",
            "scenario_type": "discount_category_mismatch",
            "customer": _customer_contact(customer, rng),
            "entities": {
                "customer_id": customer["customer_id"],
                "contract_id": contract["contract_id"],
                "covered_categories": contract["covered_categories"],
                "sku_id": sku["sku_id"],
                "sku_name": sku["name"],
                "sku_category": sku["category"],
            },
        })
    return cases


def _select_duplicate_pair(catalog, customers, rng, pair_count, next_index):
    eligible = [s for s in catalog if not s["discontinued"]]
    cases = []
    index = next_index
    for p in range(pair_count):
        customer = rng.choice(customers)
        site = rng.choice(customer["sites"])
        line_items = rng.sample(eligible, k=rng.randint(1, 2))
        shared_entities = {
            "customer_id": customer["customer_id"],
            "site_id": site["site_id"],
            "sku_ids": [s["sku_id"] for s in line_items],
            "pair_id": f"dup-{p + 1:04d}",
        }
        for role in ("first", "second"):
            cases.append({
                "case_id": f"sc-{index:04d}",
                "scenario_type": "duplicate_pair",
                "customer": _customer_contact(customer, rng),
                "entities": {**shared_entities, "pair_role": role},
            })
            index += 1
    return cases


def _select_revision_pair(catalog, customers, rng, pair_count, next_index):
    eligible = [s for s in catalog if not s["discontinued"]]
    cases = []
    index = next_index
    for p in range(pair_count):
        customer = rng.choice(customers)
        site = rng.choice(customer["sites"])
        original_items = rng.sample(eligible, k=rng.randint(1, 2))
        remaining = [s for s in eligible if s not in original_items]
        added_item = rng.choice(remaining)
        pair_id = f"rev-{p + 1:04d}"

        cases.append({
            "case_id": f"sc-{index:04d}",
            "scenario_type": "revision_pair",
            "customer": _customer_contact(customer, rng),
            "entities": {
                "customer_id": customer["customer_id"],
                "site_id": site["site_id"],
                "sku_ids": [s["sku_id"] for s in original_items],
                "pair_id": pair_id,
                "pair_role": "original",
            },
        })
        index += 1

        cases.append({
            "case_id": f"sc-{index:04d}",
            "scenario_type": "revision_pair",
            "customer": _customer_contact(customer, rng),
            "entities": {
                "customer_id": customer["customer_id"],
                "site_id": site["site_id"],
                "sku_ids": [s["sku_id"] for s in original_items] + [added_item["sku_id"]],
                "pair_id": pair_id,
                "pair_role": "revision",
            },
        })
        index += 1
    return cases


def _select_clean_distinct(catalog, customers, rng, count, next_index):
    eligible = [s for s in catalog if not s["discontinued"]]
    cases = []
    for i in range(count):
        customer = rng.choice(customers)
        line_items = rng.sample(eligible, k=rng.randint(1, 3))
        cases.append({
            "case_id": f"sc-{next_index + i:04d}",
            "scenario_type": "clean_distinct",
            "customer": _customer_contact(customer, rng),
            "entities": {"customer_id": customer["customer_id"], "sku_ids": [s["sku_id"] for s in line_items]},
        })
    return cases


def select_cases(config, catalog: list[dict], customers: list[dict]) -> list[dict]:
    # offset seed so scenario selection doesn't correlate with catalog_gen's or customer_gen's draws
    rng = random.Random(config.seed + 2)
    per_type = config.scenarios_per_type
    pair_count = per_type // 2

    cases: list[dict] = []
    cases += _select_discontinued_swap(catalog, customers, rng, per_type, len(cases) + 1)
    cases += _select_missing_required_part(catalog, customers, rng, per_type, len(cases) + 1)
    cases += _select_discount_category_mismatch(catalog, customers, rng, per_type, len(cases) + 1)
    cases += _select_duplicate_pair(catalog, customers, rng, pair_count, len(cases) + 1)
    cases += _select_revision_pair(catalog, customers, rng, pair_count, len(cases) + 1)
    cases += _select_clean_distinct(catalog, customers, rng, per_type, len(cases) + 1)
    return cases
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/data_gen/test_scenario_gen.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/data_gen/scenario_gen.py backend/tests/data_gen/test_scenario_gen.py
git commit -m "feat: add scenario case selection for all six scenario types"
```

---

## Task 6: Scenario prompt batching

**Files:**
- Modify: `backend/scripts/data_gen/scenario_gen.py` (append; do not touch Task 5's functions)
- Test: `backend/tests/data_gen/test_scenario_gen.py` (append; do not touch Task 5's tests)

**Interfaces:**
- Consumes: `cases: list[dict]` from Task 5's `select_cases`, the prompt template at `docs/prompts/scenarios_gen_prompt.md`.
- Produces: `build_prompt_batches(cases: list[dict], batch_size: int = 10) -> list[str]`, `write_prompt_batches(batches: list[str], prompts_dir: pathlib.Path) -> list[pathlib.Path]`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/data_gen/test_scenario_gen.py`:
```python
import json

from data_gen.scenario_gen import build_prompt_batches, write_prompt_batches


def _sample_cases():
    return [
        {
            "case_id": f"sc-{i:04d}",
            "scenario_type": "clean_distinct",
            "customer": {"name": "Metro Plumbing", "contact": "Ravi Patel"},
            "entities": {"customer_id": "CUST-0001", "sku_ids": ["SKU-0001"]},
        }
        for i in range(1, 26)
    ]


def test_batches_split_by_batch_size():
    batches = build_prompt_batches(_sample_cases(), batch_size=10)
    assert len(batches) == 3  # 25 cases -> 10 + 10 + 5


def test_each_batch_embeds_valid_json_for_its_cases():
    cases = _sample_cases()[:10]
    batches = build_prompt_batches(cases, batch_size=10)
    start = batches[0].index("Cases:\n") + len("Cases:\n")
    embedded = json.loads(batches[0][start:])
    assert len(embedded) == 10
    assert embedded[0]["case_id"] == "sc-0001"


def test_write_prompt_batches_numbers_files_sequentially(tmp_path):
    batches = build_prompt_batches(_sample_cases(), batch_size=10)
    paths = write_prompt_batches(batches, tmp_path)
    assert [p.name for p in paths] == ["batch_001.md", "batch_002.md", "batch_003.md"]
    for path in paths:
        assert path.exists()


def test_write_prompt_batches_continues_numbering_on_second_call(tmp_path):
    write_prompt_batches(build_prompt_batches(_sample_cases()[:5], batch_size=10), tmp_path)
    second = write_prompt_batches(build_prompt_batches(_sample_cases()[5:10], batch_size=10), tmp_path)
    assert second[0].name == "batch_002.md"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/data_gen/test_scenario_gen.py -v -k prompt_batch`
Expected: FAIL with `ImportError: cannot import name 'build_prompt_batches'`

- [ ] **Step 3: Append the implementation**

Append to `backend/scripts/data_gen/scenario_gen.py` (add these imports to the top of the file alongside the existing `import random`):
```python
import json
import re
from pathlib import Path

PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parents[3] / "docs" / "prompts" / "scenarios_gen_prompt.md"


def _load_prompt_template() -> str:
    text = PROMPT_TEMPLATE_PATH.read_text()
    match = re.search(r"```\n(You write realistic.*?)\n```", text, re.DOTALL)
    if not match:
        raise ValueError(f"could not find prompt template block in {PROMPT_TEMPLATE_PATH}")
    return match.group(1)


def build_prompt_batches(cases: list[dict], batch_size: int = 10) -> list[str]:
    template = _load_prompt_template()
    batches = []
    for i in range(0, len(cases), batch_size):
        batch = cases[i : i + batch_size]
        batch_json = json.dumps(
            [
                {
                    "case_id": c["case_id"],
                    "scenario_type": c["scenario_type"],
                    "customer": c["customer"],
                    "entities": c["entities"],
                }
                for c in batch
            ],
            indent=2,
        )
        batches.append(template.replace("{{BATCH_CASES_JSON}}", batch_json))
    return batches


def write_prompt_batches(batches: list[str], prompts_dir: Path) -> list[Path]:
    prompts_dir.mkdir(parents=True, exist_ok=True)
    next_index = len(sorted(prompts_dir.glob("batch_*.md"))) + 1
    paths = []
    for offset, batch in enumerate(batches):
        path = prompts_dir / f"batch_{next_index + offset:03d}.md"
        path.write_text(batch)
        paths.append(path)
    return paths
```

Note: `PROMPT_TEMPLATE_PATH` walks up from `backend/scripts/data_gen/scenario_gen.py` three levels to the repo root (`data_gen` -> `scripts` -> `backend` -> repo root), then into `docs/prompts/`. Verify this resolves correctly in Step 4; if the actual repo layout differs, adjust the `parents[N]` index, not the rest of the function.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/data_gen/test_scenario_gen.py -v`
Expected: all passed (9 total so far). If `PROMPT_TEMPLATE_PATH` resolution fails, print `PROMPT_TEMPLATE_PATH` from a Python shell to confirm the parents index, then fix it.

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/data_gen/scenario_gen.py backend/tests/data_gen/test_scenario_gen.py
git commit -m "feat: add scenario prompt batching from the prompt template"
```

---

## Task 7: Scenario ingest

**Files:**
- Modify: `backend/scripts/data_gen/scenario_gen.py` (append; do not touch Tasks 5-6's functions)
- Test: `backend/tests/data_gen/test_scenario_gen.py` (append)

**Interfaces:**
- Consumes: `cases: list[dict]` from Task 5, response files under a `responses_dir`.
- Produces: `ingest_responses(cases: list[dict], responses_dir: pathlib.Path) -> tuple[list[dict], dict[str, str]]` (accepted cases with `email_text` added, and a `{case_id: reason}` dict for rejects), `rebatch_rejected(cases, rejected, prompts_dir, batch_size=10) -> list[pathlib.Path]`, `write_scenarios(accepted_cases, path, force=False) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/data_gen/test_scenario_gen.py`:
```python
from data_gen.scenario_gen import ingest_responses, rebatch_rejected, write_scenarios


def _three_cases():
    return [
        {
            "case_id": "sc-0001", "scenario_type": "clean_distinct",
            "customer": {"name": "A", "contact": "B"}, "entities": {"customer_id": "CUST-0001", "sku_ids": ["SKU-0001"]},
        },
        {
            "case_id": "sc-0002", "scenario_type": "duplicate_pair",
            "customer": {"name": "A", "contact": "B"}, "entities": {"customer_id": "CUST-0001", "sku_ids": ["SKU-0001"]},
        },
        {
            "case_id": "sc-0003", "scenario_type": "clean_distinct",
            "customer": {"name": "A", "contact": "B"}, "entities": {"customer_id": "CUST-0001", "sku_ids": ["SKU-0002"]},
        },
    ]


def test_accepts_a_valid_response(tmp_path):
    (tmp_path / "batch_001.json").write_text(json.dumps([
        {"case_id": "sc-0001", "email_text": "need a couple of these for the job, thanks"},
        {"case_id": "sc-0002", "email_text": "quote for the usual parts please"},
        {"case_id": "sc-0003", "email_text": "can you price this out for me"},
    ]))
    accepted, rejected = ingest_responses(_three_cases(), tmp_path)
    assert len(accepted) == 3
    assert rejected == {}


def test_rejects_empty_email_text(tmp_path):
    (tmp_path / "batch_001.json").write_text(json.dumps([
        {"case_id": "sc-0001", "email_text": "   "},
        {"case_id": "sc-0002", "email_text": "quote for the usual parts please"},
        {"case_id": "sc-0003", "email_text": "can you price this out for me"},
    ]))
    accepted, rejected = ingest_responses(_three_cases(), tmp_path)
    assert "sc-0001" in rejected
    assert rejected["sc-0001"] == "empty email_text"


def test_rejects_label_leaking_email(tmp_path):
    (tmp_path / "batch_001.json").write_text(json.dumps([
        {"case_id": "sc-0001", "email_text": "need a couple of these, thanks"},
        {"case_id": "sc-0002", "email_text": "this is a duplicate pair of my last request"},
        {"case_id": "sc-0003", "email_text": "can you price this out for me"},
    ]))
    accepted, rejected = ingest_responses(_three_cases(), tmp_path)
    assert rejected.get("sc-0002") == "email_text leaks scenario_type label"


def test_one_malformed_batch_does_not_block_other_batches(tmp_path):
    (tmp_path / "batch_001.json").write_text("{not valid json")
    (tmp_path / "batch_002.json").write_text(json.dumps([
        {"case_id": "sc-0002", "email_text": "quote for the usual parts please"},
        {"case_id": "sc-0003", "email_text": "can you price this out for me"},
    ]))
    accepted, rejected = ingest_responses(_three_cases(), tmp_path)
    accepted_ids = {c["case_id"] for c in accepted}
    assert accepted_ids == {"sc-0002", "sc-0003"}
    assert rejected.get("sc-0001") == "missing from any response file"


def test_missing_case_is_reported(tmp_path):
    (tmp_path / "batch_001.json").write_text(json.dumps([
        {"case_id": "sc-0001", "email_text": "need a couple of these, thanks"},
    ]))
    accepted, rejected = ingest_responses(_three_cases(), tmp_path)
    assert rejected["sc-0002"] == "missing from any response file"
    assert rejected["sc-0003"] == "missing from any response file"


def test_rebatch_rejected_writes_only_rejected_cases(tmp_path):
    cases = _three_cases()
    rejected = {"sc-0002": "missing from any response file"}
    paths = rebatch_rejected(cases, rejected, tmp_path / "prompts")
    content = paths[0].read_text()
    assert "sc-0002" in content
    assert "sc-0001" not in content


def test_write_scenarios_sorts_by_case_id(tmp_path):
    accepted = [
        {"case_id": "sc-0003", "email_text": "c"},
        {"case_id": "sc-0001", "email_text": "a"},
    ]
    out = tmp_path / "scenarios.json"
    write_scenarios(accepted, out)
    written = json.loads(out.read_text())
    assert [c["case_id"] for c in written] == ["sc-0001", "sc-0003"]


def test_write_scenarios_refuses_to_overwrite_without_force(tmp_path):
    out = tmp_path / "scenarios.json"
    write_scenarios([{"case_id": "sc-0001", "email_text": "a"}], out)
    try:
        write_scenarios([{"case_id": "sc-0002", "email_text": "b"}], out)
        assert False, "expected FileExistsError"
    except FileExistsError:
        pass
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/data_gen/test_scenario_gen.py -v -k ingest`
Expected: FAIL with `ImportError: cannot import name 'ingest_responses'`

- [ ] **Step 3: Append the implementation**

Append to `backend/scripts/data_gen/scenario_gen.py`:
```python
def ingest_responses(cases: list[dict], responses_dir: Path) -> tuple[list[dict], dict[str, str]]:
    cases_by_id = {c["case_id"]: c for c in cases}
    email_text_by_id: dict[str, str] = {}
    rejected: dict[str, str] = {}

    for response_path in sorted(responses_dir.glob("*.json")):
        try:
            entries = json.loads(response_path.read_text())
        except json.JSONDecodeError:
            continue  # every case_id in this batch stays unresolved; caught by the missing-case check below

        for entry in entries:
            case_id = entry.get("case_id")
            if case_id not in cases_by_id:
                continue
            email_text = entry.get("email_text", "")
            scenario_type = cases_by_id[case_id]["scenario_type"]
            label_words = scenario_type.split("_")
            if not email_text.strip():
                rejected[case_id] = "empty email_text"
            elif all(word in email_text.lower() for word in label_words):
                rejected[case_id] = "email_text leaks scenario_type label"
            else:
                email_text_by_id[case_id] = email_text

    accepted = []
    for case in cases:
        case_id = case["case_id"]
        if case_id in email_text_by_id:
            accepted.append({**case, "email_text": email_text_by_id[case_id]})
        elif case_id not in rejected:
            rejected[case_id] = "missing from any response file"

    return accepted, rejected


def rebatch_rejected(cases: list[dict], rejected: dict[str, str], prompts_dir: Path, batch_size: int = 10) -> list[Path]:
    rejected_cases = [c for c in cases if c["case_id"] in rejected]
    batches = build_prompt_batches(rejected_cases, batch_size)
    return write_prompt_batches(batches, prompts_dir)


def write_scenarios(accepted_cases: list[dict], path: Path, force: bool = False) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists; pass --force to overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(accepted_cases, key=lambda c: c["case_id"])
    path.write_text(json.dumps(ordered, indent=2))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/data_gen/test_scenario_gen.py -v`
Expected: all passed (17 total so far)

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/data_gen/scenario_gen.py backend/tests/data_gen/test_scenario_gen.py
git commit -m "feat: add scenario ingest with reject/re-batch and scenarios.json output"
```

---

## Task 8: validate.py checks

**Files:**
- Create: `backend/scripts/data_gen/validate.py`
- Test: `backend/tests/data_gen/test_validate.py`

**Interfaces:**
- Consumes: `catalog: list[dict]`, `customers: list[dict]`, `scenarios: list[dict]` (same shapes as Tasks 2/3/7's outputs), `SCENARIO_TYPES` from Task 5.
- Produces: `check_referential_integrity(catalog, customers, scenarios) -> list[str]`, `check_scenario_coverage(scenarios) -> list[str]` (both return a list of human-readable failure strings, empty list means passed).

- [ ] **Step 1: Write the failing tests**

`backend/tests/data_gen/test_validate.py`:
```python
from data_gen.validate import check_referential_integrity, check_scenario_coverage


def _valid_catalog():
    return [
        {"sku_id": "SKU-0001", "name": "a", "category": "X", "list_price": 1.0,
         "discontinued": False, "replaced_by": None, "requires": [], "in_stock": True},
        {"sku_id": "SKU-0002", "name": "b", "category": "X", "list_price": 2.0,
         "discontinued": True, "replaced_by": "SKU-0001", "requires": [], "in_stock": False},
    ]


def _valid_customers():
    return [{
        "customer_id": "CUST-0001", "name": "A", "account_tier": "Standard",
        "contacts": [{"name": "n", "email": "e", "phone": "p"}],
        "sites": [{"site_id": "SITE-0001", "address": "a", "zip": "1"}],
        "contracts": [{"contract_id": "CTR-0001", "discount_category": "X",
                       "covered_categories": ["X"], "effective_from": "2023-01-01", "effective_to": "2024-01-01"}],
    }]


def _valid_scenario(case_id="sc-0001", scenario_type="clean_distinct"):
    return {
        "case_id": case_id, "scenario_type": scenario_type,
        "customer": {"name": "A", "contact": "n"},
        "entities": {"customer_id": "CUST-0001", "sku_ids": ["SKU-0001"]},
        "email_text": "need this please",
    }


def test_referential_integrity_passes_for_valid_data():
    failures = check_referential_integrity(_valid_catalog(), _valid_customers(), [_valid_scenario()])
    assert failures == []


def test_referential_integrity_catches_missing_replaced_by_target():
    catalog = _valid_catalog()
    catalog[1]["replaced_by"] = "SKU-9999"
    failures = check_referential_integrity(catalog, _valid_customers(), [])
    assert any("SKU-9999" in f for f in failures)


def test_referential_integrity_catches_unknown_customer_in_scenario():
    scenario = _valid_scenario()
    scenario["entities"]["customer_id"] = "CUST-9999"
    failures = check_referential_integrity(_valid_catalog(), _valid_customers(), [scenario])
    assert any("CUST-9999" in f for f in failures)


def test_scenario_coverage_passes_for_exactly_ten_per_type():
    from data_gen.scenario_gen import SCENARIO_TYPES
    scenarios = [
        _valid_scenario(case_id=f"sc-{i:04d}", scenario_type=scenario_type)
        for scenario_type in SCENARIO_TYPES
        for i in range(1, 11)
    ]
    # renumber to avoid duplicate case_ids across types
    for i, s in enumerate(scenarios):
        s["case_id"] = f"sc-{i + 1:04d}"
    failures = check_scenario_coverage(scenarios)
    assert failures == []


def test_scenario_coverage_catches_wrong_count_for_a_type():
    from data_gen.scenario_gen import SCENARIO_TYPES
    scenarios = [
        _valid_scenario(case_id=f"sc-{i:04d}", scenario_type=scenario_type)
        for scenario_type in SCENARIO_TYPES
        for i in range(1, 11)
    ]
    for i, s in enumerate(scenarios):
        s["case_id"] = f"sc-{i + 1:04d}"
    scenarios.pop()  # now one type has only 9
    failures = check_scenario_coverage(scenarios)
    assert any("expected 10 cases" in f for f in failures)


def test_scenario_coverage_catches_duplicate_case_ids():
    scenarios = [_valid_scenario("sc-0001"), _valid_scenario("sc-0001")]
    failures = check_scenario_coverage(scenarios)
    assert any("duplicate case_ids" in f for f in failures)


def test_scenario_coverage_catches_empty_email_text():
    scenario = _valid_scenario()
    scenario["email_text"] = ""
    failures = check_scenario_coverage([scenario])
    assert any("missing email_text" in f for f in failures)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/data_gen/test_validate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'data_gen.validate'`

- [ ] **Step 3: Write the implementation**

`backend/scripts/data_gen/validate.py`:
```python
import argparse
import json
from pathlib import Path

from data_gen.scenario_gen import SCENARIO_TYPES


def check_referential_integrity(catalog: list[dict], customers: list[dict], scenarios: list[dict]) -> list[str]:
    failures = []
    sku_ids = {s["sku_id"] for s in catalog}

    for sku in catalog:
        if sku["replaced_by"] and sku["replaced_by"] not in sku_ids:
            failures.append(f"catalog: {sku['sku_id']}.replaced_by -> missing SKU {sku['replaced_by']}")
        for req in sku["requires"]:
            if req not in sku_ids:
                failures.append(f"catalog: {sku['sku_id']}.requires -> missing SKU {req}")

    customer_ids = {c["customer_id"] for c in customers}
    contract_ids = {ctr["contract_id"] for c in customers for ctr in c["contracts"]}

    for case in scenarios:
        entities = case["entities"]
        customer_id = entities.get("customer_id")
        if customer_id and customer_id not in customer_ids:
            failures.append(f"scenario {case['case_id']}: unknown customer_id {customer_id}")

        contract_id = entities.get("contract_id")
        if contract_id and contract_id not in contract_ids:
            failures.append(f"scenario {case['case_id']}: unknown contract_id {contract_id}")

        referenced_skus = entities.get("sku_ids", [])
        if "sku_id" in entities:
            referenced_skus = referenced_skus + [entities["sku_id"]]
        for sku_id in referenced_skus:
            if sku_id not in sku_ids:
                failures.append(f"scenario {case['case_id']}: unknown sku_id {sku_id}")

    return failures


def check_scenario_coverage(scenarios: list[dict]) -> list[str]:
    failures = []

    case_ids = [c["case_id"] for c in scenarios]
    seen = set()
    duplicates = sorted({c for c in case_ids if c in seen or seen.add(c)})
    if duplicates:
        failures.append(f"duplicate case_ids: {duplicates}")

    counts: dict[str, int] = {}
    for case in scenarios:
        counts[case["scenario_type"]] = counts.get(case["scenario_type"], 0) + 1
    for scenario_type in SCENARIO_TYPES:
        found = counts.get(scenario_type, 0)
        if found != 10:
            failures.append(f"scenario_type {scenario_type}: expected 10 cases, found {found}")

    for case in scenarios:
        if not case.get("email_text", "").strip():
            failures.append(f"scenario {case['case_id']}: missing email_text")

    if len(scenarios) != 60:
        failures.append(f"expected 60 total scenarios, found {len(scenarios)}")

    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the generated Phase 1 dataset")
    parser.add_argument("--catalog", type=Path, default=Path("data/catalog.json"))
    parser.add_argument("--customers", type=Path, default=Path("data/customers.json"))
    parser.add_argument("--scenarios", type=Path, default=Path("data/scenarios.json"))
    args = parser.parse_args()

    catalog = json.loads(args.catalog.read_text())
    customers = json.loads(args.customers.read_text())
    scenarios = json.loads(args.scenarios.read_text())

    failures = check_referential_integrity(catalog, customers, scenarios) + check_scenario_coverage(scenarios)

    if failures:
        print("VALIDATION FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("all checks passed")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/data_gen/test_validate.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/scripts/data_gen/validate.py backend/tests/data_gen/test_validate.py
git commit -m "feat: add validate.py referential integrity and coverage checks"
```

---

## Task 9: Pipeline runner, determinism check, and gitignore

**Files:**
- Create: `backend/scripts/data_gen/run_pipeline.py`
- Modify: `backend/scripts/data_gen/validate.py` (add `check_determinism`)
- Modify: `.gitignore`
- Test: `backend/tests/data_gen/test_run_pipeline.py`, additions to `backend/tests/data_gen/test_validate.py`

**Interfaces:**
- Consumes: `generate_catalog`, `generate_customers`, `build_nodes`, `build_edges`, `select_cases` from Tasks 2-5; `write_catalog`, `write_customers`, `write_graph` from Tasks 2-4.
- Produces: `check_determinism(regenerate_fn) -> list[str]` in `validate.py` (takes a zero-arg callable returning `(catalog, customers)`, calls it twice, compares structurally), a `run_pipeline.py` CLI that runs catalog -> customers -> graph export in order, checking all output paths exist upfront before writing any of them.

- [ ] **Step 1: Write the failing test for `check_determinism`**

Append to `backend/tests/data_gen/test_validate.py`:
```python
from data_gen.validate import check_determinism


def test_check_determinism_passes_for_a_pure_deterministic_function():
    def regenerate():
        return ({"a": 1}, [{"b": 2}])
    assert check_determinism(regenerate) == []


def test_check_determinism_catches_a_non_deterministic_function():
    calls = {"n": 0}

    def regenerate():
        calls["n"] += 1
        return ({"a": calls["n"]}, [{"b": 2}])

    failures = check_determinism(regenerate)
    assert any("catalog.json" in f for f in failures)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/data_gen/test_validate.py -v -k determinism`
Expected: FAIL with `ImportError: cannot import name 'check_determinism'`

- [ ] **Step 3: Append `check_determinism` to `validate.py`**

Append to `backend/scripts/data_gen/validate.py` (above `main()`):
```python
def check_determinism(regenerate_fn) -> list[str]:
    """regenerate_fn() returns (catalog, customers) freshly built from config; called twice and compared
    structurally (Python == on the loaded lists/dicts), not byte-for-byte, since JSON key order is not
    semantically meaningful and shouldn't fail a determinism check on its own."""
    first_catalog, first_customers = regenerate_fn()
    second_catalog, second_customers = regenerate_fn()
    failures = []
    if first_catalog != second_catalog:
        failures.append("catalog.json is not deterministic across two runs with the same seed")
    if first_customers != second_customers:
        failures.append("customers.json is not deterministic across two runs with the same seed")
    return failures
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/data_gen/test_validate.py -v`
Expected: all passed (9 total)

- [ ] **Step 5: Write the failing test for the pipeline's overwrite guard**

`backend/tests/data_gen/test_run_pipeline.py`:
```python
from data_gen.run_pipeline import check_output_paths_are_clear


def test_check_output_paths_are_clear_passes_when_nothing_exists(tmp_path):
    paths = [tmp_path / "catalog.json", tmp_path / "customers.json"]
    check_output_paths_are_clear(paths, force=False)  # must not raise


def test_check_output_paths_are_clear_fails_if_any_path_exists(tmp_path):
    existing = tmp_path / "catalog.json"
    existing.write_text("{}")
    paths = [existing, tmp_path / "customers.json"]
    try:
        check_output_paths_are_clear(paths, force=False)
        assert False, "expected FileExistsError"
    except FileExistsError as e:
        assert "catalog.json" in str(e)


def test_check_output_paths_are_clear_allows_force(tmp_path):
    existing = tmp_path / "catalog.json"
    existing.write_text("{}")
    paths = [existing, tmp_path / "customers.json"]
    check_output_paths_are_clear(paths, force=True)  # must not raise
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/data_gen/test_run_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'data_gen.run_pipeline'`

- [ ] **Step 7: Write `run_pipeline.py`**

`backend/scripts/data_gen/run_pipeline.py`:
```python
import argparse
from pathlib import Path

from data_gen.catalog_gen import generate_catalog, write_catalog
from data_gen.config import DEFAULT
from data_gen.customer_gen import generate_customers, write_customers
from data_gen.graph_export import build_edges, build_nodes, write_graph


def check_output_paths_are_clear(paths: list[Path], force: bool) -> None:
    if force:
        return
    existing = [p for p in paths if p.exists()]
    if existing:
        names = ", ".join(str(p) for p in existing)
        raise FileExistsError(f"output already exists: {names}; pass --force to overwrite")


def run(data_dir: Path, force: bool = False) -> None:
    catalog_path = data_dir / "catalog.json"
    customers_path = data_dir / "customers.json"
    nodes_path = data_dir / "graph" / "nodes.json"
    edges_path = data_dir / "graph" / "edges.json"

    check_output_paths_are_clear([catalog_path, customers_path, nodes_path, edges_path], force)

    catalog = generate_catalog(DEFAULT)
    write_catalog(catalog, catalog_path, force=force)

    customers = generate_customers(DEFAULT, catalog)
    write_customers(customers, customers_path, force=force)

    nodes = build_nodes(catalog, customers)
    edges = build_edges(catalog, customers)
    write_graph(nodes, edges, nodes_path, edges_path, force=force)

    print(f"wrote {len(catalog)} SKUs, {len(customers)} customers, {len(nodes)} nodes, {len(edges)} edges to {data_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the full Phase 1 data generation pipeline (catalog, customers, graph)")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    run(args.data_dir, force=args.force)


if __name__ == "__main__":
    main()
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/data_gen/test_run_pipeline.py -v`
Expected: 3 passed

- [ ] **Step 9: Add an end-to-end determinism test**

Append to `backend/tests/data_gen/test_run_pipeline.py`:
```python
from data_gen.catalog_gen import generate_catalog
from data_gen.config import DEFAULT
from data_gen.customer_gen import generate_customers
from data_gen.validate import check_determinism


def test_full_pipeline_is_deterministic():
    def regenerate():
        catalog = generate_catalog(DEFAULT)
        customers = generate_customers(DEFAULT, catalog)
        return catalog, customers

    assert check_determinism(regenerate) == []
```

Run: `cd backend && uv run pytest tests/data_gen/test_run_pipeline.py -v`
Expected: 4 passed

- [ ] **Step 10: Add `backend/data/` to `.gitignore`**

Create or modify `.gitignore` at repo root, adding:
```
backend/data/
```

(This ignores generated output entirely for now; the spec's checked-in sample file is explicitly deferred to whenever Phase 2 needs it, per the spec's Open Items section, so no sample is carved out here.)

- [ ] **Step 11: Run the full test suite once**

Run: `cd backend && uv run pytest -v`
Expected: all tests across every module pass (config, catalog_gen, customer_gen, graph_export, scenario_gen, validate, run_pipeline).

- [ ] **Step 12: Run the pipeline for real and validate it**

Run:
```bash
cd backend
uv run python scripts/data_gen/run_pipeline.py --data-dir data
uv run python -m data_gen.scenario_gen  # not a CLI yet; see note below
```

Note: `scenario_gen.py`'s case-selection/prompt/ingest steps have no combined CLI in this plan, since the workflow is inherently interactive (case selection runs, then a human pastes prompts into a chat platform, then ingest runs against whatever came back). Wire up whatever thin CLI entry points are convenient for that manual loop; the functions in Tasks 5-7 are already fully tested and don't require a specific CLI shape to satisfy this plan's "Done when" criteria.

Then run: `cd backend && uv run python scripts/data_gen/validate.py --catalog data/catalog.json --customers data/customers.json --scenarios data/scenarios.json` (this last step will fail until `scenarios.json` exists from an actual case-selection + manual prompt/ingest pass; that manual pass is outside this plan's automated steps and is the "spot-check 10-15 emails" done-when criterion from the spec).

- [ ] **Step 13: Commit**

```bash
git add backend/scripts/data_gen/run_pipeline.py backend/scripts/data_gen/validate.py backend/tests/data_gen/test_run_pipeline.py backend/tests/data_gen/test_validate.py .gitignore
git commit -m "feat: add pipeline runner, determinism check, and data gitignore"
```

---

## Self-Review Notes

**Spec coverage:** `config.py` (Task 1), `catalog_gen.py` (Task 2), `customer_gen.py` (Task 3), `graph_export.py` including the added `HAS_CONTRACT` edge (Task 4), `scenario_gen.py` all three steps (Tasks 5-7), `validate.py` all three check families (Tasks 8-9). Repository layout matches the spec except tests live under `backend/tests/data_gen/` rather than being unlisted; the spec's layout section only describes `backend/scripts/` and `backend/data/`, not the test tree, so this doesn't conflict with it.

**Placeholder scan:** none; every step has real code, no "TBD" or "handle edge cases" left unstated.

**Type consistency:** `Config` fields (`seed`, `sku_count`, `customer_count`, `scenarios_per_type`) are used identically in Tasks 1 through 9. `case_id`, `scenario_type`, `customer`, `entities` are consistent across Tasks 5-8. `sku_id`, `replaced_by`, `requires`, `discontinued` are consistent across Tasks 2, 4, 5, 8.

**Open items carried from the spec, deliberately not resolved here:** the checked-in sample file for later phases' tests (spec defers this to whenever Phase 2 needs it; Task 9 Step 10 reaffirms the deferral rather than inventing a format now).
