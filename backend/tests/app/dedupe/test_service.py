import uuid
from datetime import date

from app.dedupe.service import run_dedupe
from app.intake.repository import save_quote_request
from app.reference_data.repository import upsert_contract, upsert_customer, upsert_site


def _seed_customer_and_site(db_session):
    # quote_requests.customer_id / site_id are foreign keys, so the referenced
    # rows must exist before a quote request can point at them.
    upsert_customer(db_session, customer_id="CUST-A", name="Test Customer", account_tier="Standard")
    upsert_site(db_session, site_id="SITE-A", customer_id="CUST-A", address="1 Test St", zip_code="00000")
    db_session.flush()


def _make_request(db_session, customer_id, site_id, sku_ids, raw_text="text", contract_id=None):
    return save_quote_request(
        db_session, raw_email_text=raw_text, parsed_json={},
        content_fingerprint={"sku_ids": sku_ids}, style_fingerprint={"tokens": []},
        customer_id=customer_id, site_id=site_id, contract_id=contract_id,
    )


def test_run_dedupe_flags_identical_sku_set_as_duplicate(db_session):
    _seed_customer_and_site(db_session)
    first = _make_request(db_session, "CUST-A", "SITE-A", ["SKU-A", "SKU-B"])
    second = _make_request(db_session, "CUST-A", "SITE-A", ["SKU-A", "SKU-B"])
    db_session.flush()

    verdicts = run_dedupe(db_session, second.id)
    assert len(verdicts) == 1
    assert verdicts[0].candidate_quote_request_id == first.id
    assert verdicts[0].verdict == "DUPLICATE_OF"


def test_run_dedupe_flags_superset_as_revision(db_session):
    _seed_customer_and_site(db_session)
    original = _make_request(db_session, "CUST-A", "SITE-A", ["SKU-A"])
    revision = _make_request(db_session, "CUST-A", "SITE-A", ["SKU-A", "SKU-B"])
    db_session.flush()

    verdicts = run_dedupe(db_session, revision.id)
    assert verdicts[0].verdict == "REVISION_OF"


def test_run_dedupe_excludes_the_target_itself_from_candidates(db_session):
    _seed_customer_and_site(db_session)
    only_request = _make_request(db_session, "CUST-A", "SITE-A", ["SKU-A"])
    db_session.flush()

    verdicts = run_dedupe(db_session, only_request.id)
    assert verdicts == []


def test_run_dedupe_unresolved_customer_and_site_yields_no_candidates(db_session):
    request = _make_request(db_session, None, None, [])
    db_session.flush()

    verdicts = run_dedupe(db_session, request.id)
    assert verdicts == []


def test_run_dedupe_raises_for_unknown_quote_request(db_session):
    import pytest
    with pytest.raises(ValueError):
        run_dedupe(db_session, uuid.uuid4())


def test_run_dedupe_blocks_on_shared_contract_alone(db_session):
    # Two different customers and sites, sharing only a contract_id: blocking
    # must still surface the candidate on the contract signal alone.
    upsert_customer(db_session, customer_id="CUST-A", name="Test Customer A", account_tier="Standard")
    upsert_customer(db_session, customer_id="CUST-B", name="Test Customer B", account_tier="Standard")
    upsert_site(db_session, site_id="SITE-A", customer_id="CUST-A", address="1 Test St", zip_code="00000")
    upsert_site(db_session, site_id="SITE-B", customer_id="CUST-B", address="2 Test St", zip_code="00001")
    upsert_contract(
        db_session, contract_id="CTR-SHARED", customer_id="CUST-A", discount_category="Standard",
        covered_categories=["C"], effective_from=date(2020, 1, 1), effective_to=date(2030, 1, 1),
    )
    db_session.flush()

    first = _make_request(db_session, "CUST-A", "SITE-A", ["SKU-X"], contract_id="CTR-SHARED")
    second = _make_request(db_session, "CUST-B", "SITE-B", ["SKU-X"], contract_id="CTR-SHARED")
    db_session.flush()

    verdicts = run_dedupe(db_session, second.id)
    assert len(verdicts) == 1
    assert verdicts[0].candidate_quote_request_id == first.id
    assert "same_contract" in verdicts[0].signals_fired
