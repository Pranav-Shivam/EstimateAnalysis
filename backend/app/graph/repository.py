from collections.abc import Iterator

from app.graph.constant import (
    BATCH_SIZE, EDGE_TYPES, HUB_LABELS, LEIDEN_GAMMA, LEIDEN_SEED, LOCAL_MAX_PATHS, MAX_CHAIN_HOPS, NODE_LABELS,
)
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
) -> int:
    """Returns how many rows found both endpoint nodes. A row whose endpoint is missing is skipped silently by
    MATCH, so a caller that must know the edge exists compares this against len(rows)."""
    _require(edge_type, EDGE_TYPES, "edge type")
    _require(from_label, NODE_LABELS, "label")
    _require(to_label, NODE_LABELS, "label")
    query = (
        f"UNWIND $rows AS row MATCH (a:{from_label} {{key: row.source}}) MATCH (b:{to_label} {{key: row.target}}) "
        f"MERGE (a)-[r:{edge_type}]->(b) SET r += row.props RETURN count(r) AS merged"
    )
    merged = 0
    for batch in _batches(rows):
        result = client.write(
            query,
            rows=[{"source": node_key(ns, r["from"]), "target": node_key(ns, r["to"]), "props": r["props"]} for r in batch],
        )
        merged += result[0]["merged"]
    return merged


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


def replace_price_variance(client: GraphClient, ns: str, quote_id: str, rows: list[dict]) -> None:
    """Delete then recreate a quote's PRICE_VARIANCE edges, so a re-sync never duplicates them. Two lines for the
    same SKU stay two edges, which MERGE would collapse."""
    quote_key = node_key(ns, quote_id)
    client.write("MATCH ({key: $key})-[r:PRICE_VARIANCE]->() DELETE r", key=quote_key)
    if rows:
        client.write(
            "UNWIND $rows AS row MATCH (q:Quote {key: $quote_key}) MATCH (s:SKU {key: row.sku_key}) "
            "CREATE (q)-[r:PRICE_VARIANCE]->(s) SET r += row.props",
            quote_key=quote_key,
            rows=[{"sku_key": node_key(ns, r["sku_id"]), "props": r["props"]} for r in rows],
        )


def advance_fingerprint(client: GraphClient, ns: str, expected: str, fingerprint: str, built_at: str) -> bool:
    """Compare-and-set on the stored fingerprint: replaced only while it still equals `expected`. MATCH, not MERGE,
    so a namespace mid-rebuild (GraphMeta dropped, not yet rewritten) is left alone. Setting `_LOCK_` first takes
    the node's write lock before the fingerprint is read (Neo4j's documented lost-update idiom), so two concurrent
    calls cannot both see `expected`; it is removed in the same transaction and never visible."""
    rows = client.write(
        "MATCH (m:GraphMeta {key: $key}) SET m._LOCK_ = true "
        "WITH m, m.reference_fingerprint = $expected AS matches "
        "SET m.reference_fingerprint = CASE WHEN matches THEN $fingerprint ELSE m.reference_fingerprint END, "
        "m.built_at = CASE WHEN matches THEN $built_at ELSE m.built_at END "
        "REMOVE m._LOCK_ RETURN matches",
        key=node_key(ns, ns), expected=expected, fingerprint=fingerprint, built_at=built_at,
    )
    return bool(rows) and rows[0]["matches"]


def fetch_fingerprint(client: GraphClient, ns: str) -> str | None:
    rows = client.read(
        "MATCH (m:GraphMeta {key: $key}) RETURN m.reference_fingerprint AS fingerprint", key=node_key(ns, ns),
    )
    return rows[0]["fingerprint"] if rows else None


def _projection_name(ns: str) -> str:
    return f"leiden-{ns}"


def _drop_projection(client: GraphClient, name: str) -> None:
    client.write("CALL gds.graph.drop($name, false) YIELD graphName RETURN graphName", name=name)


def run_leiden(client: GraphClient, ns: str) -> list[dict]:
    """Leiden over this namespace's SKUs and families. Pricing categories are left out: with five hubs they would
    make every community just a category. Returns [{"key", "label", "community"}]."""
    # Fails fast with GraphQueryFailed when the GDS plugin is missing or broken, before any projection is built.
    client.read("RETURN gds.version() AS version")
    name = _projection_name(ns)
    _drop_projection(client, name)
    try:
        projected = client.write(
            "MATCH (a)-[r:IN_FAMILY|REQUIRES|REPLACED_BY]->(b) WHERE a.ns = $ns AND b.ns = $ns "
            "WITH gds.graph.project($name, a, b, {relationshipType: type(r)}, {undirectedRelationshipTypes: ['*']}) AS g "
            "RETURN g.graphName AS name",
            name=name, ns=ns,
        )
        # Aggregating over zero matches still returns one row, with a null name and no projection created.
        if not projected or projected[0]["name"] is None:
            return []
        return client.read(
            "CALL gds.leiden.stream($name, {randomSeed: $seed, gamma: $gamma, concurrency: 1}) YIELD nodeId, communityId "
            "RETURN gds.util.asNode(nodeId).key AS key, labels(gds.util.asNode(nodeId))[0] AS label, "
            "communityId AS community ORDER BY key",
            name=name, seed=LEIDEN_SEED, gamma=LEIDEN_GAMMA,
        )
    finally:
        _drop_projection(client, name)


def clear_communities(client: GraphClient, ns: str) -> None:
    client.write("MATCH (n {ns: $ns}) WHERE n.community_id IS NOT NULL REMOVE n.community_id", ns=ns)


def write_communities(client: GraphClient, ns: str, assignments: list[dict]) -> None:
    for batch in _batches(assignments):
        client.write(
            "UNWIND $rows AS row MATCH (n {key: row.key}) SET n.community_id = row.community", rows=batch,
        )


def fetch_community_members(client: GraphClient, ns: str) -> list[dict]:
    return client.read(
        "MATCH (s:SKU {ns: $ns}) WHERE s.community_id IS NOT NULL "
        "OPTIONAL MATCH (s)-[:IN_FAMILY]->(f:ProductFamily) "
        "RETURN s.id AS sku_id, s.name AS name, s.category AS category, s.discontinued AS discontinued, "
        "s.community_id AS community, f.name AS family, EXISTS { (s)-[:REQUIRES]->() } AS has_requirements "
        "ORDER BY s.id",
        ns=ns,
    )


def fetch_node(client: GraphClient, ns: str, node_id: str) -> dict | None:
    rows = client.read(
        "MATCH (n {key: $key}) RETURN n.id AS id, labels(n)[0] AS label", key=node_key(ns, node_id),
    )
    return rows[0] if rows else None


def fetch_local_paths(client: GraphClient, ns: str, node_id: str, hops: int) -> list[dict]:
    """Paths of 1 to `hops` relationships from a node, never passing through a hub node. Nearer paths first."""
    if not isinstance(hops, int):
        raise ValueError("hops must be an integer")
    not_hub = " AND ".join(f"NOT x:{label}" for label in HUB_LABELS)
    return client.read(
        f"MATCH p = (s {{key: $key}})-[*1..{hops}]-(m) "
        f"WHERE m.ns = $ns AND all(x IN nodes(p)[1..-1] WHERE {not_hub}) "
        "RETURN [n IN nodes(p) | {id: n.id, label: labels(n)[0]}] AS nodes, "
        "[r IN relationships(p) | {type: type(r), source: startNode(r).id, target: endNode(r).id}] AS edges "
        f"ORDER BY length(p), m.id LIMIT {LOCAL_MAX_PATHS}",
        key=node_key(ns, node_id), ns=ns,
    )


def search_nodes(client: GraphClient, ns: str, text: str, limit: int) -> list[dict]:
    return client.read(
        "MATCH (n {ns: $ns}) WHERE NOT n:GraphMeta "
        "AND (toLower(n.id) CONTAINS toLower($text) OR toLower(coalesce(n.name, '')) CONTAINS toLower($text)) "
        "RETURN n.id AS id, labels(n)[0] AS label, coalesce(n.name, n.id) AS name, n.community_id AS community "
        "ORDER BY n.id LIMIT $limit",
        ns=ns, text=text, limit=limit,
    )


def fetch_neighborhood(client: GraphClient, ns: str, node_id: str, limit: int) -> dict | None:
    """The node and its one-hop neighbors with the edges to them: up to limit + 1 rows so a caller can tell the
    result was cut. None when the node is absent."""
    key = node_key(ns, node_id)
    center = client.read(
        "MATCH (n {key: $key}) RETURN n.id AS id, labels(n)[0] AS label, coalesce(n.name, n.id) AS name, "
        "n.community_id AS community",
        key=key,
    )
    if not center:
        return None
    rows = client.read(
        "MATCH (c {key: $key})-[r]-(m) WHERE m.ns = $ns AND NOT m:GraphMeta "
        "RETURN m.id AS id, labels(m)[0] AS label, coalesce(m.name, m.id) AS name, m.community_id AS community, "
        "type(r) AS type, startNode(r).id AS source, endNode(r).id AS target LIMIT $fetch",
        key=key, ns=ns, fetch=limit + 1,
    )
    return {"center": center[0], "rows": rows}


def count_edges_between_labels(client: GraphClient, ns: str) -> list[dict]:
    return client.read(
        "MATCH (a {ns: $ns})-[r]->(b {ns: $ns}) WHERE NOT a:GraphMeta AND NOT b:GraphMeta "
        "RETURN labels(a)[0] AS source, labels(b)[0] AS target, type(r) AS type, count(r) AS count "
        "ORDER BY source, type, target",
        ns=ns,
    )


def list_nodes_by_label(client: GraphClient, ns: str, label: str, limit: int) -> list[dict]:
    """A label's most connected nodes first, so the ones worth exploring are the ones shown."""
    _require(label, NODE_LABELS, "label")
    return client.read(
        f"MATCH (n:{label} {{ns: $ns}}) "
        "RETURN n.id AS id, labels(n)[0] AS label, coalesce(n.name, n.id) AS name, n.community_id AS community "
        "ORDER BY COUNT { (n)--() } DESC, n.id LIMIT $limit",
        ns=ns, limit=limit,
    )


def fetch_all_nodes(client: GraphClient, ns: str) -> list[dict]:
    return client.read(
        "MATCH (n {ns: $ns}) WHERE NOT n:GraphMeta "
        "RETURN n.id AS id, labels(n)[0] AS label, coalesce(n.name, n.id) AS name, n.community_id AS community "
        "ORDER BY n.id",
        ns=ns,
    )


def fetch_all_edges(client: GraphClient, ns: str) -> list[dict]:
    return client.read(
        "MATCH (a {ns: $ns})-[r]->(b {ns: $ns}) WHERE NOT a:GraphMeta AND NOT b:GraphMeta "
        "RETURN a.id AS source, b.id AS target, type(r) AS type",
        ns=ns,
    )
