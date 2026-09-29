from functools import lru_cache

from core.config.settings import Settings


class TraceHandle:
    def __init__(self, client, span) -> None:
        self._client = client
        self._span = span

    def span(self, name: str, **metadata) -> "_SpanContext":
        return _SpanContext(self._client, name, metadata)

    def update(self, **metadata) -> None:
        if self._span is not None:
            self._span.update(**metadata)


class _SpanContext:
    def __init__(self, client, name: str, metadata: dict) -> None:
        self._client = client
        self._name = name
        self._metadata = metadata
        self._cm = None

    def __enter__(self) -> TraceHandle:
        if self._client is None:
            return TraceHandle(None, None)
        self._cm = self._client.start_as_current_observation(name=self._name, as_type="span", metadata=self._metadata)
        span = self._cm.__enter__()
        return TraceHandle(self._client, span)

    def __exit__(self, *exc) -> bool:
        if self._cm is not None:
            return bool(self._cm.__exit__(*exc))
        return False


class TracingClient:
    def __init__(self, client) -> None:
        self._client = client

    def trace(self, name: str, **metadata) -> _SpanContext:
        return _SpanContext(self._client, name, metadata)


@lru_cache
def get_tracing_client() -> TracingClient:
    settings = Settings()
    if not settings.langfuse_public_key:
        return TracingClient(None)
    from langfuse import Langfuse

    return TracingClient(Langfuse(
        public_key=settings.langfuse_public_key, secret_key=settings.langfuse_secret_key, host=settings.langfuse_host,
    ))
