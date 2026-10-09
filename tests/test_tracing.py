import builtins
from contextlib import contextmanager

from app.observability.tracing import Tracing


class SpanContext:
    trace_id = int("1234abcd", 16)
    is_valid = True


class Span:
    def __init__(self):
        self.attributes = {}

    def get_span_context(self):
        return SpanContext()

    def set_attribute(self, key, value):
        self.attributes[key] = value


class FakeTracer:
    def __init__(self):
        self.calls = []

    @contextmanager
    def start_as_current_span(self, name, attributes=None):
        self.calls.append((name, attributes))
        yield Span()


def test_disabled_tracing_is_noop():
    tracing = Tracing("")
    assert tracing.status == "disabled"
    with tracing.span("anything", secret="must-not-appear"):
        assert tracing.current_trace_id() is None


def test_initialization_failure_degrades_to_unavailable(monkeypatch):
    original_import = builtins.__import__

    def fail_otel_import(name, *args, **kwargs):
        if name.startswith("opentelemetry"):
            raise ImportError("OpenTelemetry SDK is unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_otel_import)
    tracing = Tracing("http://collector")

    assert tracing.initialize() is False
    assert tracing.status == "unavailable"
    with tracing.span("still-a-noop"):
        pass


def test_fake_tracer_records_safe_attributes_and_trace_id():
    fake = FakeTracer()
    tracing = Tracing("http://collector", tracer=fake)

    with tracing.span("agent.run", run_id="r1", password="hidden") as span:
        assert tracing.trace_id(span) == "0000000000000000000000001234abcd"

    assert fake.calls == [("agent.run", {"run_id": "r1"})]


def test_http_middleware_emits_trace_id(tmp_path):
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import create_app

    fake = FakeTracer()
    app = create_app(
        Settings(
            workspace_root=tmp_path,
            db_path="trace-api.db",
            model_provider="fake",
            tasks_enabled=False,
        )
    )
    app.state.tracing = Tracing("http://collector", tracer=fake)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.headers["x-trace-id"] == "0000000000000000000000001234abcd"
    assert fake.calls[0][0] == "http.request"
