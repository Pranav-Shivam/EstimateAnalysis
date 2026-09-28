from collections.abc import Iterator

from app.graph.constant import BATCH_SIZE, EDGE_TYPES, MAX_CHAIN_HOPS, NODE_LABELS
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


def fetch_sku_chain(client: GraphClient, ns: str, sku_id: str) -> list[dict] | None:
    """The longest REPLACED_BY path (at most MAX_CHAIN_HOPS hops) from a SKU, as node dicts. Relationships are
    never repeated inside a path, so a cycle ends the walk instead of looping."""
    rows = client.read(
        f"MATCH path = (s:SKU {{key: $key}})-[:REPLACED_BY*0..{MAX_CHAIN_HOPS}]->(e:SKU) "
        "RETURN [n IN nodes(path) | {id: n.id, name: n.name, discontinued: n.discontinued, in_stock: n.in_stock}] "
        "AS chain ORDER BY length(path) DESC LIMIT 1",
        key=node_key(ns, sku_id),
    )
    return rows[0]["chain"] if rows else None


def fetch_required_parts(client: GraphClient, ns: str, sku_id: str) -> list[dict]:
    return client.read(
        "MATCH (s:SKU {key: $key})-[:REQUIRES]->(r:SKU) "
        "RETURN r.id AS id, r.name AS name, r.discontinued AS discontinued, r.in_stock AS in_stock ORDER BY r.id",
        key=node_key(ns, sku_id),
    )


def fetch_contract_coverage(client: GraphClient, ns: str, customer_id: str, sku_id: str) -> list[dict]:
    return client.read(
        "MATCH (c:Customer {key: $customer_key})-[:HOLDS]->(k:Contract) "
        "OPTIONAL MATCH (s:SKU {key: $sku_key})-[:PRICED_IN]->(sc:PricingCategory) "
        "RETURN k.id AS contract_id, k.discount_pct AS discount_pct, k.effective_from AS effective_from, "
        "k.effective_to AS effective_to, sc.id AS sku_category, "
        "COLLECT { MATCH (k)-[:COVERS]->(x:PricingCategory) RETURN x.id ORDER BY x.id } AS covered_categories, "
        "(sc IS NOT NULL AND EXISTS { (k)-[:COVERS]->(sc) }) AS covered ORDER BY k.id",
        customer_key=node_key(ns, customer_id), sku_key=node_key(ns, sku_id),
    )


def fetch_fingerprint(client: GraphClient, ns: str) -> str | None:
    rows = client.read(
        "MATCH (m:GraphMeta {key: $key}) RETURN m.reference_fingerprint AS fingerprint", key=node_key(ns, ns),
    )
    return rows[0]["fingerprint"] if rows else None
