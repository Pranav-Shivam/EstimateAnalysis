from app.reference_data.repository import upsert_sku
from app.reference_data.search import find_customers, find_skus
from tests.app.estimate.seed import seed_world


def test_an_exact_sku_id_wins_over_any_fuzzy_match(db_session):
    seed_world(db_session)

    assert [s.sku_id for s in find_skus(db_session, "SKU-E-A1")] == ["SKU-E-A1"]


def test_fuzzy_name_search_ranks_the_best_match_first(db_session):
    seed_world(db_session)

    assert find_skus(db_session, "Zorpwidget Alpha 9000")[0].sku_id == "SKU-E-A1"


def test_name_ties_break_by_sku_id(db_session):
    seed_world(db_session)
    for sku_id in ("SKU-TIE-2", "SKU-TIE-1"):
        upsert_sku(db_session, sku_id=sku_id, name="Quillfargle Tiebreak Unit", category="Cat-TIE", list_price=5.0,
                   discontinued=False, replaced_by=None, in_stock=True)
    db_session.flush()

    ids = [s.sku_id for s in find_skus(db_session, "Quillfargle Tiebreak Unit")]

    assert ids.index("SKU-TIE-1") < ids.index("SKU-TIE-2")


def test_an_unrelated_query_matches_nothing(db_session):
    seed_world(db_session)

    assert find_skus(db_session, "qqqqzzzz nothing like this") == []
    assert find_customers(db_session, "qqqqzzzz nothing like this") == []


def test_customer_lookup_by_id_and_by_fuzzy_name(db_session):
    seed_world(db_session)

    assert [c.customer_id for c in find_customers(db_session, "CUST-E1")] == ["CUST-E1"]
    assert find_customers(db_session, "vexthorn mechanical")[0].customer_id == "CUST-E1"
