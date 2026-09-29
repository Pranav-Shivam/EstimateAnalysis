import json
from pathlib import Path

from app.judge.calibration import calibrate
from app.judge.constant import KAPPA_ACCEPTABLE
from app.judge.scoring import ScoredDimension, gate, rollup

GOLDEN_SET_PATH = Path(__file__).resolve().parent.parent / "data" / "judge_golden_set.json"


def _overall_confidence(case: dict) -> float:
    if case["estimate_status"] != "ready":
        return 0.0
    dims = [ScoredDimension(name=name, score=score, rationale="golden set fixture")
            for name, score in case["scores"].items()]
    overall, _ = rollup(dims)
    return overall


def test_calibrated_threshold_separates_the_golden_set_as_labeled():
    """This is the roadmap's Phase 5 done-when criterion, run against the hand-scored golden set instead of
    a live Claude Haiku call: the scores here are the human annotator's own honest judgment of what a
    well-calibrated judge should say for each case (see judge_golden_set_gen.py), not model output. The
    real threshold used in production comes from scripts/calibrate_judge.py --yes against the real API,
    run separately once the owner has an Anthropic key and approves the spend."""
    cases = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))
    scores = [_overall_confidence(c) for c in cases]
    labels = [c["label"] == "trust" for c in cases]

    result = calibrate(scores, labels, KAPPA_ACCEPTABLE)

    assert result is not None
    assert result.kappa >= KAPPA_ACCEPTABLE
    for case, score in zip(cases, scores):
        assert gate(score, result.threshold) == (case["label"] == "trust"), case["case_id"]
