from sqlalchemy import inspect

from tests.conftest import TEST_DATABASE_URL
from core.db.session import make_engine


def test_all_six_tables_exist():
    engine = make_engine(TEST_DATABASE_URL)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"skus", "customers", "sites", "contracts", "quote_requests", "dedupe_verdicts"} <= tables
    engine.dispose()


def test_lookup_columns_are_indexed():
    engine = make_engine(TEST_DATABASE_URL)
    inspector = inspect(engine)
    drafts = {ix["name"]: ix["column_names"] for ix in inspector.get_indexes("estimate_drafts")}
    history = {ix["name"]: ix["column_names"] for ix in inspector.get_indexes("price_history")}
    assert drafts["ix_estimate_drafts_quote_request_id"] == ["quote_request_id"]
    assert history["ix_price_history_sku_id"] == ["sku_id"]
    engine.dispose()
