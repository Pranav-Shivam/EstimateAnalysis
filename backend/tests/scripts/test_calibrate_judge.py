import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from app.judge.models import EvalCaseRow
from core.llm.anthropic_judge_client import RawDimensionScore, RawJudgeScore
from scripts.calibrate_judge import (
    CeilingBreached, MalformedEvalCase, NoAcceptableThreshold, load_eval_cases, run_calibration,
)
from tests.app.judge.fakes import full_line_evidence


class QueuedJudgeClient:
    """Returns one scripted overall score per call, in call order (every dimension gets the same score, so
    rollup's min() is that score exactly). Lets a test control exactly which case gets which confidence."""

    def __init__(self, scores: list[float]) -> None:
        self._scores = iter(scores)

    def score(self, evidence, system_prompt):
        s = next(self._scores)
        return RawJudgeScore(dimensions=[
            RawDimensionScore(name="price_provenance", score=s, rationale="r"),
            RawDimensionScore(name="contract_discount", score=s, rationale="r"),
            RawDimensionScore(name="graph_completion", score=s, rationale="r"),
        ])


def _case(case_id: str, label: str) -> dict:
    return {
        "case_id": case_id, "label": label, "estimate_status": "ready",
        "evidence": [{
            "line_index": 0, "sku_id": "SKU-X", "unit_price": 10.0,
            "price": {"price_source": "list", "list_price": 10.0, "predicted_price": None, "peer_count": None,
                      "low": None, "high": None},
            "contract": {"discount_pct": 0.0, "contract_id": None, "covered": None, "active_on_as_of": None,
                         "days_to_expiry": None},
            "graph": {"discontinued": False, "live_sku_id": "SKU-X", "required_part_ids": [],
                      "missing_required_part_ids": []},
        }],
    }


def _cases(breach: bool) -> list[dict]:
    """5 cases scored 0.9 (4 labeled trust, 1 labeled escalate if breach else trust) + 5 cases scored 0.2
    (labeled escalate). Hand-verified: at threshold 0.9 this gives kappa 0.8 (clears 0.6) with a
    false-auto-send rate of 0.1 (breach, ceiling 0.05) when the 5th case is mislabeled, or 0.0 (no breach)
    when it agrees. Threshold 0.2 always scores kappa 0 (every case predicted trust), so calibrate() must
    pick 0.9, the only clearing candidate, in both variants."""
    fifth_label = "escalate" if breach else "trust"
    return (
        [_case(f"c{i}", "trust") for i in range(1, 5)] + [_case("c5", fifth_label)]
        + [_case(f"c{i}", "escalate") for i in range(6, 11)]
    )


def _scores() -> list[float]:
    return [0.9] * 5 + [0.2] * 5


def test_run_calibration_raises_ceiling_breached_when_the_gate_fails():
    with pytest.raises(CeilingBreached) as exc_info:
        run_calibration(_cases(breach=True), QueuedJudgeClient(_scores()), golden_set_size=10, eval_case_count=0)

    assert exc_info.value.rate == pytest.approx(0.1)
    assert exc_info.value.wrong_case_ids == ["c5"]


def test_run_calibration_returns_a_payload_when_the_gate_clears():
    payload = run_calibration(_cases(breach=False), QueuedJudgeClient(_scores()), golden_set_size=10, eval_case_count=0)

    assert payload["threshold"] == 0.9
    assert payload["kappa"] == pytest.approx(1.0)
    assert payload["false_auto_send_rate"] == 0.0


def test_run_calibration_raises_no_acceptable_threshold_when_kappa_never_clears():
    cases = [_case("c1", "trust"), _case("c2", "escalate")]
    with pytest.raises(NoAcceptableThreshold):
        run_calibration(cases, QueuedJudgeClient([0.5, 0.5]), golden_set_size=2, eval_case_count=0)


def _eval_case_row(evidence: list[dict]) -> EvalCaseRow:
    return EvalCaseRow(
        id=uuid.uuid4(), source_review_item_id=None, case_id=f"rc-test-{uuid.uuid4().hex[:8]}", label="escalate",
        estimate_status="ready", evidence=evidence,
    )


def test_load_eval_cases_returns_the_stored_full_line_evidence_unchanged(db_session):
    row = _eval_case_row([full_line_evidence("SKU-X")])
    db_session.add(row)
    db_session.flush()

    (loaded,) = [case for case in load_eval_cases(db_session) if case["case_id"] == row.case_id]

    assert loaded["evidence"] == [full_line_evidence("SKU-X")]
    assert loaded["label"] == "escalate"


def test_load_eval_cases_refuses_evidence_missing_a_dimension(db_session):
    # Filling the gaps with defaults would re-score the case as a $0 list-price line and skew the release gate.
    db_session.add(_eval_case_row([{"line_index": 0, "sku_id": "SKU-X", "price_source": "predicted"}]))
    db_session.flush()

    with pytest.raises(MalformedEvalCase):
        load_eval_cases(db_session)


def test_dry_run_prints_and_returns_before_scoring_anything(capsys, monkeypatch):
    """main()'s no-`--yes` branch returns before it would ever call run_calibration or touch CALIBRATION_PATH."""
    monkeypatch.setattr(sys, "argv", ["calibrate_judge.py"])

    from scripts import calibrate_judge

    calibrate_judge.main()

    assert "dry run" in capsys.readouterr().out
