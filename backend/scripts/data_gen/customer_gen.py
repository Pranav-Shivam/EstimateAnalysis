import argparse
import itertools
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_gen.config import DEFAULT, Config, validate_config

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

ACCOUNT_TIERS = ["Standard", "Preferred", "Enterprise"]

COMPANY_WORDS = [
    "Metro", "Summit", "Northgate", "Riverside", "Union", "Lakeview", "Cascade",
    "Ironclad", "Bluewater", "Highline", "Coastal", "Prairie", "Redstone", "Harbor",
    "Peak", "Elite", "Crown", "Apex", "Sterling", "Precision", "Advanced", "Total",
    "Zenith", "Titan", "Vanguard", "Nexus",
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
    path.write_text(json.dumps(customers, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the synthetic customer roster")
    parser.add_argument("--catalog", type=Path, default=DATA_DIR / "catalog.json")
    parser.add_argument("--out", type=Path, default=DATA_DIR / "customers.json")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    customers = generate_customers(DEFAULT, catalog)
    write_customers(customers, args.out, force=args.force)
    print(f"wrote {len(customers)} customers to {args.out}")


if __name__ == "__main__":
    main()
