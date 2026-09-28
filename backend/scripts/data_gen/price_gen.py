import argparse
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_gen.config import DEFAULT, Config, validate_config

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

PRICING_SEED_OFFSET = 3
DISCOUNT_CHOICES = [5.0, 8.0, 10.0, 12.0, 15.0]
GAP_FRACTION = 0.10
HISTORY_START = date(2023, 1, 1)
HISTORY_SPAN_DAYS = 600
REALIZED_RATIO_RANGE = (0.85, 1.0)


def _protected_sku_ids(catalog: list[dict], scenario_cases: list[dict]) -> set[str]:
    """SKUs the planted scenarios depend on must stay priceable, so they are never price-book gaps."""
    by_id = {sku["sku_id"]: sku for sku in catalog}
    referenced: set[str] = set()
    for case in scenario_cases:
        entities = case["entities"]
        # Only the sku_id / sku_ids keys carry SKU ids; other entity keys are not SKUs.
        referenced.update(entities.get("sku_ids", []))
        if "sku_id" in entities:
            referenced.add(entities["sku_id"])

    protected = set(referenced)
    for sku_id in referenced:
        sku = by_id[sku_id]
        protected.update(sku["requires"])
        if sku["replaced_by"]:
            replacement = by_id[sku["replaced_by"]]
            protected.add(replacement["sku_id"])
            protected.update(replacement["requires"])
    return protected


def generate_pricing(config: Config, catalog: list[dict], customers: list[dict], scenario_cases: list[dict]) -> dict:
    validate_config(config)
    rng = random.Random(config.seed + PRICING_SEED_OFFSET)

    contract_ids = sorted(c["contract_id"] for customer in customers for c in customer["contracts"])
    discounts = {contract_id: rng.choice(DISCOUNT_CHOICES) for contract_id in contract_ids}

    protected = _protected_sku_ids(catalog, scenario_cases)
    candidates = sorted(sku["sku_id"] for sku in catalog if sku["sku_id"] not in protected)
    gap_count = min(round(len(catalog) * GAP_FRACTION), len(candidates))
    gap_sku_ids = sorted(rng.sample(candidates, gap_count))
    gap = set(gap_sku_ids)

    history = []
    for sku in catalog:
        if sku["sku_id"] in gap:
            continue
        for _ in range(rng.randint(1, 3)):
            quoted_on = HISTORY_START + timedelta(days=rng.randrange(HISTORY_SPAN_DAYS))
            history.append({
                "sku_id": sku["sku_id"],
                "unit_price": round(sku["list_price"] * rng.uniform(*REALIZED_RATIO_RANGE), 2),
                "quoted_on": quoted_on.isoformat(),
            })

    return {"discounts": discounts, "gap_sku_ids": gap_sku_ids, "history": history}


def write_pricing(pricing: dict, path: Path, force: bool = False) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists; pass --force to overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pricing, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate contract discounts, price-book gaps, and price history")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    catalog = json.loads((args.data_dir / "catalog.json").read_text(encoding="utf-8"))
    customers = json.loads((args.data_dir / "customers.json").read_text(encoding="utf-8"))
    cases = json.loads((args.data_dir / "scenario_cases.json").read_text(encoding="utf-8"))

    pricing = generate_pricing(DEFAULT, catalog, customers, cases)
    write_pricing(pricing, args.data_dir / "pricing.json", force=args.force)
    print(
        f"wrote {len(pricing['discounts'])} contract discounts, {len(pricing['gap_sku_ids'])} gap SKUs, "
        f"{len(pricing['history'])} history rows to {args.data_dir / 'pricing.json'}"
    )


if __name__ == "__main__":
    main()
