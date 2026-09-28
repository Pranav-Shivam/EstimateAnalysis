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


def test_family_name_prefers_the_longest_matching_size_suffix(monkeypatch):
    # "Big 2 in" contains " 2 in" as its own tail, so a name ending in "Big 2 in" also
    # ends in "2 in": shortest-first would wrongly peel off only "2 in" and leave "Big"
    # stuck to the family name. No size pair in the real SIZES lists collides like this
    # today, so this is exercised with a synthetic category instead.
    import data_gen.structure_gen as structure_gen

    monkeypatch.setattr(structure_gen, "SIZES", {"Cat-COLLIDE": ["2 in", "Big 2 in"]})

    sku = _sku("SKU-X", "Widget Big 2 in", "Cat-COLLIDE")

    assert structure_gen.family_name(sku) == "Widget"


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
