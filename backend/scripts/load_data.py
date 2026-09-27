import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.reference_data.models import Sku
from app.reference_data.repository import upsert_contract, upsert_customer, upsert_site, upsert_sku
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


def load_customers(session, customers: list[dict]) -> None:
    for customer in customers:
        upsert_customer(session, customer_id=customer["customer_id"], name=customer["name"], account_tier=customer["account_tier"])
        for site in customer["sites"]:
            upsert_site(session, site_id=site["site_id"], customer_id=customer["customer_id"], address=site["address"], zip_code=site["zip"])
        for contract in customer["contracts"]:
            upsert_contract(
                session, contract_id=contract["contract_id"], customer_id=customer["customer_id"],
                discount_category=contract["discount_category"], covered_categories=contract["covered_categories"],
                effective_from=date.fromisoformat(contract["effective_from"]),
                effective_to=date.fromisoformat(contract["effective_to"]),
            )


def run(data_dir: Path = DATA_DIR) -> None:
    catalog = json.loads((data_dir / "catalog.json").read_text(encoding="utf-8"))
    customers = json.loads((data_dir / "customers.json").read_text(encoding="utf-8"))

    settings = Settings()
    engine = make_engine(settings.database_url)
    session = make_session_factory(engine)()
    try:
        load_catalog(session, catalog)
        load_customers(session, customers)
        session.commit()
        redacted_url = re.sub(r"//([^:/@]+):[^@]*@", r"//\1:***@", settings.database_url)
        print(f"loaded {len(catalog)} SKUs, {len(customers)} customers into {redacted_url}")
    finally:
        session.close()


if __name__ == "__main__":
    run()
