from datetime import date

from app.graph.constant import MAX_CHAIN_HOPS
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
    from app.graph.reader import GraphReader

    assert GraphReader(graph_client, graph_ns).stored_fingerprint() is None
