import os

import pytest

from core.db.session import make_engine, make_session_factory

TEST_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5433/estimate_analysis"
)


@pytest.fixture
def db_session():
    engine = make_engine(TEST_DATABASE_URL)
    connection = engine.connect()
    transaction = connection.begin()
    session_factory = make_session_factory(engine)
    session = session_factory(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()
