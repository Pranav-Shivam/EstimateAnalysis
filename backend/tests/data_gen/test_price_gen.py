import json
from pathlib import Path

import pytest

from data_gen.config import DEFAULT
from data_gen.price_gen import DISCOUNT_CHOICES, generate_pricing, write_pricing

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _catalog(n=40):
    catalog = [
        {"sku_id": f"SKU-{i:04d}", "name": f"s{i}", "category": "C", "list_price": 100.0 + i,
         "discontinued": False, "replaced_by": None, "requires": [], "in_stock": True}
        for i in range(1, n + 1)
    ]
    catalog[0]["discontinued"] = True
    catalog[0]["replaced_by"] = "SKU-0002"
    catalog[2]["requires"] = ["SKU-0004"]
    return catalog


def _customers():
    return [{"customer_id": "CUST-0001", "name": "A", "account_tier": "Standard", "contacts": [], "sites": [],
             "contracts": [{"contract_id": "CTR-0001", "discount_category": "C", "covered_categories": ["C"],
                            "effective_from": "2023-01-01", "effective_to": "2025-01-01"}]}]


def _cases():
    return [
        {"case_id": "sc-1", "scenario_type": "discontinued_swap", "customer": {}, "entities": {"sku_id": "SKU-0001"}},
        {"case_id": "sc-2", "scenario_type": "missing_required_part", "customer": {}, "entities": {"sku_id": "SKU-0003"}},
        {"case_id": "sc-3", "scenario_type": "clean_distinct", "customer": {}, "entities": {"sku_ids": ["SKU-0010"]}},
    ]


def test_generation_is_deterministic():
    first = generate_pricing(DEFAULT, _catalog(), _customers(), _cases())
    second = generate_pricing(DEFAULT, _catalog(), _customers(), _cases())

    assert first == second


def test_every_contract_gets_a_discount_from_the_allowed_set():
    pricing = generate_pricing(DEFAULT, _catalog(), _customers(), _cases())

    assert set(pricing["discounts"]) == {"CTR-0001"}
    assert pricing["discounts"]["CTR-0001"] in DISCOUNT_CHOICES


def test_gap_skus_are_about_ten_percent_and_have_no_history():
    pricing = generate_pricing(DEFAULT, _catalog(40), _customers(), _cases())
    gap = set(pricing["gap_sku_ids"])

    assert len(gap) == 4
    assert gap.isdisjoint({row["sku_id"] for row in pricing["history"]})


def test_scenario_skus_replacements_and_required_parts_are_never_gaps():
    pricing = generate_pricing(DEFAULT, _catalog(), _customers(), _cases())
    protected = {"SKU-0001", "SKU-0002", "SKU-0003", "SKU-0004", "SKU-0010"}

    assert protected.isdisjoint(pricing["gap_sku_ids"])


def test_every_priced_sku_has_history_within_realized_range():
    catalog = _catalog()
    pricing = generate_pricing(DEFAULT, catalog, _customers(), _cases())
    list_price = {s["sku_id"]: s["list_price"] for s in catalog}
    gap = set(pricing["gap_sku_ids"])
    with_history = {row["sku_id"] for row in pricing["history"]}

    assert with_history == set(list_price) - gap
    for row in pricing["history"]:
        assert 0.85 * list_price[row["sku_id"]] - 0.01 <= row["unit_price"] <= list_price[row["sku_id"]]


def test_write_pricing_refuses_to_overwrite_without_force(tmp_path):
    path = tmp_path / "pricing.json"
    write_pricing({"discounts": {}, "gap_sku_ids": [], "history": []}, path)

    with pytest.raises(FileExistsError):
        write_pricing({"discounts": {}, "gap_sku_ids": [], "history": []}, path)

    write_pricing({"discounts": {"CTR-1": 5.0}, "gap_sku_ids": [], "history": []}, path, force=True)
    assert json.loads(path.read_text(encoding="utf-8"))["discounts"] == {"CTR-1": 5.0}


def test_real_dataset_gap_never_touches_scenario_skus():
    catalog = json.loads((DATA_DIR / "catalog.json").read_text(encoding="utf-8"))
    customers = json.loads((DATA_DIR / "customers.json").read_text(encoding="utf-8"))
    cases = json.loads((DATA_DIR / "scenario_cases.json").read_text(encoding="utf-8"))

    pricing = generate_pricing(DEFAULT, catalog, customers, cases)

    referenced = set()
    for case in cases:
        entities = case["entities"]
        referenced.update(entities.get("sku_ids", []))
        if "sku_id" in entities:
            referenced.add(entities["sku_id"])
    assert referenced.isdisjoint(pricing["gap_sku_ids"])
    assert len(pricing["discounts"]) == len(customers)
