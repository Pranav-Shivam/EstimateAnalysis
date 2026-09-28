import logging
import uuid
from datetime import datetime, timezone

import pytest

from app.dedupe.repository import save_verdict
from app.estimate.models import EstimateDraftRow
from app.graph.constant import VARIANT_MIN_JACCARD
from app.graph.repository import node_key
from app.graph.service import (
    rebuild_graph, sync_best_effort, sync_dedupe_verdicts, sync_quote, sync_quote_request,
)
from app.intake.repository import save_quote_request
from app.reference_data.repository import reference_fingerprint
from core.graph.client import GraphUnavailable
from tests.app.estimate.seed import seed_structure, seed_world
from tests.graph_support import FailingGraphClient, graph_edge_count, graph_node


def _world(db_session, make_reader):
    seed_world(db_session)
    seed_structure(db_session)
    return make_reader()


def _request(session, *, customer_id="CUST-E1", hint=None, site_id=None, case_id=None):
    extraction = {"site_hint": hint} if hint else {}
    return save_quote_request(
        session, raw_email_text="x", parsed_json={"extraction": extraction, "resolved_line_items": []},
        content_fingerprint={"sku_ids": ["SKU-E-A1"]}, style_fingerprint={"tokens": []},
        customer_id=customer_id, site_id=site_id, case_id=case_id,
    )


def _draft_row(session, request_id, created_at, draft, status="ready"):
    row = EstimateDraftRow(
        id=uuid.uuid4(), quote_request_id=request_id, status=status, draft=draft, violations=[], iterations=1,
        reason=None, created_at=created_at,
    )
    session.add(row)
    session.flush()
    return row


def _line(sku_id, unit_price, discount_pct=0.0, price_source="list"):
    return {"sku_id": sku_id, "quantity": 1, "unit_price": unit_price, "price_source": price_source,
            "discount_pct": discount_pct}


T1 = datetime(2024, 9, 1, 9, 0, tzinfo=timezone.utc)
T2 = datetime(2024, 9, 1, 10, 0, tzinfo=timezone.utc)


def test_sync_quote_request_creates_the_node(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    row = _request(db_session, case_id="sc-9")

    sync_quote_request(db_session, graph_client, graph_ns, row.id)

    node = graph_node(graph_client, graph_ns, str(row.id))
    assert node["labels"] == ["QuoteRequest"]
    assert node["props"]["case_id"] == "sc-9"


def test_a_zip_in_the_site_hint_links_the_request_to_that_sites_project(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    row = _request(db_session, hint="the job at 62701")

    sync_quote_request(db_session, graph_client, graph_ns, row.id)

    assert graph_edge_count(graph_client, graph_ns, str(row.id), "FOR_PROJECT", "PRJ-E1") == 1


def test_an_ambiguous_site_hint_links_nothing(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    row = _request(db_session, hint="12 Elm Street")

    sync_quote_request(db_session, graph_client, graph_ns, row.id)

    assert graph_edge_count(graph_client, graph_ns, str(row.id), "FOR_PROJECT", "PRJ-E1") == 0
    assert graph_edge_count(graph_client, graph_ns, str(row.id), "FOR_PROJECT", "PRJ-E2") == 0


def test_no_hint_or_no_customer_links_nothing(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    no_hint = _request(db_session)
    no_customer = _request(db_session, customer_id=None, hint="62701")

    sync_quote_request(db_session, graph_client, graph_ns, no_hint.id)
    sync_quote_request(db_session, graph_client, graph_ns, no_customer.id)

    for row in (no_hint, no_customer):
        assert graph_edge_count(graph_client, graph_ns, str(row.id), "FOR_PROJECT", "PRJ-E1") == 0


def test_a_resolved_site_id_wins_over_the_hint(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    row = _request(db_session, hint="62701", site_id="SITE-E2")

    sync_quote_request(db_session, graph_client, graph_ns, row.id)

    assert graph_edge_count(graph_client, graph_ns, str(row.id), "FOR_PROJECT", "PRJ-E2") == 1
    assert graph_edge_count(graph_client, graph_ns, str(row.id), "FOR_PROJECT", "PRJ-E1") == 0


def test_sync_quote_request_is_idempotent(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    row = _request(db_session, hint="62701")

    sync_quote_request(db_session, graph_client, graph_ns, row.id)
    sync_quote_request(db_session, graph_client, graph_ns, row.id)

    assert graph_edge_count(graph_client, graph_ns, str(row.id), "FOR_PROJECT", "PRJ-E1") == 1
    nodes = graph_client.read("MATCH (n:QuoteRequest {key: $key}) RETURN count(n) AS c", key=node_key(graph_ns, str(row.id)))
    assert nodes == [{"c": 1}]


def test_sync_quote_request_rejects_an_unknown_id(db_session, graph_client, graph_ns):
    with pytest.raises(ValueError):
        sync_quote_request(db_session, graph_client, graph_ns, uuid.uuid4())


def _pair(db_session, *, other_customer="CUST-E1"):
    target = _request(db_session)
    candidate = _request(db_session, customer_id=other_customer)
    return target, candidate


def _verdict(db_session, target, candidate, verdict, jaccard):
    save_verdict(
        db_session, quote_request_id=target.id, candidate_quote_request_id=candidate.id, verdict=verdict,
        content_jaccard=jaccard, style_jaccard=0.0, signals_fired=[],
    )


def test_duplicate_and_revision_verdicts_become_edges_with_their_score(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    target, duplicate = _pair(db_session)
    revision = _request(db_session)
    _verdict(db_session, target, duplicate, "DUPLICATE_OF", 1.0)
    _verdict(db_session, target, revision, "REVISION_OF", 0.5)

    sync_dedupe_verdicts(db_session, graph_client, graph_ns, target.id)

    assert graph_edge_count(graph_client, graph_ns, str(target.id), "DUPLICATE_OF", str(duplicate.id)) == 1
    assert graph_edge_count(graph_client, graph_ns, str(target.id), "REVISION_OF", str(revision.id)) == 1
    scores = graph_client.read(
        "MATCH ({key: $key})-[r:DUPLICATE_OF]->() RETURN r.content_jaccard AS score", key=node_key(graph_ns, str(target.id)),
    )
    assert scores == [{"score": 1.0}]


def test_a_same_customer_distinct_pair_with_enough_overlap_is_a_variant(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    target, candidate = _pair(db_session)
    _verdict(db_session, target, candidate, "DISTINCT", VARIANT_MIN_JACCARD)

    sync_dedupe_verdicts(db_session, graph_client, graph_ns, target.id)

    assert graph_edge_count(graph_client, graph_ns, str(target.id), "VARIANT_OF", str(candidate.id)) == 1


def test_a_distinct_pair_below_the_overlap_floor_is_not_a_variant(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    target, candidate = _pair(db_session)
    _verdict(db_session, target, candidate, "DISTINCT", VARIANT_MIN_JACCARD - 0.01)

    sync_dedupe_verdicts(db_session, graph_client, graph_ns, target.id)

    assert graph_edge_count(graph_client, graph_ns, str(target.id), "VARIANT_OF", str(candidate.id)) == 0


def test_a_distinct_pair_across_customers_is_never_a_variant(db_session, graph_client, graph_ns, make_reader):
    """(Review Focus) Same-looking requests from different customers are unrelated, not variants."""
    _world(db_session, make_reader)
    target, candidate = _pair(db_session, other_customer="CUST-E2")
    _verdict(db_session, target, candidate, "DISTINCT", 0.9)

    sync_dedupe_verdicts(db_session, graph_client, graph_ns, target.id)

    assert graph_edge_count(graph_client, graph_ns, str(target.id), "VARIANT_OF", str(candidate.id)) == 0


def test_sync_dedupe_verdicts_is_idempotent_and_needs_no_verdicts(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    target, candidate = _pair(db_session)
    _verdict(db_session, target, candidate, "DUPLICATE_OF", 1.0)

    sync_dedupe_verdicts(db_session, graph_client, graph_ns, target.id)
    sync_dedupe_verdicts(db_session, graph_client, graph_ns, target.id)
    sync_dedupe_verdicts(db_session, graph_client, graph_ns, candidate.id)

    assert graph_edge_count(graph_client, graph_ns, str(target.id), "DUPLICATE_OF", str(candidate.id)) == 1


def _variance(client, ns, quote_id):
    return client.read(
        "MATCH ({key: $key})-[r:PRICE_VARIANCE]->(s:SKU) RETURN s.id AS sku, properties(r) AS props ORDER BY s.id, r.line_index",
        key=node_key(ns, str(quote_id)),
    )


def test_a_quote_gets_price_variance_edges_only_for_discounted_or_predicted_lines(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    request = _request(db_session)
    draft = {"customer_id": "CUST-E1", "contract_id": "CTR-E1", "lines": [
        _line("SKU-E-A1", 100.0, discount_pct=10.0),
        _line("SKU-E-GAP", 20.0, price_source="predicted"),
        _line("SKU-E-B1", 50.0),
    ]}
    row = _draft_row(db_session, request.id, T1, draft)

    sync_quote(db_session, graph_client, graph_ns, row.id)

    node = graph_node(graph_client, graph_ns, str(row.id))
    assert node["props"]["status"] == "ready" and node["props"]["quote_request_id"] == str(request.id)
    variance = _variance(graph_client, graph_ns, row.id)
    assert [v["sku"] for v in variance] == ["SKU-E-A1", "SKU-E-GAP"]
    discounted, predicted = variance[0]["props"], variance[1]["props"]
    assert discounted["list_price"] == 100.0 and discounted["unit_price"] == 100.0
    assert discounted["discount_pct"] == 10.0 and discounted["net_unit_price"] == 90.0
    assert discounted["price_source"] == "list" and discounted["line_index"] == 0
    assert "list_price" not in predicted and predicted["price_source"] == "predicted"
    assert predicted["net_unit_price"] == 20.0


def test_syncing_a_quote_twice_does_not_duplicate_edges(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    request = _request(db_session)
    row = _draft_row(db_session, request.id, T1, {"lines": [_line("SKU-E-A1", 100.0, discount_pct=10.0)]})

    sync_quote(db_session, graph_client, graph_ns, row.id)
    sync_quote(db_session, graph_client, graph_ns, row.id)

    assert len(_variance(graph_client, graph_ns, row.id)) == 1


def test_a_quote_with_no_draft_is_just_a_node(db_session, graph_client, graph_ns, make_reader):
    """(Review Focus) The agent never submitted: draft is SQL NULL."""
    _world(db_session, make_reader)
    request = _request(db_session)
    row = _draft_row(db_session, request.id, T1, None, status="needs_review")

    sync_quote(db_session, graph_client, graph_ns, row.id)

    assert graph_node(graph_client, graph_ns, str(row.id))["props"]["status"] == "needs_review"
    assert _variance(graph_client, graph_ns, row.id) == []


def test_a_later_quote_supersedes_the_earlier_one_for_the_same_request(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    request = _request(db_session)
    other_request = _request(db_session)
    first = _draft_row(db_session, request.id, T1, {"lines": []})
    second = _draft_row(db_session, request.id, T2, {"lines": []})
    unrelated = _draft_row(db_session, other_request.id, T2, {"lines": []})

    sync_quote(db_session, graph_client, graph_ns, second.id)
    sync_quote(db_session, graph_client, graph_ns, unrelated.id)
    sync_quote(db_session, graph_client, graph_ns, first.id)

    assert graph_edge_count(graph_client, graph_ns, str(second.id), "SUPERSEDES", str(first.id)) == 1
    assert graph_edge_count(graph_client, graph_ns, str(first.id), "SUPERSEDES", str(second.id)) == 0
    assert graph_edge_count(graph_client, graph_ns, str(unrelated.id), "SUPERSEDES", str(first.id)) == 0


def test_quotes_with_identical_timestamps_do_not_supersede_each_other(db_session, graph_client, graph_ns, make_reader):
    """(Review Focus) One transaction stamps every row with the same created_at."""
    _world(db_session, make_reader)
    request = _request(db_session)
    first = _draft_row(db_session, request.id, T1, {"lines": []})
    second = _draft_row(db_session, request.id, T1, {"lines": []})

    sync_quote(db_session, graph_client, graph_ns, first.id)
    sync_quote(db_session, graph_client, graph_ns, second.id)

    assert graph_edge_count(graph_client, graph_ns, str(second.id), "SUPERSEDES", str(first.id)) == 0
    assert graph_edge_count(graph_client, graph_ns, str(first.id), "SUPERSEDES", str(second.id)) == 0


def test_sync_quote_rejects_an_unknown_id(db_session, graph_client, graph_ns):
    with pytest.raises(ValueError):
        sync_quote(db_session, graph_client, graph_ns, uuid.uuid4())


def test_rebuild_graph_restores_runtime_entities_from_postgres(db_session, graph_client, graph_ns, make_reader):
    _world(db_session, make_reader)
    target, candidate = _pair(db_session)
    _verdict(db_session, target, candidate, "DUPLICATE_OF", 1.0)
    draft = _draft_row(db_session, target.id, T1, {"lines": [_line("SKU-E-A1", 100.0, discount_pct=10.0)]})

    first = rebuild_graph(db_session, graph_client, graph_ns)
    second = rebuild_graph(db_session, graph_client, graph_ns)

    assert graph_edge_count(graph_client, graph_ns, str(target.id), "DUPLICATE_OF", str(candidate.id)) == 1
    assert len(_variance(graph_client, graph_ns, draft.id)) == 1
    assert first == second
    assert first.namespace == graph_ns
    assert first.fingerprint == reference_fingerprint(db_session)
    assert first.node_counts["QuoteRequest"] >= 2 and first.node_counts["Quote"] >= 1
    assert first.edge_counts["DUPLICATE_OF"] >= 1


def test_sync_best_effort_swallows_graph_errors_and_logs(caplog):
    calls = []

    def sync(*args):
        calls.append(args)
        raise GraphUnavailable("down")

    with caplog.at_level(logging.WARNING):
        sync_best_effort("quote request", sync, "a", "b")

    assert calls == [("a", "b")]
    assert "graph sync failed for quote request" in caplog.text


def test_sync_best_effort_does_not_hide_other_errors():
    def sync():
        raise RuntimeError("a real bug")

    with pytest.raises(RuntimeError):
        sync_best_effort("quote request", sync)


def test_failing_graph_client_is_a_graph_unavailable_source(db_session, graph_ns):
    seed_world(db_session)
    row = _request(db_session)

    with pytest.raises(GraphUnavailable):
        sync_quote_request(db_session, FailingGraphClient(), graph_ns, row.id)
