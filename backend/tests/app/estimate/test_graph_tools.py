from datetime import date

import pytest
from sqlalchemy import delete

from app.estimate.tools import (
    TOOL_SPECS, ToolContext, ask_knowledge, check_contract_coverage, get_related_parts, handle_tool,
)
from app.reference_data.models import Sku
from app.reference_data.repository import upsert_sku
from app.retrieval.models import SkuEmbedding
from tests.app.estimate.seed import AS_OF, seed_chain_world, seed_world
from tests.graph_support import FailingGraphReader, UnusedGraph, make_ctx


def _ctx(db_session, make_reader, **kwargs):
    seed_world(db_session)
    seed_chain_world(db_session)
    return make_ctx(db_session, make_reader(), **kwargs)


A1 = {"sku_id": "SKU-E-A1", "name": "Zorpwidget Alpha 9000", "discontinued": False, "in_stock": True}


def test_a_live_sku_is_its_own_live_sku_and_lists_its_required_parts(db_session, make_reader):
    result = get_related_parts(_ctx(db_session, make_reader), sku_id="SKU-E-B1")

    assert result == {
        "sku_id": "SKU-E-B1", "discontinued": False, "replacement_chain": [], "replacement": None,
        "live_sku_id": "SKU-E-B1", "required_parts": [A1], "evidence_path": ["SKU-E-B1"],
    }


def test_a_discontinued_sku_returns_its_live_replacement(db_session, make_reader):
    result = get_related_parts(_ctx(db_session, make_reader), sku_id="SKU-E-OLD")

    assert result["discontinued"] is True
    assert result["replacement"] == A1
    assert result["replacement_chain"] == ["SKU-E-A1"]
    assert result["live_sku_id"] == "SKU-E-A1"
    assert result["required_parts"] == []
    assert result["evidence_path"] == ["SKU-E-OLD", "REPLACED_BY", "SKU-E-A1"]


def test_a_two_hop_chain_reports_every_hop(db_session, make_reader):
    result = get_related_parts(_ctx(db_session, make_reader), sku_id="SKU-E-OLD2")

    assert result["replacement_chain"] == ["SKU-E-OLD", "SKU-E-A1"]
    assert result["live_sku_id"] == "SKU-E-A1"


def test_required_parts_come_from_the_live_end_of_the_chain(db_session, make_reader):
    seed_world(db_session)
    upsert_sku(db_session, sku_id="SKU-L-OLDB", name="Old B", category="Cat-E-B", list_price=1.0,
               discontinued=True, replaced_by=None, in_stock=False)
    db_session.flush()
    db_session.get(Sku, "SKU-L-OLDB").replaced_by = "SKU-E-B1"
    db_session.flush()

    result = get_related_parts(make_ctx(db_session, make_reader()), sku_id="SKU-L-OLDB")

    assert result["live_sku_id"] == "SKU-E-B1"
    assert [p["sku_id"] for p in result["required_parts"]] == ["SKU-E-A1"]


def test_a_discontinued_sku_with_no_replacement_has_no_live_sku(db_session, make_reader):
    result = get_related_parts(_ctx(db_session, make_reader), sku_id="SKU-E-DEAD")

    assert result["live_sku_id"] is None and result["replacement"] is None
    assert result["required_parts"] == [] and result["discontinued"] is True


def test_a_replacement_cycle_returns_no_live_sku(db_session, make_reader):
    result = get_related_parts(_ctx(db_session, make_reader), sku_id="SKU-E-CYC1")

    assert result["live_sku_id"] is None


def test_a_live_sku_requiring_a_discontinued_part_reports_it_as_discontinued(db_session, make_reader):
    result = get_related_parts(_ctx(db_session, make_reader), sku_id="SKU-E-NEEDOLD")

    assert [(p["sku_id"], p["discontinued"]) for p in result["required_parts"]] == [("SKU-E-OLD", True)]


def test_related_parts_for_an_unknown_sku_is_an_error(db_session, make_reader):
    assert get_related_parts(_ctx(db_session, make_reader), sku_id="SKU-NOPE") == {"error": "unknown SKU SKU-NOPE"}


def test_related_parts_with_the_graph_down_returns_an_error_and_does_not_raise(db_session):
    seed_world(db_session)

    result = get_related_parts(make_ctx(db_session, FailingGraphReader()), sku_id="SKU-E-A1")

    assert "knowledge graph unavailable" in result["error"]


def test_coverage_says_the_discount_applies_for_a_covered_active_contract(db_session, make_reader):
    result = check_contract_coverage(_ctx(db_session, make_reader), customer_id="CUST-E1", sku_id="SKU-E-A1")

    assert result["sku_category"] == "Cat-E-A"
    [contract] = result["contracts"]
    assert contract["contract_id"] == "CTR-E1" and contract["discount_pct"] == 10.0
    assert contract["covered"] is True and contract["active_on_as_of"] is True
    assert contract["discount_applies"] is True
    assert "is covered by contract CTR-E1" in contract["reason"] and "active" in contract["reason"]
    assert contract["evidence_path"] == ["CUST-E1", "HOLDS", "CTR-E1", "COVERS", "Cat-E-A", "PRICED_IN", "SKU-E-A1"]


def test_coverage_says_no_discount_for_an_uncovered_category(db_session, make_reader):
    result = check_contract_coverage(_ctx(db_session, make_reader), customer_id="CUST-E1", sku_id="SKU-E-B1")

    [contract] = result["contracts"]
    assert contract["covered"] is False and contract["discount_applies"] is False
    assert "category Cat-E-B is not covered by contract CTR-E1" in contract["reason"]
    assert "Cat-E-A" in contract["reason"]
    assert contract["evidence_path"] == ["CUST-E1", "HOLDS", "CTR-E1"]


def test_coverage_says_no_discount_when_the_contract_is_not_active(db_session, make_reader):
    ctx = _ctx(db_session, make_reader, as_of=date(2026, 1, 1))

    [contract] = check_contract_coverage(ctx, customer_id="CUST-E1", sku_id="SKU-E-A1")["contracts"]

    assert contract["covered"] is True and contract["active_on_as_of"] is False
    assert contract["discount_applies"] is False
    assert "not active on 2026-01-01" in contract["reason"]


def test_coverage_for_a_customer_without_contracts_is_empty(db_session, make_reader):
    result = check_contract_coverage(_ctx(db_session, make_reader), customer_id="CUST-E2", sku_id="SKU-E-A1")

    assert result["contracts"] == [] and result["sku_category"] is None


def test_coverage_for_an_unknown_sku_is_an_error(db_session, make_reader):
    result = check_contract_coverage(_ctx(db_session, make_reader), customer_id="CUST-E1", sku_id="SKU-NOPE")

    assert result == {"error": "unknown SKU SKU-NOPE"}


def test_coverage_with_the_graph_down_returns_an_error(db_session):
    seed_world(db_session)

    result = check_contract_coverage(make_ctx(db_session, FailingGraphReader()), customer_id="CUST-E1", sku_id="SKU-E-A1")

    assert "knowledge graph unavailable" in result["error"]


def test_ask_knowledge_returns_the_route_rule_and_evidence(db_session, make_reader):
    result = ask_knowledge(_ctx(db_session, make_reader), question="what does SKU-E-B1 require")

    assert (result["route"], result["rule"]) == ("graph_local", "id_with_relationship_phrasing")
    assert "SKU-E-A1" in {n["id"] for n in result["evidence"]["nodes"]}


def test_ask_knowledge_reports_a_missing_vector_index_as_an_error(db_session, make_reader):
    ctx = _ctx(db_session, make_reader)
    db_session.execute(delete(SkuEmbedding))
    db_session.flush()

    result = ask_knowledge(ctx, question="something like a zorpwidget")

    assert "embed_skus" in result["error"]


def test_ask_knowledge_with_the_graph_down_returns_an_error(db_session):
    seed_world(db_session)

    result = ask_knowledge(make_ctx(db_session, FailingGraphReader()), question="what does SKU-E-B1 require")

    assert "unavailable" in result["error"]


def test_handle_tool_dispatches_the_new_tools_and_rejects_non_string_arguments(db_session, make_reader):
    ctx = _ctx(db_session, make_reader)

    assert handle_tool(ctx, "get_related_parts", {"sku_id": "SKU-E-OLD"})["live_sku_id"] == "SKU-E-A1"
    assert handle_tool(ctx, "check_contract_coverage", {"customer_id": "CUST-E1", "sku_id": "SKU-E-A1"})["contracts"]
    assert handle_tool(ctx, "check_contract_coverage", {"customer_id": 1, "sku_id": "SKU-E-A1"}) == {
        "error": "bad arguments for check_contract_coverage: customer_id must be a string",
    }
    assert "bad arguments" in handle_tool(ctx, "ask_knowledge", {})["error"]


def test_tool_context_requires_every_request_anchor():
    """The customer and SKU anchors have no default, so a caller cannot forget them (a Phase 3 gap)."""
    with pytest.raises(TypeError):
        ToolContext(session=None, as_of=AS_OF, graph=UnusedGraph(), knowledge=None)


def test_tool_specs_describe_the_new_tools_with_string_parameters():
    specs = {s["function"]["name"]: s["function"] for s in TOOL_SPECS}

    assert specs["check_contract_coverage"]["parameters"]["required"] == ["customer_id", "sku_id"]
    assert specs["ask_knowledge"]["parameters"]["required"] == ["question"]
    assert "live_sku_id" in specs["get_related_parts"]["description"]
