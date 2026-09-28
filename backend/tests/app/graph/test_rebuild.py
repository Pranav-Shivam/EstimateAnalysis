import uuid

import pytest

from app.graph.repository import (
    count_edges_by_type, count_nodes_by_label, ensure_constraints, merge_edges, merge_nodes, node_key,
)
from app.graph.service import rebuild_reference_graph
from app.reference_data.models import Contract
from app.reference_data.repository import reference_fingerprint, upsert_contract
from tests.app.estimate.seed import seed_structure, seed_world


def _node(client, ns, node_id):
    rows = client.read(
        "MATCH (n {key: $key}) RETURN labels(n) AS labels, properties(n) AS props", key=node_key(ns, node_id)
    )
    return rows[0] if rows else None


def _edges(client, ns, source, edge_type, target):
    rows = client.read(
        "MATCH ({key: $source})-[r]->({key: $target}) WHERE type(r) = $type RETURN count(r) AS count",
        source=node_key(ns, source), target=node_key(ns, target), type=edge_type,
    )
    return rows[0]["count"]


def _build(db_session, graph_client, graph_ns):
    seed_world(db_session)
    seed_structure(db_session)
    rebuild_reference_graph(db_session, graph_client, graph_ns)


def test_every_reference_node_type_is_built_with_its_properties(db_session, graph_client, graph_ns):
    _build(db_session, graph_client, graph_ns)

    sku = _node(graph_client, graph_ns, "SKU-E-A1")
    assert sku["labels"] == ["SKU"]
    assert sku["props"]["ns"] == graph_ns and sku["props"]["id"] == "SKU-E-A1"
    assert sku["props"]["category"] == "Cat-E-A" and sku["props"]["list_price"] == 100.0
    assert sku["props"]["discontinued"] is False and sku["props"]["in_stock"] is True
    assert _node(graph_client, graph_ns, "Cat-E-A")["labels"] == ["PricingCategory"]
    assert _node(graph_client, graph_ns, "CUST-E1")["props"]["account_tier"] == "Standard"
    assert _node(graph_client, graph_ns, "CUST-E1-C1")["labels"] == ["Person"]
    contract = _node(graph_client, graph_ns, "CTR-E1")
    assert contract["labels"] == ["Contract"]
    assert contract["props"]["discount_pct"] == 10.0
    assert contract["props"]["effective_from"] == "2024-01-01"
    assert _node(graph_client, graph_ns, "FAM-E-A")["props"]["name"] == "Zorpwidget Alpha"
    assert _node(graph_client, graph_ns, "PRJ-E1")["labels"] == ["Project"]
    assert _node(graph_client, graph_ns, "SITE-E1")["props"]["zip"] == "62701"


def test_every_reference_edge_type_is_built(db_session, graph_client, graph_ns):
    _build(db_session, graph_client, graph_ns)

    expected = [
        ("CUST-E1-C1", "WORKS_FOR", "CUST-E1"),
        ("CUST-E1", "HOLDS", "CTR-E1"),
        ("CTR-E1", "COVERS", "Cat-E-A"),
        ("SKU-E-A1", "IN_FAMILY", "FAM-E-A"),
        ("SKU-E-OLD", "REPLACED_BY", "SKU-E-A1"),
        ("SKU-E-A1", "PRICED_IN", "Cat-E-A"),
        ("SKU-E-B1", "REQUIRES", "SKU-E-A1"),
        ("CUST-E1", "HAS_PROJECT", "PRJ-E1"),
        ("PRJ-E1", "AT_SITE", "SITE-E1"),
    ]
    for source, edge_type, target in expected:
        assert _edges(graph_client, graph_ns, source, edge_type, target) == 1, (source, edge_type, target)


def test_a_gap_sku_has_no_list_price_property(db_session, graph_client, graph_ns):
    _build(db_session, graph_client, graph_ns)

    assert "list_price" not in _node(graph_client, graph_ns, "SKU-E-GAP")["props"]


def test_a_covered_category_with_no_skus_still_gets_a_node_and_edge(db_session, graph_client, graph_ns):
    seed_world(db_session)
    template = db_session.get(Contract, "CTR-E1")
    upsert_contract(
        db_session, contract_id="CTR-E-EMPTY", customer_id="CUST-E2", discount_category="Cat-E-EMPTY",
        covered_categories=["Cat-E-EMPTY"], effective_from=template.effective_from,
        effective_to=template.effective_to, discount_pct=5.0,
    )
    db_session.flush()

    rebuild_reference_graph(db_session, graph_client, graph_ns)

    assert _edges(graph_client, graph_ns, "CTR-E-EMPTY", "COVERS", "Cat-E-EMPTY") == 1


def test_rebuild_is_idempotent(db_session, graph_client, graph_ns):
    _build(db_session, graph_client, graph_ns)
    before = (count_nodes_by_label(graph_client, graph_ns), count_edges_by_type(graph_client, graph_ns))

    rebuild_reference_graph(db_session, graph_client, graph_ns)

    assert (count_nodes_by_label(graph_client, graph_ns), count_edges_by_type(graph_client, graph_ns)) == before
    assert _edges(graph_client, graph_ns, "SKU-E-B1", "REQUIRES", "SKU-E-A1") == 1


def test_rebuild_replaces_stale_content_in_its_namespace(db_session, graph_client, graph_ns):
    _build(db_session, graph_client, graph_ns)
    graph_client.write(
        "CREATE (:SKU {ns: $ns, key: $key, id: 'SKU-STALE'})", ns=graph_ns, key=node_key(graph_ns, "SKU-STALE"),
    )

    rebuild_reference_graph(db_session, graph_client, graph_ns)

    assert _node(graph_client, graph_ns, "SKU-STALE") is None


def test_rebuild_leaves_other_namespaces_alone(db_session, graph_client, graph_ns):
    other = f"test-other-{uuid.uuid4().hex[:8]}"
    graph_client.write(
        "CREATE (:Sentinel {ns: $ns, key: $key, id: 'keep-me'})", ns=other, key=node_key(other, "keep-me"),
    )
    try:
        _build(db_session, graph_client, graph_ns)

        assert _node(graph_client, other, "keep-me") is not None
    finally:
        graph_client.write("MATCH (n {ns: $ns}) DETACH DELETE n", ns=other)


def test_graph_meta_stores_the_reference_fingerprint(db_session, graph_client, graph_ns):
    _build(db_session, graph_client, graph_ns)

    meta = _node(graph_client, graph_ns, graph_ns)

    assert meta["labels"] == ["GraphMeta"]
    assert meta["props"]["reference_fingerprint"] == reference_fingerprint(db_session)
    assert meta["props"]["built_at"]


def test_ensure_constraints_can_run_twice(graph_client):
    ensure_constraints(graph_client)
    ensure_constraints(graph_client)


def test_merge_nodes_rejects_an_unknown_label(graph_client, graph_ns):
    with pytest.raises(ValueError):
        merge_nodes(graph_client, graph_ns, "NotARealLabel", [{"id": "x", "props": {}}])


def test_merge_edges_rejects_an_unknown_edge_type(graph_client, graph_ns):
    with pytest.raises(ValueError):
        merge_edges(graph_client, graph_ns, "NOT_A_REAL_EDGE", "SKU", "SKU", [{"from": "a", "to": "b", "props": {}}])


def test_merge_edges_matches_nodes_by_namespaced_key_not_bare_id(graph_client, graph_ns):
    # Two namespaces holding a node under the same raw id, distinguished by a marker property. Matching by the
    # namespaced key must resolve to this test's own node only; matching by bare id would be ambiguous across
    # namespaces and could wire an edge onto a node this test never touched.
    other = f"test-other-{uuid.uuid4().hex[:8]}"
    try:
        merge_nodes(graph_client, graph_ns, "SKU", [
            {"id": "SHARED-ID", "props": {"marker": "mine"}},
            {"id": "TARGET-ID", "props": {"marker": "mine"}},
        ])
        merge_nodes(graph_client, other, "SKU", [
            {"id": "SHARED-ID", "props": {"marker": "theirs"}},
            {"id": "TARGET-ID", "props": {"marker": "theirs"}},
        ])

        merge_edges(graph_client, graph_ns, "REQUIRES", "SKU", "SKU", [
            {"from": "SHARED-ID", "to": "TARGET-ID", "props": {}},
        ])

        assert _edges(graph_client, graph_ns, "SHARED-ID", "REQUIRES", "TARGET-ID") == 1
        assert _edges(graph_client, other, "SHARED-ID", "REQUIRES", "TARGET-ID") == 0
    finally:
        graph_client.write("MATCH (n {ns: $ns}) DETACH DELETE n", ns=other)
