import pytest
from pydantic import ValidationError

from core.config.settings import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    settings = Settings(_env_file=None)
    assert settings.database_url == "postgresql+psycopg://u:p@localhost:5432/db"
    assert settings.openai_api_key == "sk-test"


def test_settings_missing_database_url_raises(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_missing_openai_key_raises(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_graph_settings_have_dev_defaults(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5433/db")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    for name in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "GRAPH_NAMESPACE"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.neo4j_uri == "bolt://localhost:17687"
    assert settings.neo4j_user == "neo4j"
    assert settings.neo4j_password == "neo4j-dev-password"
    assert settings.graph_namespace == "main"


def test_graph_settings_can_be_overridden_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5433/db")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("NEO4J_URI", "bolt://example.invalid:1")
    monkeypatch.setenv("GRAPH_NAMESPACE", "other")

    settings = Settings(_env_file=None)

    assert settings.neo4j_uri == "bolt://example.invalid:1"
    assert settings.graph_namespace == "other"
