import uuid

import procrastinate

from app.consolidation.service import consolidate_review_item
from core.config.settings import Settings
from core.db.session import make_engine, make_session_factory
from core.graph.client import get_graph_client, get_graph_namespace


def _conninfo(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://")


app = procrastinate.App(connector=procrastinate.SyncPsycopgConnector(conninfo=_conninfo(Settings().database_url)))


@app.task(name="consolidate_review_item")
def consolidate_review_item_task(review_item_id: str) -> None:
    session = make_session_factory(make_engine(Settings().database_url))()
    try:
        consolidate_review_item(session, get_graph_client(), get_graph_namespace(), uuid.UUID(review_item_id))
        session.commit()
    finally:
        session.close()
