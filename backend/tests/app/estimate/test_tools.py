from datetime import date

import pytest

from app.estimate.tools import (
    TOOL_SPECS, ToolContext, check_stock, get_related_parts, handle_tool, lookup_customer, predict_price,
    search_price_book,
)
from tests.app.estimate.seed import AS_OF, seed_world


def _ctx(session, as_of=AS_OF):
    return ToolContext(session=session, as_of=as_of)


def test_lookup_customer_by_id_returns_contract_terms(db_session):
    seed_world(db_session)

    result = lookup_customer(_ctx(db_session), query="CUST-E1")

    match = result["matches"][0]
    assert match["customer_id"] == "CUST-E1"
    contract = match["contracts"][0]
    assert contract["contract_id"] == "CTR-E1"
    assert contract["discount_pct"] == 10.0
    assert contract["covered_categories"] == ["Cat-E-A"]
    assert contract["active_on_as_of"] is True


def test_lookup_customer_marks_contract_inactive_outside_its_dates(db_session):
    seed_world(db_session)

    result = lookup_customer(_ctx(db_session, as_of=date(2026, 1, 1)), query="CUST-E1")

    assert result["matches"][0]["contracts"][0]["active_on_as_of"] is False


def test_lookup_customer_by_fuzzy_name(db_session):
    seed_world(db_session)

    result = lookup_customer(_ctx(db_session), query="vexthorn mechanical")

    assert [m["customer_id"] for m in result["matches"]][0] == "CUST-E1"


def test_lookup_customer_with_no_match_returns_empty(db_session):
    seed_world(db_session)

    assert lookup_customer(_ctx(db_session), query="qqqqzzzz nothing like this")["matches"] == []


def test_search_price_book_by_exact_id_returns_prices(db_session):
    seed_world(db_session)

    entry = search_price_book(_ctx(db_session), query="SKU-E-A1")["results"][0]

    assert entry["sku_id"] == "SKU-E-A1"
    assert entry["list_price"] == 100.0
    assert entry["last_realized_price"] == 97.0
    assert entry["in_stock"] is True


def test_search_price_book_by_fuzzy_name_ranks_best_first(db_session):
    seed_world(db_session)

    results = search_price_book(_ctx(db_session), query="Zorpwidget Alpha 9000")["results"]

    assert results[0]["sku_id"] == "SKU-E-A1"


def test_search_price_book_reports_gap_sku_as_unpriced(db_session):
    seed_world(db_session)

    entry = search_price_book(_ctx(db_session), query="SKU-E-GAP")["results"][0]

    assert entry["list_price"] is None
    assert entry["last_realized_price"] is None


def test_check_stock_reports_stock_and_discontinued(db_session):
    seed_world(db_session)

    assert check_stock(_ctx(db_session), sku_id="SKU-E-OLD") == {
        "sku_id": "SKU-E-OLD", "in_stock": False, "discontinued": True,
    }
    assert "error" in check_stock(_ctx(db_session), sku_id="SKU-NOPE")


def test_get_related_parts_returns_replacement_for_discontinued_sku(db_session):
    seed_world(db_session)

    result = get_related_parts(_ctx(db_session), sku_id="SKU-E-OLD")

    assert result["replacement"]["sku_id"] == "SKU-E-A1"
    assert result["required_parts"] == []


def test_get_related_parts_returns_required_parts(db_session):
    seed_world(db_session)

    result = get_related_parts(_ctx(db_session), sku_id="SKU-E-B1")

    assert result["replacement"] is None
    assert [p["sku_id"] for p in result["required_parts"]] == ["SKU-E-A1"]


def test_predict_price_for_gap_sku_is_tagged_predicted(db_session):
    seed_world(db_session)

    result = predict_price(_ctx(db_session), sku_id="SKU-E-GAP")

    assert result == {
        "sku_id": "SKU-E-GAP", "price_source": "predicted", "predicted_price": 20.0,
        "low": 15.0, "high": 25.0, "peer_count": 3,
    }


def test_predict_price_refuses_a_sku_that_has_a_list_price(db_session):
    seed_world(db_session)

    assert "list price" in predict_price(_ctx(db_session), sku_id="SKU-E-A1")["error"]


def test_predict_price_errors_when_category_has_too_few_peers(db_session):
    seed_world(db_session)

    assert "peers" in predict_price(_ctx(db_session), sku_id="SKU-E-LONE")["error"]


def test_handle_tool_dispatches_by_name(db_session):
    seed_world(db_session)

    result = handle_tool(_ctx(db_session), "check_stock", {"sku_id": "SKU-E-A1"})

    assert result["in_stock"] is True


def test_handle_tool_reports_unknown_tool_and_bad_arguments(db_session):
    seed_world(db_session)

    assert "unknown tool" in handle_tool(_ctx(db_session), "delete_everything", {})["error"]
    assert "bad arguments" in handle_tool(_ctx(db_session), "check_stock", {"wrong": 1})["error"]


@pytest.mark.parametrize("bad_value", [123, ["SKU-E-A1"], None, {"id": "SKU-E-A1"}])
def test_handle_tool_rejects_non_string_arguments_before_running_the_handler(db_session, bad_value):
    seed_world(db_session)

    result = handle_tool(_ctx(db_session), "search_price_book", {"query": bad_value})

    assert result == {"error": "bad arguments for search_price_book: query must be a string"}


def test_handle_tool_still_runs_a_call_with_string_arguments(db_session):
    seed_world(db_session)

    result = handle_tool(_ctx(db_session), "search_price_book", {"query": "SKU-E-A1"})

    assert result["results"][0]["sku_id"] == "SKU-E-A1"


def test_tool_specs_name_every_handler_plus_submit_draft():
    names = {spec["function"]["name"] for spec in TOOL_SPECS}

    assert names == {
        "lookup_customer", "search_price_book", "check_stock", "get_related_parts", "predict_price", "submit_draft",
    }
