from datetime import date

from app.estimate.guardrails import (
    check_contract_discount, check_price_provenance, check_required_fields, run_guardrails,
)
from app.estimate.schemas import DraftLine, EstimateDraft
from tests.app.estimate.seed import AS_OF, seed_world


def _line(sku_id="SKU-E-A1", quantity=1, unit_price=100.0, price_source="list", discount_pct=0.0):
    return DraftLine(sku_id=sku_id, quantity=quantity, unit_price=unit_price, price_source=price_source,
                     discount_pct=discount_pct)


def _draft(lines, customer_id="CUST-E1", contract_id="CTR-E1"):
    return EstimateDraft(customer_id=customer_id, contract_id=contract_id, lines=lines)


# contract discount

def test_correct_discount_on_covered_category_passes(db_session):
    seed_world(db_session)

    assert check_contract_discount(db_session, _draft([_line(discount_pct=10.0)]), AS_OF) == []


def test_discount_on_uncovered_category_is_blocked(db_session):
    seed_world(db_session)
    draft = _draft([_line(), _line(sku_id="SKU-E-B1", unit_price=50.0, discount_pct=10.0)])

    violations = check_contract_discount(db_session, draft, AS_OF)

    assert len(violations) == 1
    assert violations[0].guardrail == "contract_discount"
    assert violations[0].line_index == 1
    assert "not covered" in violations[0].message
    assert "Cat-E-B" in violations[0].message


def test_discount_on_expired_contract_is_blocked(db_session):
    seed_world(db_session)

    violations = check_contract_discount(db_session, _draft([_line(discount_pct=10.0)]), date(2026, 1, 1))

    assert "not active" in violations[0].message


def test_wrong_pct_is_blocked(db_session):
    seed_world(db_session)

    violations = check_contract_discount(db_session, _draft([_line(discount_pct=15.0)]), AS_OF)

    assert "does not match" in violations[0].message


def test_negative_discount_is_blocked(db_session):
    seed_world(db_session)

    assert check_contract_discount(db_session, _draft([_line(discount_pct=-5.0)]), AS_OF) != []


def test_discount_without_a_contract_is_blocked(db_session):
    seed_world(db_session)

    violations = check_contract_discount(db_session, _draft([_line(discount_pct=10.0)], contract_id=None), AS_OF)

    assert "no valid contract" in violations[0].message


def test_discount_on_another_customers_contract_is_blocked(db_session):
    seed_world(db_session)
    draft = _draft([_line(discount_pct=10.0)], customer_id="CUST-E2", contract_id="CTR-E1")

    assert "no valid contract" in check_contract_discount(db_session, draft, AS_OF)[0].message


def test_zero_discount_is_always_allowed(db_session):
    seed_world(db_session)
    draft = _draft([_line(sku_id="SKU-E-B1", unit_price=50.0)], customer_id="CUST-E2", contract_id=None)

    assert check_contract_discount(db_session, draft, AS_OF) == []


def test_unknown_sku_line_does_not_crash_discount_check(db_session):
    seed_world(db_session)

    assert check_contract_discount(db_session, _draft([_line(sku_id="SKU-NOPE", discount_pct=10.0)]), AS_OF) == []


# required fields

def test_complete_draft_passes_required_fields():
    assert check_required_fields(_draft([_line()])) == []


def test_missing_customer_is_blocked():
    violations = check_required_fields(_draft([_line()], customer_id=None))

    assert violations[0].guardrail == "required_fields"
    assert "customer" in violations[0].message


def test_draft_with_no_lines_is_blocked():
    assert "no lines" in check_required_fields(_draft([]))[0].message


def test_line_missing_fields_is_blocked_per_line():
    draft = _draft([_line(), DraftLine(sku_id=None, quantity=None, unit_price=None, price_source=None)])

    violations = check_required_fields(draft)
    messages = " | ".join(v.message for v in violations)

    assert all(v.line_index == 1 for v in violations)
    assert "SKU" in messages and "quantity" in messages and "price" in messages


def test_zero_or_negative_quantity_is_blocked():
    assert check_required_fields(_draft([_line(quantity=0)])) != []
    assert check_required_fields(_draft([_line(quantity=-2)])) != []


# price provenance

def test_list_price_matching_price_book_passes(db_session):
    seed_world(db_session)

    assert check_price_provenance(db_session, _draft([_line()])) == []


def test_invented_list_price_is_blocked(db_session):
    seed_world(db_session)

    violations = check_price_provenance(db_session, _draft([_line(unit_price=42.0)]))

    assert violations[0].guardrail == "price_provenance"
    assert "does not match" in violations[0].message


def test_list_source_on_gap_sku_is_blocked(db_session):
    seed_world(db_session)

    violations = check_price_provenance(db_session, _draft([_line(sku_id="SKU-E-GAP", unit_price=20.0)]))

    assert "no list price" in violations[0].message


def test_predicted_price_matching_prediction_passes(db_session):
    seed_world(db_session)
    line = _line(sku_id="SKU-E-GAP", unit_price=20.0, price_source="predicted")

    assert check_price_provenance(db_session, _draft([line])) == []


def test_predicted_price_that_differs_is_blocked(db_session):
    seed_world(db_session)
    line = _line(sku_id="SKU-E-GAP", unit_price=99.0, price_source="predicted")

    assert "does not match" in check_price_provenance(db_session, _draft([line]))[0].message


def test_predicted_source_on_priced_sku_is_blocked(db_session):
    seed_world(db_session)

    violations = check_price_provenance(db_session, _draft([_line(price_source="predicted")]))

    assert "has a list price" in violations[0].message


def test_predicted_price_without_enough_peers_is_blocked(db_session):
    seed_world(db_session)
    line = _line(sku_id="SKU-E-LONE", unit_price=5.0, price_source="predicted")

    assert "cannot be predicted" in check_price_provenance(db_session, _draft([line]))[0].message


def test_unknown_sku_is_flagged_by_provenance(db_session):
    seed_world(db_session)

    assert "unknown SKU" in check_price_provenance(db_session, _draft([_line(sku_id="SKU-NOPE")]))[0].message


def test_incomplete_line_is_skipped_by_provenance(db_session):
    seed_world(db_session)
    draft = _draft([DraftLine(sku_id="SKU-E-A1")])

    assert check_price_provenance(db_session, draft) == []


# combined

def test_run_guardrails_collects_all_violations_in_order(db_session):
    seed_world(db_session)
    draft = _draft([_line(unit_price=42.0, discount_pct=15.0)], customer_id=None)

    guardrails = [v.guardrail for v in run_guardrails(db_session, draft, AS_OF)]

    assert guardrails == ["required_fields", "price_provenance", "contract_discount"]


def test_run_guardrails_passes_a_clean_draft(db_session):
    seed_world(db_session)

    assert run_guardrails(db_session, _draft([_line(discount_pct=10.0)]), AS_OF) == []
