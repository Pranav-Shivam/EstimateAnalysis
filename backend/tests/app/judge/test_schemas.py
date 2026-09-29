import uuid

import pytest

from app.judge.models import ReviewItemRow
from app.judge.schemas import InvalidCorrection, build_eval_case, validate_correction
from tests.app.estimate.seed import seed_world
from tests.app.judge.fakes import full_line_evidence

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


UNCOVERED_EVIDENCE = {"lines": [{"line_index": 0, "sku_id": "SKU-E-B1", "contract_id": "CTR-E1", "covered": False}]}


def test_validate_correction_accepts_the_flagged_lines_own_category(db_session):
    seed_world(db_session)
    validate_correction(db_session, "contract_discount", {"contract_id": "CTR-E1", "category": "Cat-E-B"},
                         evidence=UNCOVERED_EVIDENCE)


@pytest.mark.parametrize("dimension, correction, evidence", [
    ("price_provenance", None, PRICE_EVIDENCE),
    ("price_provenance", {"sku_id": "SKU-E-GAP"}, PRICE_EVIDENCE),
    ("price_provenance", {"sku_id": "SKU-E-GAP", "corrected_unit_price": "42.5"}, PRICE_EVIDENCE),
    ("price_provenance", {"sku_id": "SKU-E-GAP", "corrected_unit_price": True}, PRICE_EVIDENCE),
    ("price_provenance", {"sku_id": "SKU-E-GAP", "corrected_unit_price": -1.0}, PRICE_EVIDENCE),
    ("price_provenance", {"sku_id": "SKU-E-GAP", "corrected_unit_price": 0}, PRICE_EVIDENCE),
    ("price_provenance", {"sku_id": "SKU-E-GAP", "corrected_unit_price": float("nan")}, PRICE_EVIDENCE),
    ("price_provenance", {"sku_id": "SKU-E-GAP", "corrected_unit_price": 42.5, "note": "x"}, PRICE_EVIDENCE),
    ("graph_completion", {"sku_id": "SKU-E-B1"}, GRAPH_EVIDENCE),
    ("graph_completion", {"sku_id": "SKU-E-B1", "required_sku_id": 7}, GRAPH_EVIDENCE),
    ("graph_completion", {"sku_id": "SKU-E-B1", "required_sku_id": "SKU-E-B1"}, GRAPH_EVIDENCE),
    ("contract_discount", {"contract_id": "CTR-E1"}, UNCOVERED_EVIDENCE),
    ("contract_discount", {"contract_id": "CTR-E1", "category": "Cat-E-INVENTED"}, UNCOVERED_EVIDENCE),
    ("contract_discount", {"contract_id": "CTR-E1", "category": "Cat-E-A"}, UNCOVERED_EVIDENCE),
])
def test_validate_correction_rejects_a_malformed_or_unsupported_correction(db_session, dimension, correction, evidence):
    seed_world(db_session)
    with pytest.raises(InvalidCorrection):
        validate_correction(db_session, dimension, correction, evidence=evidence)


def test_validate_correction_rejects_an_unresolvable_dimension(db_session):
    with pytest.raises(InvalidCorrection):
        validate_correction(db_session, "guardrail", {}, evidence={"violations": []})


FULL_LINE = full_line_evidence("SKU-E-GAP")


def test_build_eval_case_carries_every_lines_full_evidence_not_just_the_flagged_dimension():
    # The release gate re-scores eval cases; with only the flagged dimension's slice it would score a $0 line.
    row = _row("price_provenance", {**PRICE_EVIDENCE, "line_evidence": [FULL_LINE]})
    case = build_eval_case(row, "approved", "rc-0001")
    assert case.label == "trust"
    assert case.estimate_status == "ready"
    assert case.evidence == [FULL_LINE]
    assert case.source_review_item_id == row.id


def test_build_eval_case_uses_escalate_label_for_a_corrected_outcome():
    row = _row("graph_completion", {**GRAPH_EVIDENCE, "line_evidence": [FULL_LINE]})
    case = build_eval_case(row, "corrected", "rc-0002")
    assert case.label == "escalate"
