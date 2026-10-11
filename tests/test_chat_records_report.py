from fastapi.testclient import TestClient

from app.chat_records.report import report_to_markdown
from tests.test_chat_records_api import _user_token, app_for, upload


def test_markdown_report_includes_work_and_quoted_evidence():
    report = {
        "period": "month",
        "period_start": "2026-09-30T16:00:00+00:00",
        "period_end": "2026-10-31T16:00:00+00:00",
        "message_count": 2,
        "participants": {"我": 2},
        "activity_by_day": {"2026-10-01": 1, "2026-10-02": 1},
        "completed_items": [
            {"text": "方案已完成", "is_self": True, "evidence_ids": ["m1"]}
        ],
        "open_items": [{"text": "下周检查", "is_self": True, "evidence_ids": ["m2"]}],
        "communication": {"strengths": [], "improvements": [], "counterpart": []},
        "evidence": {
            "m1": {
                "sender": "我",
                "sent_at": "2026-10-01T00:00:00+00:00",
                "content": "方案已完成",
            },
            "m2": {
                "sender": "我",
                "sent_at": "2026-10-02T00:00:00+00:00",
                "content": "下周检查",
            },
        },
    }
    text = report_to_markdown(report)
    assert "# 月报" in text
    assert "参与者：我 2 条" in text
    assert "2026-10-01：1 条" in text
    assert "方案已完成" in text
    assert "待核实" in text
    assert "> 2026-10-01T00:00:00+00:00 我：方案已完成" in text


def test_markdown_download_is_owner_scoped(tmp_path):
    with TestClient(app_for(tmp_path, rbac=True)) as client:
        admin = {"Authorization": "Bearer admin-key"}
        _, alice = _user_token(client, admin, "report-alice")
        _, bob = _user_token(client, admin, "report-bob")
        source = upload(client, alice).json()
        body = {
            "period": "month",
            "anchor_date": "2026-10-10",
            "source_id": source["id"],
        }
        denied = client.post(
            "/v1/chat-records/reports/markdown", headers=bob, json=body
        )
        assert denied.status_code == 404
        response = client.post(
            "/v1/chat-records/reports/markdown", headers=alice, json=body
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/markdown")
        assert "我来写方案" in response.text
        assert "下周再检查报告" in response.text
