import uuid

import pytest

from app.graph.constant import LOCAL_MAX_NODES
from app.graph.helper import member_hash
from app.graph.repository import node_key
from app.graph.service import NodeNotFound, global_stats, local_query, run_communities
from app.reference_data.repository import upsert_requirement, upsert_sku
from tests.app.estimate.seed import seed_structure, seed_world
from core.graph.client import GraphQueryFailed
from tests.graph_support import graph_node, seed_clusters


def test_leiden_checks_that_gds_is_loaded_before_building_any_projection(graph_client, graph_ns):
    """(Spec risk) A missing or broken GDS plugin must fail on a plain version check, before any projection."""
    queries = []

    class NoGds:
        def read(self, query, **params):
            queries.append(query)
            if "gds.version" in query:
                raise GraphQueryFailed("Neo4j query failed: unknown function gds.version")
            return graph_client.read(query, **params)

        def write(self, query, **params):
            queries.append(query)
            return graph_client.write(query, **params)

    with pytest.raises(GraphQueryFailed):
        run_communities(NoGds(), graph_ns)

    assert len(queries) == 1 and "gds.version" in queries[0]


def _sku(session, sku_id, category, *, discontinued=False):
    upsert_sku(session, sku_id=sku_id, name=f"unit {sku_id}", category=category, list_price=1.0,
               discontinued=discontinued, replaced_by=None, in_stock=True)


def _community_of(client, ns, sku_id):
    rows = client.read("MATCH (n {key: $key}) RETURN n.community_id AS community", key=node_key(ns, sku_id))
    return rows[0]["community"]


def _partition(client, ns):
    rows = client.read("MATCH (s:SKU {ns: $ns}) WHERE s.community_id IS NOT NULL RETURN s.community_id AS c, s.id AS id", ns=ns)
    groups: dict[int, set[str]] = {}
    for row in rows:
        groups.setdefault(row["c"], set()).add(row["id"])
    return {frozenset(members) for members in groups.values()}


def test_disconnected_clusters_land_in_separate_communities(db_session, graph_client, graph_ns, make_reader):
    seed_clusters(db_session)
    make_reader()

    summary = run_communities(graph_client, graph_ns)

    x = {_community_of(graph_client, graph_ns, f"SKU-L-X{i}") for i in range(1, 5)}
    y = {_community_of(graph_client, graph_ns, f"SKU-L-Y{i}") for i in range(1, 5)}
    assert len(x) == 1 and len(y) == 1 and x != y
    assert summary.community_count >= 2
    assert summary.largest_community_size >= 4
    assert _community_of(graph_client, graph_ns, "FAM-L-X") == next(iter(x))


def test_a_fixed_seed_gives_the_same_partition_on_every_run(db_session, graph_client, graph_ns, make_reader):
    seed_clusters(db_session)
    make_reader()

    run_communities(graph_client, graph_ns)
    first = _partition(graph_client, graph_ns)
    run_communities(graph_client, graph_ns)

    assert _partition(graph_client, graph_ns) == first


def test_the_gds_projection_is_dropped_after_a_run(db_session, graph_client, graph_ns, make_reader):
    seed_clusters(db_session)
    make_reader()

    run_communities(graph_client, graph_ns)

    exists = graph_client.read("CALL gds.graph.exists($name) YIELD exists RETURN exists", name=f"leiden-{graph_ns}")
    assert exists == [{"exists": False}]


def test_a_second_run_clears_assignments_from_the_first(db_session, graph_client, graph_ns, make_reader):
    seed_clusters(db_session)
    make_reader()
    graph_client.write("MATCH (n {key: $key}) SET n.community_id = 9999", key=node_key(graph_ns, "Cat-L"))

    run_communities(graph_client, graph_ns)

    assert "community_id" not in graph_node(graph_client, graph_ns, "Cat-L")["props"]
    assert _community_of(graph_client, graph_ns, "SKU-L-X1") != 9999


def test_run_communities_never_writes_community_id_into_another_namespace(db_session, graph_client, graph_ns, make_reader):
    """(Review Focus) The Leiden projection's ns filter must scope both the read and the write-back; a regression
    there would leak community_id onto every other populated namespace, main included."""
    other = f"test-other-{uuid.uuid4().hex[:8]}"
    graph_client.write(
        "CREATE (a:SKU {ns: $ns, key: $ka, id: 'OTHER-SKU-A'}) "
        "CREATE (b:SKU {ns: $ns, key: $kb, id: 'OTHER-SKU-B'}) "
        "CREATE (f:ProductFamily {ns: $ns, key: $kf, id: 'OTHER-FAM'}) "
        "CREATE (a)-[:REQUIRES]->(b) "
        "CREATE (a)-[:IN_FAMILY]->(f)",
        ns=other, ka=node_key(other, "OTHER-SKU-A"), kb=node_key(other, "OTHER-SKU-B"),
        kf=node_key(other, "OTHER-FAM"),
    )
    try:
        seed_clusters(db_session)
        make_reader()

        run_communities(graph_client, graph_ns)

        rows = graph_client.read("MATCH (n {ns: $ns}) RETURN n.community_id AS community_id", ns=other)
        assert rows and all(row["community_id"] is None for row in rows)
    finally:
        graph_client.write("MATCH (n {ns: $ns}) DETACH DELETE n", ns=other)


def test_an_empty_namespace_has_no_communities(graph_client, graph_ns):
    summary = run_communities(graph_client, graph_ns)

    assert summary.community_count == 0 and summary.largest_community_size == 0


def test_global_stats_describe_a_planted_cluster(db_session, graph_client, graph_ns, make_reader):
    seed_clusters(db_session)
    make_reader()
    run_communities(graph_client, graph_ns)

    stats = global_stats(graph_client, graph_ns)

    x = next(s for s in stats if "SKU-L-X1" in s.example_sku_ids)
    y = next(s for s in stats if "SKU-L-Y1" in s.example_sku_ids)
    assert x.size == 4 and x.families == ("Xylo Widget",)
    assert (x.dominant_category, x.dominant_category_share) == ("Cat-L", 1.0)
    assert x.discontinued_count == 1 and x.requirement_count == 1
    assert x.example_sku_ids == ("SKU-L-X1", "SKU-L-X2", "SKU-L-X3", "SKU-L-X4")
    assert x.member_hash == member_hash(x.example_sku_ids)
    assert y.discontinued_count == 0 and y.requirement_count == 0


def test_global_stats_are_empty_before_communities_are_computed(db_session, graph_client, graph_ns, make_reader):
    seed_world(db_session)
    make_reader()

    assert global_stats(graph_client, graph_ns) == []


def _ids(result):
    return {n["id"] for n in result.nodes}


def test_one_hop_lists_direct_neighbours_with_hubs_as_leaves(db_session, graph_client, graph_ns, make_reader):
    seed_world(db_session)
    make_reader()

    result = local_query(graph_client, graph_ns, "SKU-E-B1", hops=1)

    assert result.center == "SKU-E-B1"
    assert _ids(result) == {"SKU-E-B1", "SKU-E-A1", "Cat-E-B"}
    assert {"type": "REQUIRES", "source": "SKU-E-B1", "target": "SKU-E-A1"} in result.edges
    assert {"type": "PRICED_IN", "source": "SKU-E-B1", "target": "Cat-E-B"} in result.edges
    assert result.truncated is False
    labels = {n["id"]: n["label"] for n in result.nodes}
    assert labels["SKU-E-B1"] == "SKU" and labels["Cat-E-B"] == "PricingCategory"


def test_two_hops_pass_through_a_sku_but_not_through_a_hub(db_session, graph_client, graph_ns, make_reader):
    seed_world(db_session)
    seed_structure(db_session)
    for i in range(1, 6):
        _sku(db_session, f"SKU-L-H{i}", "Cat-L-HUB")
    db_session.flush()
    make_reader()

    through_sku = local_query(graph_client, graph_ns, "SKU-E-B1", hops=2)
    through_hub = local_query(graph_client, graph_ns, "SKU-L-H1", hops=2)

    assert {"SKU-E-OLD", "FAM-E-A"} <= _ids(through_sku)
    assert "Cat-L-HUB" in _ids(through_hub)
    assert _ids(through_hub).isdisjoint({f"SKU-L-H{i}" for i in range(2, 6)})


def test_a_hub_centre_returns_at_most_the_node_cap_and_says_it_was_truncated(db_session, graph_client, graph_ns, make_reader):
    """(Review Focus) A pricing category with more members than the cap."""
    for i in range(LOCAL_MAX_NODES + 10):
        _sku(db_session, f"SKU-L-B{i:03d}", "Cat-L-BIG")
    db_session.flush()
    make_reader()

    result = local_query(graph_client, graph_ns, "Cat-L-BIG", hops=1)

    assert result.truncated is True
    assert len(result.nodes) == LOCAL_MAX_NODES
    assert "Cat-L-BIG" in _ids(result)
    kept = _ids(result)
    assert all(e["source"] in kept and e["target"] in kept for e in result.edges)


def test_an_unknown_id_raises_node_not_found(db_session, graph_client, graph_ns, make_reader):
    seed_world(db_session)
    make_reader()

    with pytest.raises(NodeNotFound):
        local_query(graph_client, graph_ns, "SKU-NOPE")


def test_an_id_that_exists_only_in_another_namespace_is_not_found(db_session, graph_client, graph_ns, make_reader):
    """(Review Focus) The namespace is part of the lookup key."""
    other = f"test-other-{uuid.uuid4().hex[:8]}"
    graph_client.write("CREATE (:SKU {ns: $ns, key: $key, id: 'OTHER-ONLY'})", ns=other, key=node_key(other, "OTHER-ONLY"))
    try:
        seed_world(db_session)
        make_reader()

        with pytest.raises(NodeNotFound):
            local_query(graph_client, graph_ns, "OTHER-ONLY")
    finally:
        graph_client.write("MATCH (n {ns: $ns}) DETACH DELETE n", ns=other)


def test_hops_are_clamped_to_between_one_and_the_maximum(db_session, graph_client, graph_ns, make_reader):
    """(Review Focus) hops of 0 or 99 must not disable or unbound the walk."""
    for i in range(1, 5):
        _sku(db_session, f"SKU-L-C{i}", "Cat-L-CHAIN")
    db_session.flush()
    for i in range(1, 4):
        upsert_requirement(db_session, sku_id=f"SKU-L-C{i}", required_sku_id=f"SKU-L-C{i + 1}")
    db_session.flush()
    make_reader()

    zero = local_query(graph_client, graph_ns, "SKU-L-C1", hops=0)
    huge = local_query(graph_client, graph_ns, "SKU-L-C1", hops=99)

    assert "SKU-L-C2" in _ids(zero) and "SKU-L-C3" not in _ids(zero)
    assert "SKU-L-C3" in _ids(huge) and "SKU-L-C4" not in _ids(huge)


def test_an_isolated_node_returns_just_itself(db_session, graph_client, graph_ns, make_reader):
    seed_world(db_session)
    make_reader()
    graph_client.write("CREATE (:Site {ns: $ns, key: $key, id: 'SITE-LONELY'})", ns=graph_ns, key=node_key(graph_ns, "SITE-LONELY"))

    result = local_query(graph_client, graph_ns, "SITE-LONELY")

    assert result.nodes == [{"id": "SITE-LONELY", "label": "Site"}]
    assert result.edges == [] and result.truncated is False
