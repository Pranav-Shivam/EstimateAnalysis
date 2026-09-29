from dataclasses import dataclass


@dataclass(frozen=True)
class ScoredDimension:
    name: str
    score: float
    rationale: str


def rollup(dimensions: list[ScoredDimension]) -> tuple[float, str]:
    """The overall confidence is the weakest dimension, so one bad fact cannot be diluted by two good ones.
    An exact tie breaks alphabetically so the flagged dimension is deterministic."""
    overall = min(d.score for d in dimensions)
    flagged = sorted(d.name for d in dimensions if d.score == overall)[0]
    return overall, flagged


def gate(overall_confidence: float, threshold: float) -> bool:
    return overall_confidence >= threshold
