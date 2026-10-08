from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any


class RunEventEmitter:
    def __init__(self, sink: Callable[[dict[str, Any]], None]):
        self.sink = sink
        self.sequence = 0

    def emit(self, event_type: str, **data: Any) -> dict[str, Any]:
        self.sequence += 1
        event = {
            "seq": self.sequence,
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **data,
        }
        self.sink(event)
        return event
