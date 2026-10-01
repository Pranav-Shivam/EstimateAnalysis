import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.consolidation.service import consolidate_review_item
from app.dedupe.service import run_dedupe
from app.estimate.constant import DATASET_AS_OF
from app.estimate.service import run_estimate
from app.graph.reader import GraphReader
from app.graph.service import rebuild_reference_graph
from app.intake.models import QuoteRequestRow
from app.intake.service import process_email
from app.judge.service import resolve_review_item, run_judge
from app.quotes.repository import estimates_for_requests, review_items_for_estimates
from app.reference_data.models import Sku, SkuRequirement
from core.graph.client import GraphClient
from core.tracing.langfuse_client import TracingClient
from demo.fakes import (
    DemoJudgeClient, DemoSetupError, ScriptedAgentClient, ScriptedExtractionClient, UnusedEmbedder, blocked_draft,
    build_draft,
)
from demo.scenarios import DemoCase

EXPECTED_DEDUPE_VERDICTS = {"duplicate_b": "DUPLICATE_OF", "revision_b": "REVISION_OF"}
RESOLVED_STATUSES = ("corrected", "consolidated")


class DemoExpectationFailed(Exception):
    """A scenario did not behave the way its role promises. The demo dataset or the fakes need attention."""


@dataclass(frozen=True)
class SeededCase:
    case: DemoCase
    quote_request_id: uuid.UUID
    estimate_id: uuid.UUID
    trusted: bool
    review_dimension: str | None


@dataclass(frozen=True)
class ReplayResult:
    case_id: str
    estimate_id: uuid.UUID
    trusted: bool
    review_dimension: str | None


def plant_gaps(session: Session, cases: list[DemoCase]) -> None:
    """Removes what the reviewer will later supply: the price_gap SKU's list price and the requirement the
    graph_gap scenario is about. The contract gap already exists in the dataset."""
    for case in cases:
        if case.price_gap is not None:
            sku = session.get(Sku, case.price_gap)
            if sku is None or sku.list_price is None:
                raise DemoSetupError(
                    f"{case.price_gap} is already unpriced: reload the reference data with scripts/load_data.py"
                )
            sku.list_price = None
        if case.graph_gap is not None:
            requirement = session.get(SkuRequirement, case.graph_gap)
            if requirement is None:
                raise DemoSetupError(
                    f"requirement {case.graph_gap} is already gone: reload the reference data with scripts/load_data.py"
                )
            session.delete(requirement)
    session.flush()


def _check(case: DemoCase, status: str, trusted: bool, dimension: str | None, dedupe_verdicts: list[str]) -> None:
    if case.expectation == "trusted":
        ok = status == "ready" and trusted
    elif case.expectation == "guardrail":
        ok = status == "needs_review" and dimension == "guardrail"
    else:
        ok = status == "ready" and not trusted and dimension == case.expectation.split(":", 1)[1]
    wanted = EXPECTED_DEDUPE_VERDICTS.get(case.role)
    if wanted is not None and wanted not in dedupe_verdicts:
        raise DemoExpectationFailed(f"{case.case_id} ({case.role}) expected a {wanted} verdict, got {dedupe_verdicts}")
    if not ok:
        raise DemoExpectationFailed(
            f"{case.case_id} ({case.role}) expected {case.expectation!r} but got status={status!r} "
            f"trusted={trusted} dimension={dimension!r}"
        )


def seed(
    session: Session, client: GraphClient, ns: str, cases: list[DemoCase], scenarios: list[dict],
) -> list[SeededCase]:
    plant_gaps(session, cases)
    rebuild_reference_graph(session, client, ns)
    session.commit()

    reader = GraphReader(client, ns)
    extraction = ScriptedExtractionClient(scenarios)
    judge = _seed_judge(cases)
    tracing = TracingClient(None)

    seeded = []
    for case in cases:
        request, dedupe, estimate, judged = _run_scenario(
            session, reader, extraction, judge, tracing, case.scenario, blocked=case.role == "blocked",
        )
        dimension = judged.review_item.dimension if judged.review_item else None
        _check(case, estimate.result.status, judged.verdict.trusted, dimension, [v.verdict for v in dedupe])
        seeded.append(SeededCase(case, request.id, estimate.row.id, judged.verdict.trusted, dimension))
    return seeded


def seed_remaining(session: Session, client: GraphClient, ns: str, cases: list[DemoCase], scenarios: list[dict]) -> int:
    """Runs every scenario `seed` did not pick through the same pipeline, so the app holds the whole dataset. These
    quotes carry no expected outcome: each lands wherever the scripted stand-ins and the planted gaps take it."""
    seeded_ids = set(session.scalars(select(QuoteRequestRow.case_id).where(QuoteRequestRow.case_id.is_not(None))))
    reader = GraphReader(client, ns)
    extraction = ScriptedExtractionClient(scenarios)
    judge = _seed_judge(cases)
    tracing = TracingClient(None)
    remaining = [scenario for scenario in scenarios if scenario["case_id"] not in seeded_ids]
    for scenario in remaining:
        _run_scenario(session, reader, extraction, judge, tracing, scenario, blocked=False)
    return len(remaining)


def _seed_judge(cases: list[DemoCase]) -> DemoJudgeClient:
    return DemoJudgeClient(
        graph_watch={c.graph_gap[0] for c in cases if c.graph_gap},
        contract_watch={c.scenario["entities"]["sku_id"] for c in cases if c.role == "contract_gap"},
    )


def _run_scenario(
    session: Session, reader: GraphReader, extraction: ScriptedExtractionClient, judge: DemoJudgeClient,
    tracing: TracingClient, scenario: dict, blocked: bool,
):
    """Intake, dedupe, estimate and judge for one scenario email, committing after each stage as production does."""
    request = process_email(session, scenario["email_text"], extraction, case_id=scenario["case_id"]).row
    session.commit()
    dedupe = run_dedupe(session, request.id, tracing)
    session.commit()

    draft = build_draft(session, reader, request, DATASET_AS_OF)
    agent = ScriptedAgentClient(blocked_draft(draft) if blocked else draft)
    estimate = run_estimate(session, request.id, DATASET_AS_OF, agent, reader, UnusedEmbedder(), tracing)
    session.commit()
    judged = run_judge(session, reader, DATASET_AS_OF, estimate.row.id, judge)
    session.commit()
    return request, dedupe, estimate, judged


def _seeded_requests(session: Session) -> list[QuoteRequestRow]:
    return list(session.scalars(
        select(QuoteRequestRow).where(QuoteRequestRow.case_id.is_not(None))
        .order_by(QuoteRequestRow.created_at, QuoteRequestRow.id)
    ))


def _latest_items(session: Session, request: QuoteRequestRow):
    estimates = estimates_for_requests(session, [request.id])
    if not estimates:
        return None, []
    return estimates[0], review_items_for_estimates(session, [estimates[0].id])


def _needs_replay(items) -> bool:
    """A seeded quote whose latest estimate was flagged and has since been resolved, with nothing left open."""
    return (
        bool(items) and not any(item.status == "open" for item in items)
        and any(item.status in RESOLVED_STATUSES for item in items)
    )


def pending_replays(session: Session) -> list[str]:
    return [
        request.case_id for request in _seeded_requests(session)
        if _needs_replay(_latest_items(session, request)[1])
    ]


def _apply_planned_corrections(session: Session, cases: list[DemoCase]) -> None:
    """What a reviewer does in the UI, done in code: resolve each flagged item with the case's correction."""
    planned = {case.case_id: case for case in cases if case.correction is not None}
    for request in _seeded_requests(session):
        case = planned.get(request.case_id)
        if case is None:
            continue
        _, items = _latest_items(session, request)
        for item in items:
            if item.status == "open":
                resolve_review_item(session, item.id, "corrected", case.correction)
        session.commit()


def _replay_judge(items) -> DemoJudgeClient:
    """Watches exactly what the resolved flags were about, so the replayed estimate is trusted only if the
    correction really changed the evidence: a consolidation that wrote nothing leaves the gap visible and the
    judge doubting it again."""
    graph_watch, contract_watch = set(), set()
    for item in items:
        if item.dimension == "graph_completion" and item.correction:
            graph_watch.add(item.correction["sku_id"])
        elif item.dimension == "contract_discount":
            contract_watch.update(
                row["sku_id"] for row in item.evidence.get("lines", []) if row.get("sku_id")
            )
    return DemoJudgeClient(graph_watch=graph_watch, contract_watch=contract_watch)


def replay(session: Session, client: GraphClient, ns: str, cases: list[DemoCase] | None = None) -> list[ReplayResult]:
    """Re-runs estimate and judge for every seeded quote whose flag was resolved. Consolidates inline what the
    procrastinate worker would (a no-op for anything the worker already consolidated). With `cases`, first resolves
    each flagged item with the case's planned correction, so no browser is needed."""
    if cases:
        _apply_planned_corrections(session, cases)

    reader = GraphReader(client, ns)
    tracing = TracingClient(None)
    results = []
    for request in _seeded_requests(session):
        _, items = _latest_items(session, request)
        if not _needs_replay(items):
            continue
        for item in items:
            if item.status == "corrected":
                consolidate_review_item(session, client, ns, item.id)
        session.commit()

        judge = _replay_judge(items)
        draft = build_draft(session, reader, request, DATASET_AS_OF)
        estimate = run_estimate(
            session, request.id, DATASET_AS_OF, ScriptedAgentClient(draft), reader, UnusedEmbedder(), tracing,
        )
        session.commit()
        judged = run_judge(session, reader, DATASET_AS_OF, estimate.row.id, judge)
        session.commit()
        results.append(ReplayResult(
            request.case_id, estimate.row.id, judged.verdict.trusted,
            judged.review_item.dimension if judged.review_item else None,
        ))
    return results
