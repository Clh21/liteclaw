from datetime import datetime, timedelta, timezone
from enum import Enum

from pydantic import BaseModel, Field, model_validator


class ScheduleType(str, Enum):
    once = "once"
    interval = "interval"


class TaskStatus(str, Enum):
    active = "active"
    running = "running"
    paused = "paused"
    completed = "completed"
    failed = "failed"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def next_interval_time(
    planned: datetime, interval_seconds: int, now: datetime
) -> datetime:
    candidate = planned
    step = timedelta(seconds=interval_seconds)
    while candidate <= now:
        candidate += step
    return candidate


class TaskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=20_000)
    schedule_type: ScheduleType
    run_at: datetime | None = None
    interval_seconds: int | None = Field(default=None, ge=10)
    session_id: str | None = None
    max_retries: int = Field(default=2, ge=0, le=5)

    @model_validator(mode="after")
    def validate_schedule(self):
        if self.schedule_type == ScheduleType.once:
            if self.run_at is None:
                raise ValueError("run_at is required for once tasks")
            if self.interval_seconds is not None:
                raise ValueError("interval_seconds is only valid for interval tasks")
        elif self.interval_seconds is None:
            raise ValueError("interval_seconds is required for interval tasks")
        if self.run_at is not None:
            if self.run_at.tzinfo is None or self.run_at.utcoffset() is None:
                raise ValueError("run_at must include a timezone")
            self.run_at = self.run_at.astimezone(timezone.utc)
        return self
