import json
from pathlib import Path

DIMENSION_NAMES = {"price_provenance", "contract_discount", "graph_completion"}
DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _cases():
    return json.loads((DATA_DIR / "judge_golden_set.json").read_text(encoding="utf-8"))


def test_golden_set_has_at_least_twenty_cases():
    assert len(_cases()) >= 20


def test_golden_set_has_both_labels():
    labels = {c["label"] for c in _cases()}
    assert labels == {"trust", "escalate"}


def test_every_ready_case_has_evidence_and_scores_for_all_three_dimensions():
    for case in _cases():
        if case["estimate_status"] != "ready":
            continue
        assert case["evidence"], case["case_id"]
        for line in case["evidence"]:
            assert set(line.keys()) >= {"line_index", "sku_id", "unit_price", "price", "contract", "graph"}, case["case_id"]
        assert set(case["scores"].keys()) == DIMENSION_NAMES, case["case_id"]
        for score in case["scores"].values():
            assert 0.0 <= score <= 1.0, case["case_id"]


def test_every_needs_review_case_has_a_guardrail_reason():
    for case in _cases():
        if case["estimate_status"] == "needs_review":
            assert case.get("guardrail_reason"), case["case_id"]


def test_case_ids_are_unique():
    ids = [c["case_id"] for c in _cases()]
    assert len(ids) == len(set(ids))
