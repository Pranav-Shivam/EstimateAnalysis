from datetime import date

from app.estimate.schemas import DraftLine, EstimateDraft
from app.judge.evidence import build_evidence
from app.reference_data.repository import upsert_contract
from tests.app.estimate.seed import AS_OF, seed_world


def _draft(lines, customer_id="CUST-E1", contract_id="CTR-E1"):
    return EstimateDraft(customer_id=customer_id, contract_id=contract_id, lines=lines)


def test_list_price_line_carries_its_list_price(db_session, make_reader):
    seed_world(db_session)
    reader = make_reader()
    line = DraftLine(sku_id="SKU-E-A1", quantity=1, unit_price=100.0, price_source="list", discount_pct=0.0)

    evidence = build_evidence(db_session, reader, _draft([line]), AS_OF)

    assert evidence[0].price.price_source == "list"
    assert evidence[0].price.list_price == 100.0
    assert evidence[0].price.predicted_price is None


def test_predicted_price_line_carries_peer_evidence(db_session, make_reader):
    seed_world(db_session)
    reader = make_reader()
    line = DraftLine(sku_id="SKU-E-GAP", quantity=1, unit_price=20.0, price_source="predicted", discount_pct=0.0)

    evidence = build_evidence(db_session, reader, _draft([line], contract_id=None), AS_OF)

    assert evidence[0].price.price_source == "predicted"
    assert evidence[0].price.predicted_price == 20.0
    assert evidence[0].price.peer_count == 3
    assert evidence[0].price.low == 15.0
    assert evidence[0].price.high == 25.0


def test_line_without_a_discount_has_no_contract_claim(db_session, make_reader):
    seed_world(db_session)
    reader = make_reader()
    line = DraftLine(sku_id="SKU-E-A1", quantity=1, unit_price=100.0, price_source="list", discount_pct=0.0)

    evidence = build_evidence(db_session, reader, _draft([line]), AS_OF)

    assert evidence[0].contract.covered is None
    assert evidence[0].contract.days_to_expiry is None


def test_discount_without_a_contract_reports_no_coverage_claim(db_session, make_reader):
    seed_world(db_session)
    reader = make_reader()
    line = DraftLine(sku_id="SKU-E-A1", quantity=1, unit_price=100.0, price_source="list", discount_pct=10.0)

    evidence = build_evidence(db_session, reader, _draft([line], customer_id=None, contract_id=None), AS_OF)

    assert evidence[0].contract.covered is None
    assert evidence[0].contract.contract_id is None


def test_covered_discount_reports_days_to_expiry(db_session, make_reader):
    seed_world(db_session)
    reader = make_reader()
    line = DraftLine(sku_id="SKU-E-A1", quantity=1, unit_price=100.0, price_source="list", discount_pct=10.0)

    evidence = build_evidence(db_session, reader, _draft([line]), AS_OF)

    assert evidence[0].contract.covered is True
    assert evidence[0].contract.active_on_as_of is True
    assert evidence[0].contract.days_to_expiry == (date(2025, 12, 31) - AS_OF).days


def test_near_expiry_contract_reports_a_small_days_to_expiry(db_session, make_reader):
    seed_world(db_session)
    upsert_contract(
        db_session, contract_id="CTR-E2", customer_id="CUST-E1", discount_category="Cat-E-A",
        covered_categories=["Cat-E-A"], effective_from=date(2024, 1, 1), effective_to=date(2024, 9, 5),
        discount_pct=10.0,
    )
    db_session.flush()
    reader = make_reader()
    line = DraftLine(sku_id="SKU-E-A1", quantity=1, unit_price=100.0, price_source="list", discount_pct=10.0)

    evidence = build_evidence(db_session, reader, _draft([line], contract_id="CTR-E2"), AS_OF)

    assert evidence[0].contract.days_to_expiry == 4


def test_discontinued_line_reports_live_replacement(db_session, make_reader):
    seed_world(db_session)
    reader = make_reader()
    line = DraftLine(sku_id="SKU-E-OLD", quantity=1, unit_price=80.0, price_source="list", discount_pct=0.0)

    evidence = build_evidence(db_session, reader, _draft([line], contract_id=None), AS_OF)

    assert evidence[0].graph.discontinued is True
    assert evidence[0].graph.live_sku_id == "SKU-E-A1"


def test_missing_required_part_is_reported(db_session, make_reader):
    seed_world(db_session)
    reader = make_reader()
    line = DraftLine(sku_id="SKU-E-B1", quantity=1, unit_price=50.0, price_source="list", discount_pct=0.0)

    evidence = build_evidence(db_session, reader, _draft([line], contract_id=None), AS_OF)

    assert evidence[0].graph.required_part_ids == ["SKU-E-A1"]
    assert evidence[0].graph.missing_required_part_ids == ["SKU-E-A1"]


def test_present_required_part_is_not_reported_as_missing(db_session, make_reader):
    seed_world(db_session)
    reader = make_reader()
    lines = [
        DraftLine(sku_id="SKU-E-B1", quantity=1, unit_price=50.0, price_source="list", discount_pct=0.0),
        DraftLine(sku_id="SKU-E-A1", quantity=1, unit_price=100.0, price_source="list", discount_pct=0.0),
    ]

    evidence = build_evidence(db_session, reader, _draft(lines, contract_id=None), AS_OF)

    assert evidence[0].graph.missing_required_part_ids == []
    assert evidence[1].line_index == 1
