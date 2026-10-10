from datetime import date
from types import SimpleNamespace

import pytest

from app.chat_records.analysis import (
    add_model_observations,
    analyze_messages,
    period_bounds,
)


def message(message_id, day, sender, content):
    return {
        "id": message_id,
        "sent_at": f"2026-10-{day:02d}T01:00:00+00:00",
        "sender": sender,
        "content": content,
        "conversation": "项目群",
        "self_sender": "我",
    }


def test_analysis_tracks_open_and_completed_items_with_evidence():
    rows = [
        message("m1", 1, "我", "我来写方案"),
        message("m2", 2, "我", "方案已完成"),
        message("m3", 3, "小王", "下周再检查报告"),
    ]
    result = analyze_messages(rows)
    assert result["message_count"] == 3
    assert result["participants"] == {"我": 2, "小王": 1}
    assert result["completed_items"][0]["evidence_ids"] == ["m1", "m2"]
    assert result["open_items"][0]["evidence_ids"] == ["m3"]
    assert result["open_items"][0]["status"] == "needs_confirmation"
    assert result["activity_by_day"] == {
        "2026-10-01": 1,
        "2026-10-02": 1,
        "2026-10-03": 1,
    }


def test_period_bounds_use_local_calendar_week_month_year():
    week = period_bounds("week", date(2026, 10, 9), "Asia/Shanghai")
    month = period_bounds("month", date(2026, 10, 9), "Asia/Shanghai")
    year = period_bounds("year", date(2026, 10, 9), "Asia/Shanghai")
    assert week[0] == "2026-10-04T16:00:00+00:00"
    assert week[1] == "2026-10-11T16:00:00+00:00"
    assert month[0] == "2026-09-30T16:00:00+00:00"
    assert month[1] == "2026-10-31T16:00:00+00:00"
    assert year[0] == "2025-12-31T16:00:00+00:00"
    assert year[1] == "2026-12-31T16:00:00+00:00"


@pytest.mark.asyncio
async def test_model_observations_reject_unknown_evidence_ids():
    class Model:
        async def complete(self, messages, tools):
            return SimpleNamespace(
                content='{"strengths":[{"text":"清楚提出任务","evidence_ids":["m1"]},{"text":"虚构","evidence_ids":["missing"]}],"improvements":[],"counterpart":[]}'
            )

    rows = [message("m1", 1, "我", "我来写方案")]
    result = await add_model_observations(analyze_messages(rows), rows, Model())
    assert result["communication"]["strengths"] == [
        {"text": "清楚提出任务", "evidence_ids": ["m1"]}
    ]
