from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    openai_api_key: str
    anthropic_api_key: str
    # Dev defaults match docker-compose.yml. Host port 17687 avoids the Neo4j default and local collisions.
    neo4j_uri: str = "bolt://localhost:17687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j-dev-password"
    # Every graph node carries its namespace, so tests share one Neo4j without touching the real graph.
    graph_namespace: str = "main"
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None
    # The Vite dev server's origin. The API has no auth, so CORS is the only browser-side gate.
    cors_allowed_origins: list[str] = ["http://localhost:7050"]
