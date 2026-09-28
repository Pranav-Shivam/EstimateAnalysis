from app.estimate.pricing import PEER_MIN, predict_price_for_sku
from app.reference_data.repository import get_sku, upsert_sku
from tests.app.estimate.seed import seed_world


def test_prediction_uses_category_peer_median_and_quartiles(db_session):
    seed_world(db_session)

    prediction = predict_price_for_sku(db_session, get_sku(db_session, "SKU-E-GAP"))

    assert prediction.price == 20.0
    assert prediction.low == 15.0
    assert prediction.high == 25.0
    assert prediction.peer_count == 3


def test_prediction_is_none_without_enough_peers(db_session):
    seed_world(db_session)

    assert predict_price_for_sku(db_session, get_sku(db_session, "SKU-E-LONE")) is None


def test_prediction_needs_at_least_peer_min_priced_peers(db_session):
    upsert_sku(db_session, sku_id="SKU-PP1", name="a", category="Cat-PP", list_price=10.0,
               discontinued=False, replaced_by=None, in_stock=True)
    upsert_sku(db_session, sku_id="SKU-PP2", name="b", category="Cat-PP", list_price=20.0,
               discontinued=False, replaced_by=None, in_stock=True)
    upsert_sku(db_session, sku_id="SKU-PP3", name="c", category="Cat-PP", list_price=None,
               discontinued=False, replaced_by=None, in_stock=True)
    db_session.flush()

    assert PEER_MIN == 3
    assert predict_price_for_sku(db_session, get_sku(db_session, "SKU-PP3")) is None
