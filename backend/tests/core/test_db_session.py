from sqlalchemy import inspect

from tests.conftest import TEST_DATABASE_URL
from core.db.session import make_engine


def test_all_six_tables_exist():
    engine = make_engine(TEST_DATABASE_URL)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"skus", "customers", "sites", "contracts", "quote_requests", "dedupe_verdicts"} <= tables
    engine.dispose()
