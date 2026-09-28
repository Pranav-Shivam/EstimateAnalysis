# backend/tests/app/reference_data/test_repository.py
from datetime import date

from app.reference_data.models import Customer, Sku
from app.reference_data.repository import (
    all_customers,
    all_skus,
    contracts_for_customer,
    get_contract,
    get_customer,
    get_sku,
    latest_realized_price,
    replace_price_history,
    required_sku_ids,
    skus_with_list_price_in_category,
    upsert_contract,
    upsert_customer,
    upsert_requirement,
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


def _add_sku(session, sku_id, category="Cat-RP", list_price=10.0):
    upsert_sku(session, sku_id=sku_id, name=sku_id, category=category, list_price=list_price,
               discontinued=False, replaced_by=None, in_stock=True)


def test_upsert_sku_accepts_null_list_price(db_session):
    _add_sku(db_session, "SKU-RP1", list_price=None)
    db_session.flush()

    assert get_sku(db_session, "SKU-RP1").list_price is None


def test_upsert_contract_stores_discount_pct(db_session):
    upsert_customer(db_session, customer_id="CUST-RP1", name="n", account_tier="Standard")
    db_session.flush()
    upsert_contract(
        db_session, contract_id="CTR-RP1", customer_id="CUST-RP1", discount_category="A",
        covered_categories=["A"], effective_from=date(2024, 1, 1), effective_to=date(2025, 1, 1), discount_pct=12.0,
    )
    db_session.flush()

    assert get_contract(db_session, "CTR-RP1").discount_pct == 12.0
    assert get_customer(db_session, "CUST-RP1").name == "n"


def test_requirements_are_idempotent_and_sorted(db_session):
    for sku_id in ("SKU-RP2", "SKU-RP3", "SKU-RP4"):
        _add_sku(db_session, sku_id)
    db_session.flush()
    upsert_requirement(db_session, sku_id="SKU-RP2", required_sku_id="SKU-RP4")
    upsert_requirement(db_session, sku_id="SKU-RP2", required_sku_id="SKU-RP3")
    upsert_requirement(db_session, sku_id="SKU-RP2", required_sku_id="SKU-RP3")
    db_session.flush()

    assert required_sku_ids(db_session, "SKU-RP2") == ["SKU-RP3", "SKU-RP4"]


def test_replace_price_history_replaces_and_latest_wins(db_session):
    _add_sku(db_session, "SKU-RP5")
    db_session.flush()
    replace_price_history(db_session, "SKU-RP5", [(9.0, date(2024, 1, 1)), (8.0, date(2024, 6, 1))])
    db_session.flush()
    assert latest_realized_price(db_session, "SKU-RP5") == 8.0

    replace_price_history(db_session, "SKU-RP5", [(7.0, date(2024, 3, 1))])
    db_session.flush()
    assert latest_realized_price(db_session, "SKU-RP5") == 7.0


def test_latest_realized_price_is_none_without_history(db_session):
    _add_sku(db_session, "SKU-RP6")
    db_session.flush()

    assert latest_realized_price(db_session, "SKU-RP6") is None


def test_skus_with_list_price_in_category_excludes_gaps(db_session):
    _add_sku(db_session, "SKU-RP7", category="Cat-RP-Only", list_price=10.0)
    _add_sku(db_session, "SKU-RP8", category="Cat-RP-Only", list_price=None)
    db_session.flush()

    ids = [s.sku_id for s in skus_with_list_price_in_category(db_session, "Cat-RP-Only")]

    assert ids == ["SKU-RP7"]
