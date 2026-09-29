from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from core.config.settings import Settings


def make_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@lru_cache
def app_session_factory() -> sessionmaker:
    settings = Settings()
    engine = make_engine(settings.database_url)
    return make_session_factory(engine)


def get_session() -> Iterator[Session]:
    session = app_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
