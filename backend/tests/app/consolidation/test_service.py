import uuid

import pytest

from app.consolidation.service import consolidate_review_item
from app.estimate.repository import save_estimate_draft
from app.intake.repository import save_quote_request
from app.judge.models import JudgeVerdictRow, ReviewItemRow
from app.reference_data.models import Contract, Sku, SkuRequirement
from app.reference_data.repository import reference_fingerprint
from tests.app.estimate.seed import seed_world
from tests.graph_support import graph_edge_count, graph_node


def _estimate_draft_id(session) -> uuid.UUID:
    # judge_verdicts.estimate_id and review_items.estimate_id carry a real foreign key to estimate_drafts.id
    # (migration 0005), so a corrected review item under test needs a real draft row, not a bare uuid4().
    request = save_quote_request(
        session, raw_email_text="need parts", parsed_json={"resolved_line_items": []},
        content_fingerprint={}, style_fingerprint={}, customer_id="CUST-E1", contract_id="CTR-E1",
    )
    row = save_estimate_draft(
        session, quote_request_id=request.id, status="ready", draft={"customer_id": "CUST-E1", "lines": []},
        violations=[], iterations=1, reason=None,
    )
    return row.id


def _corrected_review_item(session, dimension, correction, evidence):
    estimate_id = _estimate_draft_id(session)
    verdict = JudgeVerdictRow(
        id=uuid.uuid4(), estimate_id=estimate_id, model="m", dimensions=[], overall_confidence=0.1,
        flagged_dimension=dimension, trusted=False,
    )
    session.add(verdict)
    session.flush()
    row = ReviewItemRow(
        id=uuid.uuid4(), judge_verdict_id=verdict.id, estimate_id=verdict.estimate_id, dimension=dimension,
        fact="x", evidence=evidence, line_index=None, status="corrected", outcome="corrected", correction=correction,
    )
    session.add(row)
    session.flush()
    return row


def _world(db_session, make_reader):
    seed_world(db_session)
    return make_reader()


def test_price_provenance_handler_sets_list_price_and_syncs_the_graph(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    row = _corrected_review_item(
        db_session, "price_provenance", {"sku_id": "SKU-E-GAP", "corrected_unit_price": 42.5},
        {"lines": [{"line_index": 0, "sku_id": "SKU-E-GAP"}]},
    )

    consolidate_review_item(db_session, graph_client, graph_ns, row.id)

    assert db_session.get(Sku, "SKU-E-GAP").list_price == 42.5
    assert graph_node(graph_client, graph_ns, "SKU-E-GAP")["props"]["list_price"] == 42.5
    assert db_session.get(ReviewItemRow, row.id).status == "consolidated"


def test_graph_completion_handler_adds_requirement_and_keeps_graph_current(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    row = _corrected_review_item(
        db_session, "graph_completion", {"sku_id": "SKU-E-GAP", "required_sku_id": "SKU-E-A1"},
        {"lines": [{"line_index": 0, "sku_id": "SKU-E-GAP"}]},
    )

    consolidate_review_item(db_session, graph_client, graph_ns, row.id)

    assert db_session.get(SkuRequirement, ("SKU-E-GAP", "SKU-E-A1")) is not None
    assert graph_edge_count(graph_client, graph_ns, "SKU-E-GAP", "REQUIRES", "SKU-E-A1") == 1
    from app.graph.reader import GraphReader
    assert GraphReader(graph_client, graph_ns).stored_fingerprint() == reference_fingerprint(db_session)


def test_graph_completion_handler_is_idempotent_on_a_second_run(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    row = _corrected_review_item(
        db_session, "graph_completion", {"sku_id": "SKU-E-GAP", "required_sku_id": "SKU-E-A1"},
        {"lines": [{"line_index": 0, "sku_id": "SKU-E-GAP"}]},
    )
    consolidate_review_item(db_session, graph_client, graph_ns, row.id)
    db_session.get(ReviewItemRow, row.id).status = "corrected"
    db_session.flush()

    consolidate_review_item(db_session, graph_client, graph_ns, row.id)

    assert graph_edge_count(graph_client, graph_ns, "SKU-E-GAP", "REQUIRES", "SKU-E-A1") == 1


def test_contract_discount_handler_adds_coverage_and_keeps_graph_current(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    row = _corrected_review_item(
        db_session, "contract_discount", {"contract_id": "CTR-E1", "category": "Cat-E-B"},
        {"lines": [{"line_index": 0, "sku_id": "SKU-E-B1", "contract_id": "CTR-E1"}]},
    )

    consolidate_review_item(db_session, graph_client, graph_ns, row.id)

    assert db_session.get(Contract, "CTR-E1").covered_categories == ["Cat-E-A", "Cat-E-B"]
    assert graph_edge_count(graph_client, graph_ns, "CTR-E1", "COVERS", "Cat-E-B") == 1
    from app.graph.reader import GraphReader
    assert GraphReader(graph_client, graph_ns).stored_fingerprint() == reference_fingerprint(db_session)


def test_consolidate_review_item_rejects_a_row_not_in_corrected_status(db_session, graph_client, graph_ns):
    seed_world(db_session)
    verdict = JudgeVerdictRow(
        id=uuid.uuid4(), estimate_id=_estimate_draft_id(db_session), model="m", dimensions=[], overall_confidence=0.9,
        flagged_dimension="price_provenance", trusted=True,
    )
    db_session.add(verdict)
    db_session.flush()
    row = ReviewItemRow(
        id=uuid.uuid4(), judge_verdict_id=verdict.id, estimate_id=verdict.estimate_id, dimension="price_provenance",
        fact="x", evidence={"lines": []}, line_index=None, status="open",
    )
    db_session.add(row)
    db_session.flush()

    with pytest.raises(ValueError):
        consolidate_review_item(db_session, graph_client, graph_ns, row.id)


def test_consolidating_an_already_consolidated_item_is_a_no_op(db_session, graph_client, graph_ns, make_reader):
    # A redelivered job (a retry after the commit landed, or a redrive) must not fail the worker or rewrite the fact.
    _world(db_session, make_reader)
    row = _corrected_review_item(
        db_session, "price_provenance", {"sku_id": "SKU-E-GAP", "corrected_unit_price": 42.5},
        {"lines": [{"line_index": 0, "sku_id": "SKU-E-GAP"}]},
    )
    consolidate_review_item(db_session, graph_client, graph_ns, row.id)
    db_session.get(Sku, "SKU-E-GAP").list_price = 99.0
    db_session.flush()

    consolidate_review_item(db_session, graph_client, graph_ns, row.id)

    assert db_session.get(ReviewItemRow, row.id).status == "consolidated"
    assert db_session.get(Sku, "SKU-E-GAP").list_price == 99.0
