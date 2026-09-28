from datetime import date

import pytest

from load_data import load_catalog, load_customers, load_pricing
from app.reference_data.models import Contract, Sku
from app.reference_data.repository import (
    all_customers, all_skus, get_contract, get_sku, latest_realized_price, required_sku_ids,
)


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


def _pricing_catalog():
    return [
        {"sku_id": "SKU-LP1", "name": "A", "category": "Cat-LP", "list_price": 10.0,
         "discontinued": False, "replaced_by": None, "in_stock": True, "requires": ["SKU-LP2"]},
        {"sku_id": "SKU-LP2", "name": "B", "category": "Cat-LP", "list_price": 20.0,
         "discontinued": False, "replaced_by": None, "in_stock": True, "requires": []},
        {"sku_id": "SKU-LP3", "name": "C", "category": "Cat-LP", "list_price": 30.0,
         "discontinued": False, "replaced_by": None, "in_stock": True, "requires": []},
    ]


def _pricing_customers():
    return [{
        "customer_id": "CUST-LP1", "name": "Test Co", "account_tier": "Standard", "contacts": [], "sites": [],
        "contracts": [{"contract_id": "CTR-LP1", "discount_category": "Cat-LP", "covered_categories": ["Cat-LP"],
                       "effective_from": "2024-01-01", "effective_to": "2025-01-01"}],
    }]


def _pricing():
    return {
        "discounts": {"CTR-LP1": 12.0},
        "gap_sku_ids": ["SKU-LP3"],
        "history": [
            {"sku_id": "SKU-LP1", "unit_price": 9.0, "quoted_on": "2024-01-01"},
            {"sku_id": "SKU-LP1", "unit_price": 8.5, "quoted_on": "2024-06-01"},
        ],
    }


def test_load_catalog_loads_requirements(db_session):
    load_catalog(db_session, _pricing_catalog())
    db_session.flush()

    assert required_sku_ids(db_session, "SKU-LP1") == ["SKU-LP2"]


def test_load_pricing_applies_discount_gap_and_history(db_session):
    load_catalog(db_session, _pricing_catalog())
    load_customers(db_session, _pricing_customers())
    db_session.flush()

    load_pricing(db_session, _pricing())
    db_session.flush()

    assert get_contract(db_session, "CTR-LP1").discount_pct == 12.0
    assert get_sku(db_session, "SKU-LP3").list_price is None
    assert get_sku(db_session, "SKU-LP1").list_price == 10.0
    assert latest_realized_price(db_session, "SKU-LP1") == 8.5


def test_load_pricing_sees_rows_loaded_earlier_in_the_same_session(db_session):
    load_catalog(db_session, _pricing_catalog())
    load_customers(db_session, _pricing_customers())

    load_pricing(db_session, _pricing())
    db_session.flush()

    assert get_contract(db_session, "CTR-LP1").discount_pct == 12.0


def test_load_pricing_is_idempotent(db_session):
    load_catalog(db_session, _pricing_catalog())
    load_customers(db_session, _pricing_customers())
    db_session.flush()

    load_pricing(db_session, _pricing())
    load_pricing(db_session, _pricing())
    db_session.flush()

    from sqlalchemy import func, select
    from app.reference_data.models import PriceHistory
    count = db_session.scalar(select(func.count()).select_from(PriceHistory).where(PriceHistory.sku_id == "SKU-LP1"))
    assert count == 2


def test_load_pricing_rejects_unknown_references(db_session):
    load_catalog(db_session, _pricing_catalog())
    db_session.flush()

    with pytest.raises(ValueError):
        load_pricing(db_session, {"discounts": {"CTR-NOPE": 5.0}, "gap_sku_ids": [], "history": []})
