from collections.abc import Iterator

from app.graph.constant import BATCH_SIZE, EDGE_TYPES, NODE_LABELS
from core.graph.client import GraphClient


def node_key(ns: str, node_id: str) -> str:
    return f"{ns}:{node_id}"


def _require(name: str, allowed: tuple[str, ...], kind: str) -> None:
    # Labels and relationship types cannot be Cypher parameters, so they are interpolated. Only known names pass.
    if name not in allowed:
        raise ValueError(f"unknown graph {kind} {name!r}")


def _batches(rows: list[dict]) -> Iterator[list[dict]]:
    for start in range(0, len(rows), BATCH_SIZE):
        yield rows[start:start + BATCH_SIZE]


def drop_namespace(client: GraphClient, ns: str) -> None:
    client.write("MATCH (n {ns: $ns}) DETACH DELETE n", ns=ns)


def ensure_constraints(client: GraphClient) -> None:
    # Community edition has no composite node keys, so uniqueness is enforced on the namespaced `key` property.
    for label in NODE_LABELS:
        client.write(f"CREATE CONSTRAINT {label.lower()}_key IF NOT EXISTS FOR (n:{label}) REQUIRE n.key IS UNIQUE")


def merge_nodes(client: GraphClient, ns: str, label: str, rows: list[dict]) -> None:
    _require(label, NODE_LABELS, "label")
    query = f"UNWIND $rows AS row MERGE (n:{label} {{key: row.key}}) SET n.ns = $ns, n.id = row.id SET n += row.props"
    for batch in _batches(rows):
        client.write(
            query, ns=ns,
            rows=[{"key": node_key(ns, r["id"]), "id": r["id"], "props": r["props"]} for r in batch],
        )


def merge_edges(
    client: GraphClient, ns: str, edge_type: str, from_label: str, to_label: str, rows: list[dict],
) -> None:
    _require(edge_type, EDGE_TYPES, "edge type")
    _require(from_label, NODE_LABELS, "label")
    _require(to_label, NODE_LABELS, "label")
    query = (
        f"UNWIND $rows AS row MATCH (a:{from_label} {{key: row.source}}) MATCH (b:{to_label} {{key: row.target}}) "
        f"MERGE (a)-[r:{edge_type}]->(b) SET r += row.props"
    )
    for batch in _batches(rows):
        client.write(
            query,
            rows=[{"source": node_key(ns, r["from"]), "target": node_key(ns, r["to"]), "props": r["props"]} for r in batch],
        )


def count_nodes_by_label(client: GraphClient, ns: str) -> dict[str, int]:
    rows = client.read(
        "MATCH (n {ns: $ns}) UNWIND labels(n) AS label RETURN label, count(n) AS count ORDER BY label", ns=ns,
    )
    return {row["label"]: row["count"] for row in rows}


def count_edges_by_type(client: GraphClient, ns: str) -> dict[str, int]:
    rows = client.read(
        "MATCH ({ns: $ns})-[r]->() RETURN type(r) AS type, count(r) AS count ORDER BY type", ns=ns,
    )
    return {row["type"]: row["count"] for row in rows}
