import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_gen.scenario_gen import SCENARIO_TYPES

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


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
    site_ids = {site["site_id"] for c in customers for site in c["sites"]}
    contract_ids_by_customer = {
        c["customer_id"]: {ctr["contract_id"] for ctr in c["contracts"]} for c in customers
    }

    for case in scenarios:
        entities = case["entities"]
        customer_id = entities.get("customer_id")
        if customer_id and customer_id not in customer_ids:
            failures.append(f"scenario {case['case_id']}: unknown customer_id {customer_id}")

        site_id = entities.get("site_id")
        if site_id and site_id not in site_ids:
            failures.append(f"scenario {case['case_id']}: unknown site_id {site_id}")

        contract_id = entities.get("contract_id")
        if contract_id:
            customer_contract_ids = contract_ids_by_customer.get(customer_id, set())
            if contract_id not in customer_contract_ids:
                failures.append(
                    f"scenario {case['case_id']}: contract_id {contract_id} does not belong to customer_id {customer_id}"
                )

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


def check_pricing(catalog: list[dict], customers: list[dict], pricing: dict) -> list[str]:
    failures = []
    sku_ids = {s["sku_id"] for s in catalog}
    contract_ids = {c["contract_id"] for customer in customers for c in customer["contracts"]}
    gap = set(pricing["gap_sku_ids"])
    history_sku_ids = {row["sku_id"] for row in pricing["history"]}

    for contract_id in sorted(contract_ids - set(pricing["discounts"])):
        failures.append(f"pricing: contract {contract_id} has no discount")
    for contract_id in sorted(set(pricing["discounts"]) - contract_ids):
        failures.append(f"pricing: discount for unknown contract {contract_id}")
    for sku_id in sorted(gap - sku_ids):
        failures.append(f"pricing: gap SKU {sku_id} is not in the catalog")
    for sku_id in sorted(history_sku_ids - sku_ids):
        failures.append(f"pricing: history references unknown SKU {sku_id}")
    for sku_id in sorted(gap & history_sku_ids):
        failures.append(f"pricing: gap SKU {sku_id} must not have price history")
    for sku_id in sorted(sku_ids - gap - history_sku_ids):
        failures.append(f"pricing: priced SKU {sku_id} has no price history")
    for row in pricing["history"]:
        if row["unit_price"] <= 0:
            failures.append(f"pricing: non-positive history price for {row['sku_id']}")

    return failures


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
    parser.add_argument("--catalog", type=Path, default=DATA_DIR / "catalog.json")
    parser.add_argument("--customers", type=Path, default=DATA_DIR / "customers.json")
    parser.add_argument("--scenarios", type=Path, default=DATA_DIR / "scenarios.json")
    parser.add_argument("--pricing", type=Path, default=DATA_DIR / "pricing.json")
    parser.add_argument("--structure", type=Path, default=DATA_DIR / "structure.json")
    args = parser.parse_args()

    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    customers = json.loads(args.customers.read_text(encoding="utf-8"))
    scenarios = json.loads(args.scenarios.read_text(encoding="utf-8"))
    pricing = json.loads(args.pricing.read_text(encoding="utf-8"))
    structure = json.loads(args.structure.read_text(encoding="utf-8"))

    failures = (
        check_referential_integrity(catalog, customers, scenarios)
        + check_scenario_coverage(scenarios)
        + check_pricing(catalog, customers, pricing)
        + check_structure(catalog, customers, structure)
    )

    if failures:
        print("VALIDATION FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("all checks passed")


if __name__ == "__main__":
    main()
