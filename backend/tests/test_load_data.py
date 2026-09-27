from datetime import date

from load_data import load_catalog, load_customers
from app.reference_data.models import Contract, Sku
from app.reference_data.repository import all_customers, all_skus


def test_load_catalog_resolves_replaced_by_after_insert(db_session):
    catalog = [
        {"sku_id": "SKU-A", "name": "Old Part", "category": "C", "list_price": 5.0,
         "discontinued": True, "replaced_by": "SKU-B", "in_stock": False, "requires": []},
        {"sku_id": "SKU-B", "name": "New Part", "category": "C", "list_price": 6.0,
         "discontinued": False, "replaced_by": None, "in_stock": True, "requires": []},
    ]
    load_catalog(db_session, catalog)
    db_session.flush()

    skus_by_id = {s.sku_id: s for s in all_skus(db_session) if s.sku_id in ("SKU-A", "SKU-B")}
    assert set(skus_by_id) == {"SKU-A", "SKU-B"}
    assert db_session.get(Sku, "SKU-A").replaced_by == "SKU-B"


def test_load_customers_inserts_sites_and_contracts(db_session):
    customers = [{
        "customer_id": "CUST-T9", "name": "Test Co", "account_tier": "Standard",
        "contacts": [], "sites": [{"site_id": "SITE-T9", "address": "1 Main St", "zip": "00000"}],
        "contracts": [{
            "contract_id": "CTR-T9", "discount_category": "A", "covered_categories": ["A"],
            "effective_from": "2024-01-01", "effective_to": "2025-01-01",
        }],
    }]
    load_customers(db_session, customers)
    db_session.flush()

    assert any(c.customer_id == "CUST-T9" for c in all_customers(db_session))
    contract = db_session.get(Contract, "CTR-T9")
    assert contract.effective_from == date(2024, 1, 1)
