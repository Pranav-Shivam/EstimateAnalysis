from functools import lru_cache

from neo4j import GraphDatabase, Query, RoutingControl
from neo4j.exceptions import AuthError, Neo4jError, ServiceUnavailable, SessionExpired

from core.config.settings import Settings

DATABASE = "neo4j"
CONNECTION_TIMEOUT_SECONDS = 5
QUERY_TIMEOUT_SECONDS = 30
# A fail-closed guardrail must learn about an outage in seconds, not the driver's 30s default.
MAX_RETRY_SECONDS = 3


class GraphError(Exception):
    pass


class GraphUnavailable(GraphError):
    pass


class GraphQueryFailed(GraphError):
    pass


class GraphClient:
    def __init__(self, uri: str, user: str, password: str) -> None:
        # Notifications off: GDS emits deprecation notices on some procedures that would flood the log.
        self._driver = GraphDatabase.driver(
            uri, auth=(user, password), connection_timeout=CONNECTION_TIMEOUT_SECONDS,
            max_transaction_retry_time=MAX_RETRY_SECONDS, notifications_min_severity="OFF",
        )

    def read(self, query: str, **params) -> list[dict]:
        return self._execute(query, params, RoutingControl.READ)

    def write(self, query: str, **params) -> list[dict]:
        return self._execute(query, params, RoutingControl.WRITE)

    def close(self) -> None:
        self._driver.close()

    def _execute(self, query: str, params: dict, routing: RoutingControl) -> list[dict]:
        try:
            result = self._driver.execute_query(
                Query(query, timeout=QUERY_TIMEOUT_SECONDS), parameters_=params, routing_=routing, database_=DATABASE,
            )
        except (ServiceUnavailable, SessionExpired, AuthError, OSError) as exc:
            raise GraphUnavailable(f"Neo4j is unavailable: {exc}") from exc
        except Neo4jError as exc:
            raise GraphQueryFailed(f"Neo4j query failed: {exc}") from exc
        return [record.data() for record in result.records]


@lru_cache
def get_graph_client() -> GraphClient:
    settings = Settings()
    return GraphClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)


def get_graph_namespace() -> str:
    return Settings().graph_namespace
