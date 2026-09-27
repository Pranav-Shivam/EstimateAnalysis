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
