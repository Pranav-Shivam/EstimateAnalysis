import asyncio
import uuid

import procrastinate
from sqlalchemy.exc import OperationalError

from app.consolidation.constant import CONSOLIDATION_MAX_ATTEMPTS, CONSOLIDATION_RETRY_EXPONENTIAL_WAIT
from app.consolidation.service import consolidate_review_item
from core.config.settings import Settings
from core.db.session import app_session_factory
from core.graph.client import get_graph_client, get_graph_namespace


def _conninfo(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://")


# One App serves both processes. The worker opens it async (run_worker), which the async connector needs to fetch
# and run jobs. The API opens it sync (main.py lifespan); an async connector that was never opened async hands
# sync callers its own SyncPsycopgConnector, so .defer() from a sync route writes through a sync pool.
app = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=_conninfo(Settings().database_url)))


@app.task(
    name="consolidate_review_item",
    retry=procrastinate.RetryStrategy(
        max_attempts=CONSOLIDATION_MAX_ATTEMPTS, exponential_wait=CONSOLIDATION_RETRY_EXPONENTIAL_WAIT,
        retry_exceptions=[OperationalError],
    ),
)
def consolidate_review_item_task(review_item_id: str) -> None:
    session = app_session_factory()()
    try:
        consolidate_review_item(session, get_graph_client(), get_graph_namespace(), uuid.UUID(review_item_id))
        session.commit()
    finally:
        session.close()


def run_worker(**options) -> None:
    """App.run_worker on a selector event loop. App.run_worker uses asyncio.run's default loop, which on Windows
    is the Proactor loop that psycopg's async pool refuses to run on. SelectorEventLoop works on every platform,
    and a Runner scopes the choice to this call instead of changing the process-wide loop policy."""

    async def _run() -> None:
        async with app.open_async():
            await app.run_worker_async(**options)

    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(_run())
