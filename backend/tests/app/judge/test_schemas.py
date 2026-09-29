import uuid

import pytest

from app.judge.models import ReviewItemRow
from app.judge.schemas import InvalidCorrection, build_eval_case, validate_correction
from tests.app.estimate.seed import seed_world

PRICE_EVIDENCE = {"lines": [{"line_index": 0, "sku_id": "SKU-E-GAP", "price_source": "predicted", "list_price": None}]}
GRAPH_EVIDENCE = {"lines": [{"line_index": 0, "sku_id": "SKU-E-B1", "required_part_ids": [], "missing_required_part_ids": []}]}
CONTRACT_EVIDENCE = {"lines": [{"line_index": 0, "sku_id": "SKU-E-A1", "contract_id": "CTR-E1", "covered": False}]}


def _row(dimension, evidence):
    return ReviewItemRow(
        id=uuid.uuid4(), judge_verdict_id=uuid.uuid4(), estimate_id=uuid.uuid4(), dimension=dimension,
        fact="x", evidence=evidence, line_index=None,
    )


def test_validate_correction_accepts_a_price_correction_naming_a_flagged_sku(db_session):
    seed_world(db_session)
    validate_correction(db_session, "price_provenance", {"sku_id": "SKU-E-GAP", "corrected_unit_price": 42.5},
                         evidence=PRICE_EVIDENCE)


def test_validate_correction_rejects_a_sku_the_review_item_never_named(db_session):
    seed_world(db_session)
    with pytest.raises(InvalidCorrection):
        validate_correction(db_session, "price_provenance", {"sku_id": "SKU-E-A1", "corrected_unit_price": 42.5},
                             evidence=PRICE_EVIDENCE)


def test_validate_correction_rejects_an_unknown_required_sku(db_session):
    seed_world(db_session)
    with pytest.raises(InvalidCorrection):
        validate_correction(db_session, "graph_completion",
                             {"sku_id": "SKU-E-B1", "required_sku_id": "SKU-NOPE"}, evidence=GRAPH_EVIDENCE)


def test_validate_correction_rejects_a_mismatched_contract_id(db_session):
    seed_world(db_session)
    with pytest.raises(InvalidCorrection):
        validate_correction(db_session, "contract_discount", {"contract_id": "CTR-NOPE", "category": "Cat-E-B"},
                             evidence=CONTRACT_EVIDENCE)


def test_validate_correction_rejects_an_unresolvable_dimension(db_session):
    with pytest.raises(InvalidCorrection):
        validate_correction(db_session, "guardrail", {}, evidence={"violations": []})


def test_build_eval_case_uses_trust_label_for_an_approved_outcome():
    row = _row("price_provenance", PRICE_EVIDENCE)
    case = build_eval_case(row, "approved", "rc-0001")
    assert case.label == "trust"
    assert case.estimate_status == "ready"
    assert case.evidence == PRICE_EVIDENCE["lines"]
    assert case.source_review_item_id == row.id


def test_build_eval_case_uses_escalate_label_for_a_corrected_outcome():
    row = _row("graph_completion", GRAPH_EVIDENCE)
    case = build_eval_case(row, "corrected", "rc-0002")
    assert case.label == "escalate"
