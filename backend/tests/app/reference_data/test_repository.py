# backend/tests/app/reference_data/test_repository.py
from datetime import date

from app.reference_data.models import Customer, Sku
from app.reference_data.repository import (
    all_customers,
    all_skus,
    contracts_for_customer,
    upsert_contract,
    upsert_customer,
    upsert_site,
    upsert_sku,
)


def test_upsert_sku_inserts_then_updates(db_session):
    upsert_sku(db_session, sku_id="SKU-T1", name="Widget", category="Cat", list_price=10.0,
               discontinued=False, replaced_by=None, in_stock=True)
    db_session.flush()
    row = db_session.get(Sku, "SKU-T1")
    assert row.name == "Widget"

    upsert_sku(db_session, sku_id="SKU-T1", name="Widget V2", category="Cat", list_price=12.0,
               discontinued=True, replaced_by=None, in_stock=False)
    db_session.flush()
    assert db_session.get(Sku, "SKU-T1").name == "Widget V2"
    assert sum(1 for s in all_skus(db_session) if s.sku_id == "SKU-T1") == 1


def test_upsert_customer_site_contract_and_lookup(db_session):
    upsert_customer(db_session, customer_id="CUST-T1", name="Test Co", account_tier="Standard")
    upsert_site(db_session, site_id="SITE-T1", customer_id="CUST-T1", address="1 Main St", zip_code="00000")
    upsert_contract(
        db_session, contract_id="CTR-T1", customer_id="CUST-T1", discount_category="A",
        covered_categories=["A", "B"], effective_from=date(2024, 1, 1), effective_to=date(2025, 1, 1),
    )
    db_session.flush()

    customers = all_customers(db_session)
    assert any(c.customer_id == "CUST-T1" for c in customers)

    contracts = contracts_for_customer(db_session, "CUST-T1")
    assert len(contracts) == 1
    assert contracts[0].contract_id == "CTR-T1"
