import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI

from app.retrieval.vector import run_embedding_job
from core.config.settings import Settings
from core.db.session import make_engine, make_session_factory
from core.llm.openai_embedding_client import OpenAIEmbeddingClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Embed SKU names for vector search (dry run unless --yes)")
    parser.add_argument("--yes", action="store_true", help="actually call the OpenAI API (costs money)")
    args = parser.parse_args()

    settings = Settings()
    session = make_session_factory(make_engine(settings.database_url))()
    try:
        run_embedding_job(
            session, lambda: OpenAIEmbeddingClient(client=OpenAI(api_key=settings.openai_api_key)),
            yes=args.yes, out=print, on_batch_saved=session.commit,
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
