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
    # set.add() returns None (falsy), so condition is True only on re-occurrence: c in seen (second+ time) or None
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
