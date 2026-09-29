import pytest

from app.estimate.guardrails import check_graph_integrity, graph_is_current
from app.estimate.schemas import DraftLine, EstimateDraft
from app.reference_data.models import Sku
from app.reference_data.repository import upsert_requirement, upsert_sku
from core.graph.client import GraphUnavailable
from tests.app.estimate.seed import seed_chain_world, seed_world
from tests.graph_support import FailingGraphReader


def _draft(*sku_ids):
    return EstimateDraft(
        customer_id="CUST-E1", contract_id=None,
        lines=[DraftLine(sku_id=s, quantity=1, unit_price=1.0, price_source="list") for s in sku_ids],
    )


def _reader(db_session, make_reader):
    seed_world(db_session)
    seed_chain_world(db_session)
    return make_reader()


def _messages(check):
    return [v.message for v in check.violations]


def test_a_clean_draft_has_no_violations(db_session, make_reader):
    check = check_graph_integrity(_reader(db_session, make_reader), _draft("SKU-E-A1"), ("SKU-E-A1",))

    assert check.violations == [] and check.unreplaceable == []


def test_a_discontinued_line_is_a_violation_that_names_the_live_replacement(db_session, make_reader):
    check = check_graph_integrity(_reader(db_session, make_reader), _draft("SKU-E-OLD"), ())

    [violation] = check.violations
    assert violation.guardrail == "graph_integrity" and violation.line_index == 0
    assert "SKU-E-OLD is discontinued" in violation.message and "SKU-E-A1" in violation.message


def test_a_request_for_a_discontinued_sku_must_be_covered_by_its_live_replacement(db_session, make_reader):
    reader = _reader(db_session, make_reader)

    swapped = check_graph_integrity(reader, _draft("SKU-E-A1"), ("SKU-E-OLD",))
    left_in = check_graph_integrity(reader, _draft("SKU-E-OLD"), ("SKU-E-OLD",))

    assert swapped.violations == []
    assert any("the request asks for SKU-E-OLD; the draft must quote SKU-E-A1" in m for m in _messages(left_in))
    assert any("SKU-E-OLD is discontinued" in m for m in _messages(left_in))


def test_dropping_a_requested_line_is_caught(db_session, make_reader):
    """(Review Focus) The draft's own lines cannot vouch for what the customer asked; intake's SKUs can."""
    reader = _reader(db_session, make_reader)

    check = check_graph_integrity(reader, _draft("SKU-E-A1"), ("SKU-E-A1", "SKU-E-B1"))

    assert any("the request asks for SKU-E-B1; the draft must quote SKU-E-B1" in m for m in _messages(check))


def test_swapping_to_a_mid_chain_sku_that_is_still_discontinued_is_caught(db_session, make_reader):
    """(Review Focus) OLD2 is replaced by OLD, which is itself replaced by A1; quoting OLD is not enough."""
    check = check_graph_integrity(_reader(db_session, make_reader), _draft("SKU-E-OLD"), ("SKU-E-OLD2",))

    messages = _messages(check)
    assert any("SKU-E-OLD is discontinued" in m and "SKU-E-A1" in m for m in messages)
    assert any("the request asks for SKU-E-OLD2; the draft must quote SKU-E-A1" in m for m in messages)


def test_a_missing_required_part_is_a_violation_and_adding_it_clears_it(db_session, make_reader):
    reader = _reader(db_session, make_reader)

    missing = check_graph_integrity(reader, _draft("SKU-E-B1"), ())
    added = check_graph_integrity(reader, _draft("SKU-E-B1", "SKU-E-A1"), ())

    assert _messages(missing) == ["SKU-E-B1 requires SKU-E-A1; the draft must include SKU-E-A1"]
    assert missing.violations[0].line_index is None
    assert added.violations == []


def test_required_parts_are_enforced_transitively(db_session, make_reader):
    seed_world(db_session)
    for n in (1, 2, 3):
        upsert_sku(db_session, sku_id=f"SKU-L-T{n}", name=f"t{n}", category="Cat-L", list_price=1.0,
                   discontinued=False, replaced_by=None, in_stock=True)
    db_session.flush()
    upsert_requirement(db_session, sku_id="SKU-L-T1", required_sku_id="SKU-L-T2")
    upsert_requirement(db_session, sku_id="SKU-L-T2", required_sku_id="SKU-L-T3")
    db_session.flush()
    reader = make_reader()

    only_first = check_graph_integrity(reader, _draft("SKU-L-T1"), ())
    first_two = check_graph_integrity(reader, _draft("SKU-L-T1", "SKU-L-T2"), ())
    all_three = check_graph_integrity(reader, _draft("SKU-L-T1", "SKU-L-T2", "SKU-L-T3"), ())

    assert _messages(only_first) == ["SKU-L-T1 requires SKU-L-T2; the draft must include SKU-L-T2"]
    assert _messages(first_two) == ["SKU-L-T2 requires SKU-L-T3; the draft must include SKU-L-T3"]
    assert all_three.violations == []


def test_a_required_part_that_is_discontinued_must_be_quoted_as_its_live_replacement(db_session, make_reader):
    reader = _reader(db_session, make_reader)

    alone = check_graph_integrity(reader, _draft("SKU-E-NEEDOLD"), ())
    swapped = check_graph_integrity(reader, _draft("SKU-E-NEEDOLD", "SKU-E-A1"), ())
    left_in = check_graph_integrity(reader, _draft("SKU-E-NEEDOLD", "SKU-E-OLD"), ())

    assert _messages(alone) == ["SKU-E-NEEDOLD requires SKU-E-OLD; the draft must include SKU-E-A1"]
    assert swapped.violations == []
    assert any("SKU-E-OLD is discontinued" in m for m in _messages(left_in))
    assert any("the draft must include SKU-E-A1" in m for m in _messages(left_in))


def test_a_sku_with_no_live_replacement_is_unreplaceable_not_a_violation(db_session, make_reader):
    reader = _reader(db_session, make_reader)

    in_draft = check_graph_integrity(reader, _draft("SKU-E-DEAD"), ())
    in_request = check_graph_integrity(reader, _draft("SKU-E-A1"), ("SKU-E-DEAD",))

    assert in_draft.unreplaceable == ["SKU-E-DEAD"] and in_draft.violations == []
    assert in_request.unreplaceable == ["SKU-E-DEAD"]


def test_a_replacement_cycle_or_an_overlong_chain_is_unreplaceable(db_session, make_reader):
    """(Review Focus) Neither may loop or be treated as resolved."""
    reader = _reader(db_session, make_reader)

    cycle = check_graph_integrity(reader, _draft("SKU-E-A1"), ("SKU-E-CYC1",))
    deep = check_graph_integrity(reader, _draft("SKU-E-A1"), ("SKU-E-D0",))

    assert cycle.unreplaceable == ["SKU-E-CYC1"]
    assert deep.unreplaceable == ["SKU-E-D0"]


def test_a_required_part_with_no_live_replacement_is_unreplaceable(db_session, make_reader):
    seed_world(db_session)
    seed_chain_world(db_session)
    upsert_sku(db_session, sku_id="SKU-L-NEEDDEAD", name="needs dead", category="Cat-L", list_price=1.0,
               discontinued=False, replaced_by=None, in_stock=True)
    db_session.flush()
    upsert_requirement(db_session, sku_id="SKU-L-NEEDDEAD", required_sku_id="SKU-E-DEAD")
    db_session.flush()

    check = check_graph_integrity(make_reader(), _draft("SKU-L-NEEDDEAD"), ())

    assert check.unreplaceable == ["SKU-E-DEAD"]


def test_unreplaceable_skus_are_listed_once(db_session, make_reader):
    check = check_graph_integrity(
        _reader(db_session, make_reader), _draft("SKU-E-DEAD", "SKU-E-DEAD"), ("SKU-E-DEAD", "SKU-E-DEAD"),
    )

    assert check.unreplaceable == ["SKU-E-DEAD"]


def test_unknown_skus_and_lines_without_a_sku_are_left_to_the_other_guardrails(db_session, make_reader):
    reader = _reader(db_session, make_reader)
    draft = EstimateDraft(customer_id="CUST-E1", lines=[
        DraftLine(sku_id="SKU-NOPE", quantity=1, unit_price=1.0, price_source="list"),
        DraftLine(sku_id=None, quantity=1, unit_price=1.0, price_source="list"),
    ])

    check = check_graph_integrity(reader, draft, ("SKU-ALSO-NOPE",))

    assert check.violations == [] and check.unreplaceable == []


def test_an_unresolved_intake_item_cannot_be_anchored(db_session, make_reader):
    """Known gap, pinned so it is a decision and not an accident: intake items with no sku_id never reach
    request_sku_ids, so the graph cannot say the draft dropped them."""
    check = check_graph_integrity(_reader(db_session, make_reader), _draft("SKU-E-A1"), ())

    assert check.violations == []


def test_an_unreachable_graph_raises_instead_of_passing():
    with pytest.raises(GraphUnavailable):
        check_graph_integrity(FailingGraphReader(), _draft("SKU-E-A1"), ("SKU-E-A1",))


def test_the_graph_is_current_right_after_a_build(db_session, make_reader):
    reader = _reader(db_session, make_reader)

    assert graph_is_current(db_session, reader) is True


def test_the_graph_is_stale_once_postgres_moves_on(db_session, make_reader):
    """(Review Focus) A SKU discontinued after the build must not be approved by an old graph."""
    reader = _reader(db_session, make_reader)

    db_session.get(Sku, "SKU-E-A1").discontinued = True
    db_session.flush()

    assert graph_is_current(db_session, reader) is False


def test_a_graph_that_was_never_built_is_not_current(db_session, graph_client, graph_ns):
    from app.graph.reader import GraphReader

    seed_world(db_session)

    assert graph_is_current(db_session, GraphReader(graph_client, graph_ns)) is False


def test_freshness_check_propagates_an_outage(db_session):
    seed_world(db_session)

    with pytest.raises(GraphUnavailable):
        graph_is_current(db_session, FailingGraphReader())
