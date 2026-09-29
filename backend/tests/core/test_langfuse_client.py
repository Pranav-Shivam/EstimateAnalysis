from core.tracing.langfuse_client import TracingClient


def test_a_none_client_makes_every_call_a_true_no_op():
    tracing = TracingClient(None)

    with tracing.trace("estimate_run", estimate_id="e-1") as trace:
        trace.update(output={"status": "ready"})
        with trace.span("tool_call", tool="lookup_customer") as child:
            child.update(output={"matches": []})

    # no exception means every call on a None-backed client was a safe no-op


class FakeObservation:
    def __init__(self, name, metadata):
        self.name = name
        self.metadata = metadata
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)


class FakeSpanContext:
    def __init__(self, client, name, metadata):
        self.client = client
        self.name = name
        self.metadata = metadata

    def __enter__(self):
        obs = FakeObservation(self.name, self.metadata)
        self.client.opened.append(obs)
        return obs

    def __exit__(self, *exc):
        return False


class FakeLangfuseClient:
    """Duck-types the one real Langfuse method TracingClient calls."""

    def __init__(self):
        self.opened = []

    def start_as_current_observation(self, *, name, as_type, metadata=None):
        return FakeSpanContext(self, name, metadata or {})


def test_a_real_client_opens_a_root_trace_and_a_nested_span():
    fake = FakeLangfuseClient()
    tracing = TracingClient(fake)

    with tracing.trace("estimate_run", estimate_id="e-1") as trace:
        with trace.span("tool_call", tool="lookup_customer") as child:
            child.update(output={"matches": []})

    assert [obs.name for obs in fake.opened] == ["estimate_run", "tool_call"]
    assert fake.opened[1].updates == [{"output": {"matches": []}}]
