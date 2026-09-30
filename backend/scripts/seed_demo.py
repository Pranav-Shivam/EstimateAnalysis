import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select

from app.estimate.constant import DATASET_AS_OF
from app.intake.models import QuoteRequestRow
from app.reference_data.repository import all_customers
from core.config.settings import Settings
from core.db.session import make_engine, make_session_factory
from core.graph.client import GraphError, get_graph_client
from demo.fakes import DemoSetupError
from demo.scenarios import select_cases
from demo.seed import DemoExpectationFailed, pending_replays, replay, seed

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed the demo quotes through the real services with scripted LLM stand-ins "
        "(dry run unless --yes; --replay re-runs quotes whose flag has been resolved)",
    )
    parser.add_argument("--yes", action="store_true", help="write to the database and the graph")
    parser.add_argument("--replay", action="store_true", help="re-run estimate and judge for resolved quotes")
    return parser.parse_args(argv)


def _load(name: str):
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = Settings()
    session = make_session_factory(make_engine(settings.database_url))()
    try:
        if not all_customers(session):
            print("no reference data: run `python scripts/load_data.py` first", file=sys.stderr)
            return 1
        seeded_count = session.scalar(
            select(func.count()).select_from(QuoteRequestRow).where(QuoteRequestRow.case_id.is_not(None))
        )

        if args.replay:
            pending = pending_replays(session)
            print(f"{len(pending)} seeded quote(s) ready to replay: {', '.join(pending) or 'none'}")
            if not args.yes:
                print("dry run: pass --yes to replay")
                return 0
            client = get_graph_client()
            for result in replay(session, client, settings.graph_namespace):
                verdict = "trusted" if result.trusted else f"flagged ({result.review_dimension})"
                print(f"{result.case_id}: new estimate {result.estimate_id} is {verdict}")
            return 0

        if seeded_count:
            print(
                f"{seeded_count} seeded quote(s) already exist; use --replay after resolving them in the UI",
                file=sys.stderr,
            )
            return 1
        cases = select_cases(session, _load("scenarios.json"), _load("catalog.json"), DATASET_AS_OF)
        for case in cases:
            print(f"{case.role:14} {case.case_id}  expect {case.expectation}")
        if not args.yes:
            print("dry run: pass --yes to seed (this plants a graph gap and writes quotes)")
            return 0
        seeded = seed(session, get_graph_client(), settings.graph_namespace, cases, _load("scenarios.json"))
        print(f"seeded {len(seeded)} quote(s)")
        return 0
    except (DemoSetupError, DemoExpectationFailed, GraphError) as exc:
        print(f"seed failed: {exc}", file=sys.stderr)
        print(
            "a failed seed can leave quotes and planted gaps behind: reload the reference data with "
            "scripts/load_data.py and delete the quote_requests rows with a case_id before seeding again",
            file=sys.stderr,
        )
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
