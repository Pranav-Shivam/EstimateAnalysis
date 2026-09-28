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
