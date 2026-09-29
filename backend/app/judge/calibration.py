from dataclasses import dataclass

from app.judge.scoring import gate


@dataclass(frozen=True)
class CalibrationResult:
    threshold: float
    kappa: float


def cohens_kappa(pairs: list[tuple[bool, bool]]) -> float:
    """Standard 2x2 Cohen's kappa between two boolean raters (here: judge-trusts vs. human-trusts)."""
    n = len(pairs)
    if n == 0:
        return 0.0
    agree = sum(1 for a, b in pairs if a == b) / n
    rate_a = sum(1 for a, _ in pairs if a) / n
    rate_b = sum(1 for _, b in pairs if b) / n
    expected = rate_a * rate_b + (1 - rate_a) * (1 - rate_b)
    if expected == 1.0:
        return 1.0 if agree == 1.0 else 0.0
    return (agree - expected) / (1 - expected)


def calibrate(scores: list[float], labels: list[bool], acceptable_kappa: float) -> CalibrationResult | None:
    """Sweeps every observed confidence score as a candidate threshold and returns the LOWEST one whose
    kappa against the golden set's human labels still clears acceptable_kappa: the lowest threshold
    maximizes how much gets auto-trusted (coverage) without dropping below the agreement bar. Returns
    None when no candidate clears it, per the research: a low kappa means fix the rubric, not ship a
    threshold that failed its own check."""
    best = None
    for candidate in sorted(set(scores)):
        pairs = [(gate(score, candidate), label) for score, label in zip(scores, labels)]
        kappa = cohens_kappa(pairs)
        if kappa >= acceptable_kappa and (best is None or candidate < best.threshold):
            best = CalibrationResult(threshold=candidate, kappa=kappa)
    return best
