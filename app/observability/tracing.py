from contextlib import contextmanager

SENSITIVE = ("key", "token", "password", "secret", "authorization", "cookie")


class Tracing:
    def __init__(
        self,
        endpoint: str,
        service_name: str = "liteclaw",
        headers: str = "",
        tracer=None,
    ):
        self.endpoint = endpoint
        self.service_name = service_name
        self.headers = headers
        self.tracer = tracer
        self.provider = None
        self.status = (
            "ready" if tracer is not None else ("pending" if endpoint else "disabled")
        )

    def initialize(self) -> bool:
        if not self.endpoint:
            return False
        if self.tracer is not None:
            self.status = "ready"
            return True
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            parsed_headers = {}
            for item in self.headers.split(","):
                key, separator, value = item.partition("=")
                if separator and key.strip():
                    parsed_headers[key.strip()] = value.strip()
            exporter = OTLPSpanExporter(
                endpoint=self.endpoint,
                headers=parsed_headers or None,
            )
            self.provider = TracerProvider(
                resource=Resource.create({"service.name": self.service_name})
            )
            self.provider.add_span_processor(BatchSpanProcessor(exporter))
            self.tracer = self.provider.get_tracer("liteclaw")
            self.status = "ready"
            return True
        except Exception:  # noqa: BLE001 - telemetry must not block the service
            self.provider = None
            self.tracer = None
            self.status = "unavailable"
            return False

    @contextmanager
    def span(self, name: str, **attributes):
        if self.tracer is None:
            yield None
            return
        safe = {
            key: value
            for key, value in attributes.items()
            if value is not None
            and isinstance(value, (str, bool, int, float))
            and not any(secret in key.casefold() for secret in SENSITIVE)
        }
        with self.tracer.start_as_current_span(name, attributes=safe) as span:
            yield span

    @staticmethod
    def trace_id(span) -> str | None:
        if span is None:
            return None
        context = span.get_span_context()
        if not context.is_valid:
            return None
        return f"{context.trace_id:032x}"

    def current_trace_id(self) -> str | None:
        if self.tracer is None:
            return None
        try:
            from opentelemetry import trace

            return self.trace_id(trace.get_current_span())
        except ImportError:
            return None

    def shutdown(self) -> None:
        if self.provider is not None:
            self.provider.force_flush(timeout_millis=5000)
            self.provider.shutdown()
