import json
from pathlib import Path

from app.judge.calibration import calibrate
from app.judge.constant import KAPPA_ACCEPTABLE
from app.judge.scoring import ScoredDimension, gate, rollup

GOLDEN_SET_PATH = Path(__file__).resolve().parent.parent / "data" / "judge_golden_set.json"


def _overall_confidence(case: dict) -> float:
    dims = [ScoredDimension(name=name, score=score, rationale="golden set fixture")
            for name, score in case["scores"].items()]
    overall, _ = rollup(dims)
    return overall


def test_calibrated_threshold_separates_the_golden_set_as_labeled():
    """This is the roadmap's Phase 5 done-when criterion, run against the hand-scored golden set instead of
    a live Claude Haiku call: the scores here are the human annotator's own honest judgment of what a
    well-calibrated judge should say for each case (see judge_golden_set_gen.py), not model output. The
    real threshold used in production comes from scripts/calibrate_judge.py --yes against the real API,
    run separately once the owner has an Anthropic key and approves the spend.

    Calibration itself only sees the 29 "ready" cases the judge actually scores: the 3 "needs_review"
    fast-path cases always score 0.0 and always escalate before the judge is ever asked, so folding them
    into the kappa computation would count guardrail behavior as judge agreement it never earned. Their
    labels are still checked, just directly rather than through kappa."""
    cases = json.loads(GOLDEN_SET_PATH.read_text(encoding="utf-8"))
    ready_cases = [c for c in cases if c["estimate_status"] == "ready"]
    fast_path_cases = [c for c in cases if c["estimate_status"] != "ready"]

    for case in fast_path_cases:
        assert case["label"] == "escalate", case["case_id"]

    scores = [_overall_confidence(c) for c in ready_cases]
    labels = [c["label"] == "trust" for c in ready_cases]

    result = calibrate(scores, labels, KAPPA_ACCEPTABLE)

    assert result is not None
    assert result.kappa >= KAPPA_ACCEPTABLE
    for case, score in zip(ready_cases, scores):
        assert gate(score, result.threshold) == (case["label"] == "trust"), case["case_id"]
