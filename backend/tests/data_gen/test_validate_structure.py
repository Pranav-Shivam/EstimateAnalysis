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
