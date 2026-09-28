from datetime import date

from app.estimate.models import EstimateDraftRow
from app.intake.repository import save_quote_request
from app.reference_data.models import Contract, Customer, PriceHistory, Sku, SkuRequirement


def _sku(sku_id: str, list_price: float | None = 10.0) -> Sku:
    return Sku(
        sku_id=sku_id, name=sku_id, category="Cat-PM", list_price=list_price,
        discontinued=False, replaced_by=None, in_stock=True,
    )


def test_sku_allows_null_list_price(db_session):
    db_session.add(_sku("SKU-PM1", None))
    db_session.flush()

    assert db_session.get(Sku, "SKU-PM1").list_price is None


def test_contract_discount_pct_defaults_to_zero(db_session):
    db_session.add(Customer(customer_id="CUST-PM1", name="n", account_tier="Standard"))
    db_session.flush()
    contract = Contract(
        contract_id="CTR-PM1", customer_id="CUST-PM1", discount_category="A", covered_categories=["A"],
        effective_from=date(2024, 1, 1), effective_to=date(2025, 1, 1),
    )
    db_session.add(contract)
    db_session.flush()
    db_session.refresh(contract)

    assert contract.discount_pct == 0


def test_requirement_and_price_history_round_trip(db_session):
    db_session.add_all([_sku("SKU-PM2"), _sku("SKU-PM3")])
    db_session.flush()
    db_session.add(SkuRequirement(sku_id="SKU-PM2", required_sku_id="SKU-PM3"))
    history = PriceHistory(sku_id="SKU-PM2", unit_price=9.5, quoted_on=date(2024, 2, 1))
    db_session.add(history)
    db_session.flush()

    assert history.id is not None
    assert db_session.get(SkuRequirement, ("SKU-PM2", "SKU-PM3")) is not None


def test_estimate_draft_row_round_trip(db_session):
    request = save_quote_request(
        db_session, raw_email_text="t", parsed_json={}, content_fingerprint={}, style_fingerprint={},
        customer_id=None,
    )
    row = EstimateDraftRow(
        quote_request_id=request.id, status="ready", draft={"lines": []}, violations=[], iterations=1, reason=None,
    )
    db_session.add(row)
    db_session.flush()
    db_session.refresh(row)

    assert row.id is not None
    assert row.created_at is not None
