import uuid
from datetime import date

from app.graph.constant import MAX_CHAIN_HOPS
from app.graph.reader import GraphReader
from app.graph.repository import merge_edges, merge_nodes
from app.reference_data.repository import reference_fingerprint
from tests.app.estimate.seed import AS_OF, seed_chain_world, seed_world


def _reader(db_session, make_reader):
    seed_world(db_session)
    seed_chain_world(db_session)
    return make_reader()


def test_a_live_sku_is_its_own_live_end(db_session, make_reader):
    chain = _reader(db_session, make_reader).sku_chain("SKU-E-A1")

    assert [n.sku_id for n in chain.nodes] == ["SKU-E-A1"]
    assert chain.live_end.sku_id == "SKU-E-A1"
    assert chain.evidence_path == ["SKU-E-A1"]


def test_a_discontinued_sku_walks_to_its_live_replacement(db_session, make_reader):
    chain = _reader(db_session, make_reader).sku_chain("SKU-E-OLD")

    assert [n.sku_id for n in chain.nodes] == ["SKU-E-OLD", "SKU-E-A1"]
    assert chain.nodes[0].discontinued is True and chain.nodes[0].in_stock is False
    assert chain.live_end.sku_id == "SKU-E-A1"
    assert chain.sku_id == "SKU-E-OLD"
    assert chain.evidence_path == ["SKU-E-OLD", "REPLACED_BY", "SKU-E-A1"]


def test_a_two_hop_chain_reaches_the_live_end(db_session, make_reader):
    chain = _reader(db_session, make_reader).sku_chain("SKU-E-OLD2")

    assert [n.sku_id for n in chain.nodes] == ["SKU-E-OLD2", "SKU-E-OLD", "SKU-E-A1"]
    assert chain.live_end.sku_id == "SKU-E-A1"
    assert chain.evidence_path == ["SKU-E-OLD2", "REPLACED_BY", "SKU-E-OLD", "REPLACED_BY", "SKU-E-A1"]


def test_a_discontinued_sku_with_no_replacement_has_no_live_end(db_session, make_reader):
    chain = _reader(db_session, make_reader).sku_chain("SKU-E-DEAD")

    assert [n.sku_id for n in chain.nodes] == ["SKU-E-DEAD"]
    assert chain.live_end is None


def test_a_replacement_cycle_terminates_with_no_live_end(db_session, make_reader):
    """(Review Focus) A replaced by B replaced by A must not loop forever."""
    chain = _reader(db_session, make_reader).sku_chain("SKU-E-CYC1")

    assert chain.live_end is None
    assert {n.sku_id for n in chain.nodes} == {"SKU-E-CYC1", "SKU-E-CYC2"}


def test_a_chain_past_the_hop_bound_is_treated_as_unresolvable(db_session, make_reader):
    """(Review Focus) D0 reaches the live SKU only after 12 hops; the bound is 10."""
    chain = _reader(db_session, make_reader).sku_chain("SKU-E-D0")

    assert MAX_CHAIN_HOPS == 10
    assert chain.live_end is None
    assert len(chain.nodes) == MAX_CHAIN_HOPS + 1


def test_a_chain_within_the_hop_bound_is_resolved_from_the_middle(db_session, make_reader):
    chain = _reader(db_session, make_reader).sku_chain("SKU-E-D5")

    assert chain.live_end.sku_id == "SKU-E-A1"


def test_an_unknown_sku_has_no_chain(db_session, make_reader):
    assert _reader(db_session, make_reader).sku_chain("SKU-NOPE") is None


def test_required_parts_lists_direct_requirements_with_their_status(db_session, make_reader):
    reader = _reader(db_session, make_reader)

    assert [(p.sku_id, p.discontinued) for p in reader.required_parts("SKU-E-B1")] == [("SKU-E-A1", False)]
    assert [(p.sku_id, p.discontinued, p.in_stock) for p in reader.required_parts("SKU-E-NEEDOLD")] == [
        ("SKU-E-OLD", True, False),
    ]
    assert reader.required_parts("SKU-E-A1") == []
    assert reader.required_parts("SKU-NOPE") == []


def test_contract_coverage_says_covered_and_active(db_session, make_reader):
    coverage = _reader(db_session, make_reader).contract_coverage("CUST-E1", "SKU-E-A1", AS_OF)

    assert len(coverage) == 1
    row = coverage[0]
    assert (row.contract_id, row.discount_pct, row.sku_category) == ("CTR-E1", 10.0, "Cat-E-A")
    assert row.covered is True and row.active_on_as_of is True
    assert row.covered_categories == ("Cat-E-A",)


def test_contract_coverage_says_uncovered_for_another_category(db_session, make_reader):
    row = _reader(db_session, make_reader).contract_coverage("CUST-E1", "SKU-E-B1", AS_OF)[0]

    assert row.covered is False
    assert row.sku_category == "Cat-E-B"
    assert row.covered_categories == ("Cat-E-A",)


def test_contract_coverage_reports_an_inactive_contract(db_session, make_reader):
    row = _reader(db_session, make_reader).contract_coverage("CUST-E1", "SKU-E-A1", date(2026, 1, 1))[0]

    assert row.covered is True
    assert row.active_on_as_of is False


def test_contract_coverage_is_empty_for_a_customer_without_contracts(db_session, make_reader):
    assert _reader(db_session, make_reader).contract_coverage("CUST-E2", "SKU-E-A1", AS_OF) == []


def test_contract_coverage_for_an_unknown_sku_has_no_category(db_session, make_reader):
    row = _reader(db_session, make_reader).contract_coverage("CUST-E1", "SKU-NOPE", AS_OF)[0]

    assert row.sku_category is None
    assert row.covered is False


def test_stored_fingerprint_matches_postgres_after_a_build(db_session, make_reader):
    reader = _reader(db_session, make_reader)

    assert reader.stored_fingerprint() == reference_fingerprint(db_session)


def test_stored_fingerprint_is_none_before_any_build(graph_client, graph_ns):
    assert GraphReader(graph_client, graph_ns).stored_fingerprint() is None


def test_contract_coverage_is_active_exactly_on_the_effective_from_date(db_session, make_reader):
    row = _reader(db_session, make_reader).contract_coverage("CUST-E1", "SKU-E-A1", date(2024, 1, 1))[0]

    assert row.active_on_as_of is True


def test_contract_coverage_is_active_exactly_on_the_effective_to_date(db_session, make_reader):
    row = _reader(db_session, make_reader).contract_coverage("CUST-E1", "SKU-E-A1", date(2025, 12, 31))[0]

    assert row.active_on_as_of is True


def _iso_props(discontinued=False, in_stock=True):
    return {"discontinued": discontinued, "in_stock": in_stock}


def test_required_parts_are_scoped_to_the_namespace(graph_client, graph_ns):
    """Two namespaces holding a SKU under the same raw id, requiring different parts. A reader scoped to one
    namespace must never see the other namespace's requirement, which would happen if the underlying query
    matched by bare id instead of the namespaced key."""
    other = f"test-other-{uuid.uuid4().hex[:8]}"
    try:
        merge_nodes(graph_client, graph_ns, "SKU", [
            {"id": "SKU-ISO-A", "props": {"name": "mine", **_iso_props()}},
            {"id": "SKU-ISO-R-MINE", "props": {"name": "mine req", **_iso_props()}},
        ])
        merge_edges(graph_client, graph_ns, "REQUIRES", "SKU", "SKU", [
            {"from": "SKU-ISO-A", "to": "SKU-ISO-R-MINE", "props": {}},
        ])
        merge_nodes(graph_client, other, "SKU", [
            {"id": "SKU-ISO-A", "props": {"name": "theirs", **_iso_props()}},
            {"id": "SKU-ISO-R-THEIRS", "props": {"name": "their req", **_iso_props()}},
        ])
        merge_edges(graph_client, other, "REQUIRES", "SKU", "SKU", [
            {"from": "SKU-ISO-A", "to": "SKU-ISO-R-THEIRS", "props": {}},
        ])

        mine = GraphReader(graph_client, graph_ns).required_parts("SKU-ISO-A")
        theirs = GraphReader(graph_client, other).required_parts("SKU-ISO-A")

        assert [p.sku_id for p in mine] == ["SKU-ISO-R-MINE"]
        assert [p.sku_id for p in theirs] == ["SKU-ISO-R-THEIRS"]
    finally:
        graph_client.write("MATCH (n {ns: $ns}) DETACH DELETE n", ns=other)


def test_sku_chain_is_scoped_to_the_namespace(graph_client, graph_ns):
    """Two namespaces holding a SKU under the same raw id, replaced by different live SKUs. A reader scoped to
    one namespace must never resolve the other namespace's replacement chain."""
    other = f"test-other-{uuid.uuid4().hex[:8]}"
    try:
        merge_nodes(graph_client, graph_ns, "SKU", [
            {"id": "SKU-ISO-CHAIN", "props": {"name": "mine", **_iso_props(discontinued=True, in_stock=False)}},
            {"id": "SKU-ISO-LIVE-MINE", "props": {"name": "mine live", **_iso_props()}},
        ])
        merge_edges(graph_client, graph_ns, "REPLACED_BY", "SKU", "SKU", [
            {"from": "SKU-ISO-CHAIN", "to": "SKU-ISO-LIVE-MINE", "props": {}},
        ])
        merge_nodes(graph_client, other, "SKU", [
            {"id": "SKU-ISO-CHAIN", "props": {"name": "theirs", **_iso_props(discontinued=True, in_stock=False)}},
            {"id": "SKU-ISO-LIVE-THEIRS", "props": {"name": "their live", **_iso_props()}},
        ])
        merge_edges(graph_client, other, "REPLACED_BY", "SKU", "SKU", [
            {"from": "SKU-ISO-CHAIN", "to": "SKU-ISO-LIVE-THEIRS", "props": {}},
        ])

        mine = GraphReader(graph_client, graph_ns).sku_chain("SKU-ISO-CHAIN")
        theirs = GraphReader(graph_client, other).sku_chain("SKU-ISO-CHAIN")

        assert mine.live_end.sku_id == "SKU-ISO-LIVE-MINE"
        assert theirs.live_end.sku_id == "SKU-ISO-LIVE-THEIRS"
    finally:
        graph_client.write("MATCH (n {ns: $ns}) DETACH DELETE n", ns=other)


def test_contract_coverage_is_scoped_to_the_namespace(graph_client, graph_ns):
    """Two namespaces holding a customer, contract, and SKU under the same raw ids but different discount and
    category data. A reader scoped to one namespace must never see the other namespace's coverage."""
    other = f"test-other-{uuid.uuid4().hex[:8]}"
    try:
        for ns, discount_pct, category in ((graph_ns, 10.0, "Cat-ISO-MINE"), (other, 99.0, "Cat-ISO-THEIRS")):
            merge_nodes(graph_client, ns, "PricingCategory", [{"id": category, "props": {}}])
            merge_nodes(graph_client, ns, "Customer", [{"id": "CUST-ISO", "props": {"name": "x", "account_tier": "Standard"}}])
            merge_nodes(graph_client, ns, "Contract", [{"id": "CTR-ISO", "props": {
                "discount_pct": discount_pct, "discount_category": category,
                "effective_from": "2024-01-01", "effective_to": "2025-12-31",
            }}])
            merge_nodes(graph_client, ns, "SKU", [{"id": "SKU-ISO-COV", "props": {"name": "x", "category": category, **_iso_props()}}])
            merge_edges(graph_client, ns, "HOLDS", "Customer", "Contract", [{"from": "CUST-ISO", "to": "CTR-ISO", "props": {}}])
            merge_edges(graph_client, ns, "COVERS", "Contract", "PricingCategory", [{"from": "CTR-ISO", "to": category, "props": {}}])
            merge_edges(graph_client, ns, "PRICED_IN", "SKU", "PricingCategory", [{"from": "SKU-ISO-COV", "to": category, "props": {}}])

        mine = GraphReader(graph_client, graph_ns).contract_coverage("CUST-ISO", "SKU-ISO-COV", AS_OF)[0]
        theirs = GraphReader(graph_client, other).contract_coverage("CUST-ISO", "SKU-ISO-COV", AS_OF)[0]

        assert (mine.discount_pct, mine.sku_category) == (10.0, "Cat-ISO-MINE")
        assert (theirs.discount_pct, theirs.sku_category) == (99.0, "Cat-ISO-THEIRS")
    finally:
        graph_client.write("MATCH (n {ns: $ns}) DETACH DELETE n", ns=other)
