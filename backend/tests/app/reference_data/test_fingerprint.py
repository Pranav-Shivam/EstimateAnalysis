from app.intake.repository import save_quote_request
from app.reference_data.models import Contract, Customer, Sku
from app.reference_data.repository import reference_fingerprint, upsert_requirement
from tests.app.estimate.seed import seed_world


def test_fingerprint_is_stable_for_unchanged_data(db_session):
    seed_world(db_session)

    assert reference_fingerprint(db_session) == reference_fingerprint(db_session)


def test_fingerprint_changes_when_a_sku_is_discontinued(db_session):
    seed_world(db_session)
    before = reference_fingerprint(db_session)

    db_session.get(Sku, "SKU-E-A1").discontinued = True
    db_session.flush()

    assert reference_fingerprint(db_session) != before


def test_fingerprint_changes_when_a_requirement_is_added(db_session):
    seed_world(db_session)
    before = reference_fingerprint(db_session)

    upsert_requirement(db_session, sku_id="SKU-E-P1", required_sku_id="SKU-E-A1")
    db_session.flush()

    assert reference_fingerprint(db_session) != before


def test_fingerprint_changes_when_a_contract_changes(db_session):
    seed_world(db_session)
    before = reference_fingerprint(db_session)

    db_session.get(Contract, "CTR-E1").covered_categories = ["Cat-E-A", "Cat-E-B"]
    db_session.flush()

    assert reference_fingerprint(db_session) != before


def test_fingerprint_ignores_runtime_entities_and_unrelated_columns(db_session):
    seed_world(db_session)
    before = reference_fingerprint(db_session)

    save_quote_request(
        db_session, raw_email_text="x", parsed_json={}, content_fingerprint={}, style_fingerprint={},
        customer_id="CUST-E1",
    )
    db_session.get(Customer, "CUST-E1").name = "Renamed Co"
    db_session.get(Sku, "SKU-E-A1").list_price = 123.0
    db_session.flush()

    assert reference_fingerprint(db_session) == before
