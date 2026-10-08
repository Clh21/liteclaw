from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.tasks.models import TaskCreate, next_interval_time


def test_once_task_requires_timezone_aware_run_at():
    with pytest.raises(ValidationError):
        TaskCreate(name="report", prompt="Write report", schedule_type="once")
    with pytest.raises(ValidationError):
        TaskCreate(
            name="report",
            prompt="Write report",
            schedule_type="once",
            run_at=datetime(2026, 10, 8, 12, 0),
        )


def test_interval_task_requires_minimum_interval_and_rejects_run_at_only_fields():
    with pytest.raises(ValidationError):
        TaskCreate(
            name="poll",
            prompt="Check status",
            schedule_type="interval",
            interval_seconds=9,
        )
    task = TaskCreate(
        name="poll",
        prompt="Check status",
        schedule_type="interval",
        interval_seconds=60,
    )
    assert task.interval_seconds == 60


def test_interval_advances_to_first_future_time_without_backlog():
    planned = datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc)
    now = planned + timedelta(seconds=185)
    assert next_interval_time(planned, 60, now) == planned + timedelta(seconds=240)
