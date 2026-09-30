"""Runs the real GPT-4o intake and estimate agent over the 60 synthetic emails and scores the results against the
scenario answer key. Dry run unless --yes; --yes spends real OpenAI money up to --cap-usd, then stops.

Everything happens in one database transaction that is rolled back at the end, and nothing is synced to the graph,
so the dev database and the seeded demo are left exactly as they were. The report is written to
data/live_run_report.json."""
import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI

from app.dedupe.service import run_dedupe
from app.estimate.constant import DATASET_AS_OF
from app.estimate.guardrails import graph_is_current
from app.estimate.service import run_estimate
from app.graph.reader import GraphReader
from app.intake.service import process_email
from core.config.settings import Settings
from core.db.session import make_engine, make_session_factory
from core.graph.client import get_graph_client
from core.llm.openai_agent_client import AgentError, OpenAIAgentClient
from core.llm.openai_client import ExtractionError, OpenAIExtractionClient
from core.llm.openai_embedding_client import OpenAIEmbeddingClient
from core.tracing.langfuse_client import TracingClient
from scripts.live_run.expectation import build_expectation
from scripts.live_run.meter import PRICES_PER_MILLION, UsageMeter, metered_openai
from scripts.live_run.scoring import (
    AGENT_SCENARIO_TYPES, CORRECT, CORRECT_FLAGGED, WRONG_READY, DraftView, classify_outcome, dedupe_pairs, score_extraction,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REPORT_PATH = DATA_DIR / "live_run_report.json"
DEFAULT_CAP_USD = 5.0
# Rough per-call sizes used only for the dry-run estimate; the live run reports measured numbers instead.
ASSUMED_EXTRACTION_TOKENS = (400, 150)
ASSUMED_AGENT_RUN_TOKENS = (21_000, 1_000)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Live GPT-4o intake and agent run over the scenarios (dry run unless --yes)")
    parser.add_argument("--yes", action="store_true", help="actually call OpenAI (costs money)")
    parser.add_argument("--cap-usd", type=float, default=DEFAULT_CAP_USD, help="stop once this much has been spent")
    parser.add_argument("--agent-cases-per-type", type=int, default=10, help="agent runs per scenario type (max 10)")
    return parser.parse_args(argv)


def select_agent_cases(scenarios: list[dict], per_type: int) -> list[dict]:
    """Round-robin across types, so a run that hits the cap early still covers every type evenly."""
    by_type = {t: [s for s in scenarios if s["scenario_type"] == t][:per_type] for t in AGENT_SCENARIO_TYPES}
    ordered = []
    for index in range(per_type):
        ordered.extend(cases[index] for cases in by_type.values() if index < len(cases))
    return ordered


def estimate_cost_usd(extraction_calls: int, agent_runs: int) -> float:
    def call_cost(model: str, tokens: tuple[int, int]) -> float:
        price_in, price_out = PRICES_PER_MILLION[model]
        return (tokens[0] * price_in + tokens[1] * price_out) / 1_000_000

    return (
        extraction_calls * call_cost("gpt-4o", ASSUMED_EXTRACTION_TOKENS)
        + agent_runs * call_cost("gpt-4o", ASSUMED_AGENT_RUN_TOKENS)
    )


def _draft_view(result) -> DraftView:
    lines = result.draft.lines if result.draft else []
    flagged = bool(result.draft and result.draft.flags and not result.violations)
    return DraftView(result.status, {line.sku_id: line.discount_pct for line in lines if line.sku_id}, flagged)


def run_intake_and_dedupe(session, scenarios, extraction_client, meter, report) -> dict:
    rows = {}
    for scenario in scenarios:
        if meter.spent_usd >= meter.cap_usd:
            break
        started, spent_before = time.perf_counter(), meter.spent_usd
        try:
            result = process_email(session, scenario["email_text"], extraction_client)
        except ExtractionError as exc:
            report["cases"][scenario["case_id"]] = {"type": scenario["scenario_type"], "extraction_error": str(exc)}
            continue
        row = result.row
        rows[scenario["case_id"]] = row
        resolved = [item.sku_id for item in result.resolved_line_items if item.sku_id]
        report["cases"][scenario["case_id"]] = {
            "type": scenario["scenario_type"],
            **score_extraction(scenario["entities"], row.customer_id, resolved),
            "customer_as_written": row.parsed_json["extraction"]["customer_name_as_written"],
            "sku_names_as_written": [item.sku_name_as_written for item in result.resolved_line_items],
            "resolved_sku_ids": resolved,
            "extraction_seconds": round(time.perf_counter() - started, 2),
            "extraction_usd": round(meter.spent_usd - spent_before, 5),
        }
    session.flush()

    for later, earlier, expected in dedupe_pairs(scenarios):
        if later not in rows or earlier not in rows:
            continue
        verdicts = run_dedupe(session, rows[later].id, TracingClient(None))
        against_earlier = [v for v in verdicts if v.candidate_quote_request_id == rows[earlier].id]
        got = against_earlier[0].verdict if against_earlier else None
        report["cases"][later]["dedupe"] = {"expected": expected, "got": got, "ok": got == expected}
    return rows


def run_agents(session, agent_cases, rows, agent_client, reader, embedder, meter, report) -> str | None:
    for scenario in agent_cases:
        case_id = scenario["case_id"]
        if case_id not in rows:
            continue
        # The clients wrap every exception from a call, so a cap hit inside one surfaces as an AgentError. Checking
        # here, between cases, is what actually ends the run.
        if meter.spent_usd >= meter.cap_usd:
            return f"spent ${meter.spent_usd:.4f}, cap is ${meter.cap_usd:.2f}"
        started, spent_before = time.perf_counter(), meter.spent_usd
        try:
            run = run_estimate(session, rows[case_id].id, DATASET_AS_OF, agent_client, reader, embedder, TracingClient(None))
        except AgentError as exc:
            report["cases"][case_id]["agent_error"] = str(exc)
            continue
        view = _draft_view(run.result)
        report["cases"][case_id]["agent"] = {
            "status": run.result.status, "iterations": run.result.iterations, "reason": run.result.reason,
            "violations": [v.guardrail for v in run.result.violations],
            "flags": run.result.draft.flags if run.result.draft else [],
            "draft_skus": sorted(view.skus),
            "outcome": classify_outcome(view, build_expectation(session, scenario)),
            "seconds": round(time.perf_counter() - started, 2), "usd": round(meter.spent_usd - spent_before, 5),
        }
    return None


def summarize(report: dict) -> dict:
    extraction = [c for c in report["cases"].values() if "customer_ok" in c]
    agent_by_type: dict[str, Counter] = defaultdict(Counter)
    for case in report["cases"].values():
        if "agent" in case:
            agent_by_type[case["type"]][case["agent"]["outcome"]] += 1
    dedupe = [c["dedupe"] for c in report["cases"].values() if "dedupe" in c]
    return {
        "extraction_customer_ok": f"{sum(c['customer_ok'] for c in extraction)}/{len(extraction)}",
        "extraction_skus_ok": f"{sum(c['skus_ok'] for c in extraction)}/{len(extraction)}",
        "dedupe_pairs_ok": f"{sum(d['ok'] for d in dedupe)}/{len(dedupe)}",
        "agent_outcomes_by_type": {t: dict(counts) for t, counts in agent_by_type.items()},
        "agent_correct": sum(c[CORRECT] for c in agent_by_type.values()),
        "agent_correct_flagged": sum(c[CORRECT_FLAGGED] for c in agent_by_type.values()),
        "agent_wrong_ready": sum(c[WRONG_READY] for c in agent_by_type.values()),
        "agent_runs": sum(sum(c.values()) for c in agent_by_type.values()),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    scenarios = json.loads((DATA_DIR / "scenarios.json").read_text(encoding="utf-8"))
    agent_cases = select_agent_cases(scenarios, min(args.agent_cases_per_type, 10))
    expected_usd = estimate_cost_usd(len(scenarios), len(agent_cases))
    print(f"{len(scenarios)} intake calls, {len(agent_cases)} agent runs ({', '.join(AGENT_SCENARIO_TYPES)})")
    print(f"assumed cost about ${expected_usd:.2f} (an assumption, not a measurement); cap ${args.cap_usd:.2f}")
    if not args.yes:
        print("dry run: pass --yes to call OpenAI")
        return 0

    settings = Settings()
    meter = UsageMeter(cap_usd=args.cap_usd)
    # The org has a tokens-per-minute limit; the SDK backs off and retries a 429 instead of failing the case.
    openai = metered_openai(OpenAI(api_key=settings.openai_api_key, max_retries=10), meter)
    graph_client = get_graph_client()
    reader = GraphReader(graph_client, settings.graph_namespace)
    session = make_session_factory(make_engine(settings.database_url))()
    report = {"date": date.today().isoformat(), "cap_usd": args.cap_usd, "cases": {}}
    stopped = None
    try:
        if not graph_is_current(session, reader):
            print("the knowledge graph is stale: POST /v1/graph/rebuild first", file=sys.stderr)
            return 1
        rows = run_intake_and_dedupe(session, scenarios, OpenAIExtractionClient(client=openai), meter, report)
        stopped = run_agents(
            session, agent_cases, rows, OpenAIAgentClient(client=openai), reader,
            OpenAIEmbeddingClient(client=openai), meter, report,
        )
    finally:
        session.rollback()
        session.close()

    report["stopped_at_cap"] = stopped
    report["spent_usd"] = round(meter.spent_usd, 4)
    report["stages"] = {name: asdict(totals) for name, totals in meter.stages.items()}
    report["summary"] = summarize(report)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print(f"spent ${meter.spent_usd:.4f}" + (f"; stopped early: {stopped}" if stopped else "") + f"; wrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
