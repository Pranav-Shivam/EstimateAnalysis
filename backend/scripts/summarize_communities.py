import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI

from app.graph.service import global_stats
from app.retrieval.summarizer import run_summary_job
from core.config.settings import Settings
from core.db.session import make_engine, make_session_factory
from core.graph.client import get_graph_client
from core.llm.openai_summary_client import OpenAISummaryClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize graph communities with an LLM (dry run unless --yes)")
    parser.add_argument("--yes", action="store_true", help="actually call the OpenAI API (costs money)")
    args = parser.parse_args()

    settings = Settings()
    session = make_session_factory(make_engine(settings.database_url))()
    try:
        stats = global_stats(get_graph_client(), settings.graph_namespace)
        if not stats:
            print("no communities found; run POST /v1/graph/rebuild first")
            return
        run_summary_job(
            session, stats, lambda: OpenAISummaryClient(client=OpenAI(api_key=settings.openai_api_key)),
            yes=args.yes, out=print, on_saved=session.commit,
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
