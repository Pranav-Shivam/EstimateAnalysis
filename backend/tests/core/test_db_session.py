from sqlalchemy import inspect

from core.db.session import make_engine

TEST_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/estimate_analysis"


def test_all_six_tables_exist():
    engine = make_engine(TEST_DATABASE_URL)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {"skus", "customers", "sites", "contracts", "quote_requests", "dedupe_verdicts"} <= tables
    engine.dispose()
