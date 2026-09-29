import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.estimate.repository import get_estimate_draft
from app.estimate.schemas import EstimateDraft
from app.graph.reader import GraphReader
from app.judge.constant import CALIBRATION_PATH, DEFAULT_CONFIDENCE_THRESHOLD
from app.judge.evidence import LineEvidence, build_evidence
from app.judge.prompts import JUDGE_SYSTEM_PROMPT
from app.judge.models import ReviewItemRow
from app.judge.repository import (
    get_review_item, next_eval_case_id, save_eval_case, save_judge_verdict, save_review_item,
)
from app.judge.schemas import (
    RESOLVABLE_DIMENSIONS, DimensionScore, EvalCase, JudgeVerdict, ReviewItem, build_eval_case, validate_correction,
)
from app.judge.scoring import ScoredDimension, gate, rollup
from core.llm.anthropic_judge_client import JUDGE_MODEL, AnthropicJudgeClient


class EstimateNotFound(Exception):
    pass


class ReviewItemNotFound(Exception):
    pass


class ReviewItemAlreadyResolved(Exception):
    pass


class ReviewItemNotResolvable(Exception):
    pass


@dataclass
class ReviewItemResolution:
    row: ReviewItemRow
    eval_case: EvalCase
    consolidation_required: bool


@dataclass
class JudgeRunResult:
    verdict: JudgeVerdict
    verdict_id: uuid.UUID
    review_item: ReviewItem | None


def current_threshold() -> float:
    """Reads the threshold the real `scripts/calibrate_judge.py --yes` run wrote. Uncalibrated until that
    real, paid run happens, so a conservative placeholder is used until then."""
    if CALIBRATION_PATH.exists():
        import json
        return json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))["threshold"]
    return DEFAULT_CONFIDENCE_THRESHOLD


def _dimension_evidence(name: str, lines: list[LineEvidence]) -> list[dict]:
    key = {"price_provenance": "price", "contract_discount": "contract", "graph_completion": "graph"}[name]
    return [{"line_index": line.line_index, "sku_id": line.sku_id, **asdict(getattr(line, key))} for line in lines]


def _fast_path_verdict(estimate_id: uuid.UUID) -> JudgeVerdict:
    return JudgeVerdict(
        estimate_id=estimate_id, model="none (guardrail fast path)", dimensions=[],
        overall_confidence=0.0, flagged_dimension="guardrail", trusted=False,
    )


def run_judge(
    session: Session, graph: GraphReader, as_of: date, estimate_id: uuid.UUID, llm_client: AnthropicJudgeClient,
) -> JudgeRunResult:
    row = get_estimate_draft(session, estimate_id)
    if row is None:
        raise EstimateNotFound(f"estimate {estimate_id} not found")

    if row.status == "needs_review":
        verdict = _fast_path_verdict(estimate_id)
        fact = row.reason or "guardrails flagged this draft for review"
        evidence = {"violations": row.violations}
        line_index = None
    else:
        draft = EstimateDraft.model_validate(row.draft)
        lines = build_evidence(session, graph, draft, as_of)
        raw = llm_client.score([asdict(line) for line in lines], JUDGE_SYSTEM_PROMPT)
        scored = [ScoredDimension(name=d.name, score=d.score, rationale=d.rationale) for d in raw.dimensions]
        overall, flagged = rollup(scored)
        dimensions = [
            DimensionScore(name=d.name, score=d.score, rationale=d.rationale, evidence=_dimension_evidence(d.name, lines))
            for d in scored
        ]
        verdict = JudgeVerdict(
            estimate_id=estimate_id, model=JUDGE_MODEL, dimensions=dimensions, overall_confidence=overall,
            flagged_dimension=flagged, trusted=gate(overall, current_threshold()),
        )
        flagged_score = next(d for d in dimensions if d.name == flagged)
        fact = flagged_score.rationale
        evidence = {"dimension": flagged, "lines": flagged_score.evidence}
        line_index = flagged_score.evidence[0]["line_index"] if len(flagged_score.evidence) == 1 else None

    verdict_row = save_judge_verdict(
        session, estimate_id=verdict.estimate_id, model=verdict.model,
        dimensions=[d.model_dump() for d in verdict.dimensions], overall_confidence=verdict.overall_confidence,
        flagged_dimension=verdict.flagged_dimension, trusted=verdict.trusted,
    )
    review_item = None
    if not verdict.trusted:
        save_review_item(
            session, judge_verdict_id=verdict_row.id, estimate_id=estimate_id, dimension=verdict.flagged_dimension,
            fact=fact, evidence=evidence, line_index=line_index,
        )
        review_item = ReviewItem(dimension=verdict.flagged_dimension, fact=fact, evidence=evidence, line_index=line_index)

    return JudgeRunResult(verdict=verdict, verdict_id=verdict_row.id, review_item=review_item)


def resolve_review_item(
    session: Session, review_item_id: uuid.UUID, outcome: str, correction: dict | None,
) -> ReviewItemResolution:
    row = get_review_item(session, review_item_id)
    if row is None:
        raise ReviewItemNotFound(f"review item {review_item_id} not found")
    if row.status != "open":
        raise ReviewItemAlreadyResolved(f"review item {review_item_id} is already {row.status!r}")
    if row.dimension not in RESOLVABLE_DIMENSIONS:
        raise ReviewItemNotResolvable(f"dimension {row.dimension!r} is not resolvable through this endpoint")
    if outcome == "corrected":
        validate_correction(session, row.dimension, correction, row.evidence)

    row.status = outcome
    row.outcome = outcome
    row.correction = correction if outcome == "corrected" else None
    row.resolved_at = datetime.now(timezone.utc)
    session.flush()

    case = build_eval_case(row, outcome, next_eval_case_id(session))
    save_eval_case(session, case)

    return ReviewItemResolution(row=row, eval_case=case, consolidation_required=outcome == "corrected")
