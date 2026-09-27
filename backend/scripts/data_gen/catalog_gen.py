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
    "Plumbing-Fittings": ["1/2 in", "3/4 in", "1 in", "1-1/4 in", "1-1/2 in", "2 in", "2-1/2 in"],
    "Plumbing-Fixtures": ["Standard", "Compact", "Wall-Mount", "Deck-Mount"],
    "HVAC-Parts": ["Small", "Medium", "Large", "16x20", "20x25"],
    "HVAC-Equipment": ["2 Ton", "3 Ton", "4 Ton", "5 Ton"],
    "Electrical-Supplies": ["15A", "20A", "30A", "50A", "60A", "100A"],
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
