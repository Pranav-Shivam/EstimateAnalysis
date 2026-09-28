import re
from dataclasses import dataclass
from enum import Enum


class Route(str, Enum):
    SQL = "sql"
    GRAPH_LOCAL = "graph_local"
    GRAPH_GLOBAL = "graph_global"
    VECTOR = "vector"


@dataclass(frozen=True)
class RouteDecision:
    route: Route
    rule: str
    entity_id: str | None


ID_PATTERN = re.compile(r"\b(?:SKU|CUST|CTR|SITE|PRJ|FAM)-[A-Z0-9]+(?:-[A-Z0-9]+)*\b", re.IGNORECASE)
# The ids that have a plain Postgres lookup. Sites, projects and families exist only as graph nodes.
SQL_ID_PREFIXES = ("SKU", "CUST", "CTR")
PORTFOLIO = re.compile(
    r"\b(?:which product groups|product groups|across the catalog|most exposed|portfolio|clusters|communities|"
    r"themes|biggest groups|catalog overview)\b",
    re.IGNORECASE,
)
SIMILARITY = re.compile(
    r"\b(?:similar to|alternatives? to|something like|something for|equivalent to|comparable to|looks like)\b",
    re.IGNORECASE,
)
RELATIONSHIP = re.compile(
    r"\b(?:replac\w*|require\w*|goes with|covers?|covered|contracts?|connected|related|neighbou?rs|linked)\b",
    re.IGNORECASE,
)


def route_question(question: str) -> RouteDecision:
    """Pick where a question is answered. Free and deterministic; the precedence is the design: portfolio phrasing,
    then similarity, then an id with relationship phrasing, then an id, then a name."""
    match = ID_PATTERN.search(question)
    entity_id = match.group(0).upper() if match else None

    if PORTFOLIO.search(question):
        return RouteDecision(Route.GRAPH_GLOBAL, "portfolio_phrasing", entity_id)
    if SIMILARITY.search(question):
        return RouteDecision(Route.VECTOR, "similarity_phrasing", entity_id)
    if entity_id and RELATIONSHIP.search(question):
        return RouteDecision(Route.GRAPH_LOCAL, "id_with_relationship_phrasing", entity_id)
    if entity_id:
        if entity_id.split("-")[0] in SQL_ID_PREFIXES:
            return RouteDecision(Route.SQL, "id_lookup", entity_id)
        return RouteDecision(Route.GRAPH_LOCAL, "non_sql_id", entity_id)
    return RouteDecision(Route.SQL, "name_search", None)
