import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.reference_data.models import Contract, Sku
from app.reference_data.repository import (
    replace_price_history, set_sku_family, upsert_contact, upsert_contract, upsert_customer, upsert_family,
    upsert_project, upsert_requirement, upsert_site, upsert_sku,
)
from core.config.settings import Settings
from core.db.session import make_engine, make_session_factory

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def load_catalog(session, catalog: list[dict]) -> None:
    for sku in catalog:
        upsert_sku(
            session, sku_id=sku["sku_id"], name=sku["name"], category=sku["category"],
            list_price=sku["list_price"], discontinued=sku["discontinued"], replaced_by=None,
            in_stock=sku["in_stock"],
        )
    session.flush()
    for sku in catalog:
        if sku["discontinued"] and sku["replaced_by"]:
            row = session.get(Sku, sku["sku_id"])
            row.replaced_by = sku["replaced_by"]
    session.flush()
    for sku in catalog:
        for required_sku_id in sku["requires"]:
            upsert_requirement(session, sku_id=sku["sku_id"], required_sku_id=required_sku_id)


def load_customers(session, customers: list[dict]) -> None:
    for customer in customers:
        upsert_customer(session, customer_id=customer["customer_id"], name=customer["name"], account_tier=customer["account_tier"])
        # Sessions run with autoflush off, and Contact has no relationship() to Customer for the ORM to infer
        # insert order from, so the customer row must be flushed before contacts referencing it are added.
        session.flush()
        for number, contact in enumerate(customer["contacts"], start=1):
            upsert_contact(
                session, contact_id=f"{customer['customer_id']}-C{number}", customer_id=customer["customer_id"],
                name=contact["name"], email=contact["email"], phone=contact["phone"],
            )
        for site in customer["sites"]:
            upsert_site(session, site_id=site["site_id"], customer_id=customer["customer_id"], address=site["address"], zip_code=site["zip"])
        for contract in customer["contracts"]:
            upsert_contract(
                session, contract_id=contract["contract_id"], customer_id=customer["customer_id"],
                discount_category=contract["discount_category"], covered_categories=contract["covered_categories"],
                effective_from=date.fromisoformat(contract["effective_from"]),
                effective_to=date.fromisoformat(contract["effective_to"]),
            )


def load_pricing(session, pricing: dict) -> None:
    # Sessions run with autoflush off, so contracts and SKUs upserted earlier are invisible to session.get until flushed.
    session.flush()
    for contract_id, discount_pct in pricing["discounts"].items():
        contract = session.get(Contract, contract_id)
        if contract is None:
            raise ValueError(f"pricing references unknown contract {contract_id}")
        contract.discount_pct = discount_pct

    for sku_id in pricing["gap_sku_ids"]:
        sku = session.get(Sku, sku_id)
        if sku is None:
            raise ValueError(f"pricing references unknown SKU {sku_id}")
        sku.list_price = None

    history_by_sku: dict[str, list[tuple[float, date]]] = {}
    for row in pricing["history"]:
        history_by_sku.setdefault(row["sku_id"], []).append((row["unit_price"], date.fromisoformat(row["quoted_on"])))
    for sku_id, rows in history_by_sku.items():
        if session.get(Sku, sku_id) is None:
            raise ValueError(f"pricing references unknown SKU {sku_id}")
        replace_price_history(session, sku_id, rows)


def load_structure(session, structure: dict) -> None:
    # Sessions run with autoflush off: SKUs, customers and sites loaded earlier must be flushed to be linked.
    session.flush()
    for family in structure["families"]:
        upsert_family(session, family_id=family["family_id"], name=family["name"], category=family["category"])
    session.flush()
    for sku_id, family_id in structure["sku_family"].items():
        set_sku_family(session, sku_id, family_id)
    for project in structure["projects"]:
        upsert_project(
            session, project_id=project["project_id"], customer_id=project["customer_id"],
            site_id=project["site_id"], name=project["name"],
        )


def load_all(session, data_dir: Path = DATA_DIR) -> str:
    catalog = json.loads((data_dir / "catalog.json").read_text(encoding="utf-8"))
    customers = json.loads((data_dir / "customers.json").read_text(encoding="utf-8"))
    pricing = json.loads((data_dir / "pricing.json").read_text(encoding="utf-8"))
    structure = json.loads((data_dir / "structure.json").read_text(encoding="utf-8"))

    load_catalog(session, catalog)
    load_customers(session, customers)
    load_pricing(session, pricing)
    load_structure(session, structure)
    return (
        f"loaded {len(catalog)} SKUs, {len(customers)} customers, "
        f"{len(pricing['history'])} price history rows, "
        f"{len(structure['families'])} families, {len(structure['projects'])} projects"
    )


def run(data_dir: Path = DATA_DIR) -> None:
    settings = Settings()
    engine = make_engine(settings.database_url)
    session = make_session_factory(engine)()
    try:
        summary = load_all(session, data_dir)
        session.commit()
        redacted_url = re.sub(r"//([^:/@]+):[^@]*@", r"//\1:***@", settings.database_url)
        print(f"{summary} into {redacted_url}")
    finally:
        session.close()


if __name__ == "__main__":
    run()
