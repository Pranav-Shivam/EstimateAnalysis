"""One-shot setup for `docker compose up`. Safe to run on every start: each step first checks whether its work is
already done, so a second start changes nothing.

Order: schema migrations, reference data plus the saved LLM output (no API call), the demo quotes, then the graph.
The demo seed is skipped once seeded quotes exist, because seeding twice leaves planted gaps behind."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

import load_data
import restore_llm_data
import seed_demo
from app.estimate.guardrails import graph_is_current
from app.graph.reader import GraphReader
from app.graph.service import rebuild_graph, run_communities
from app.intake.models import QuoteRequestRow
from app.reference_data.repository import all_customers
from core.config.settings import Settings
from core.db.session import make_engine, make_session_factory
from core.graph.client import get_graph_client

BACKEND_DIR = Path(__file__).resolve().parent.parent


def main() -> int:
    settings = Settings()
    print("applying migrations")
    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")

    session = make_session_factory(make_engine(settings.database_url))()
    try:
        has_reference_data = bool(all_customers(session))
        has_demo_quotes = bool(session.scalar(
            select(func.count()).select_from(QuoteRequestRow).where(QuoteRequestRow.case_id.is_not(None))
        ))
    finally:
        session.close()

    changed = False
    if has_reference_data:
        print("reference data already loaded")
    else:
        load_data.run()
        restore_llm_data.main()
        changed = True
    if has_demo_quotes:
        print("demo quotes already seeded")
    else:
        if seed_demo.main(["--yes"]) != 0:
            return 1
        changed = True

    client = get_graph_client()
    session = make_session_factory(make_engine(settings.database_url))()
    try:
        reader = GraphReader(client, settings.graph_namespace)
        if changed or not graph_is_current(session, reader):
            print("rebuilding the knowledge graph")
            rebuild_graph(session, client, settings.graph_namespace)
            run_communities(client, settings.graph_namespace)
        else:
            print("knowledge graph already current")
    finally:
        session.close()
    print("setup complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
