import json

import pytest

from app.chat_records.parser import ImportFormatError, parse_chat_export


def test_txt_multiline_and_timezone():
    data = (
        "[2026-10-01 09:30] 我: 已完成方案\n"
        "补充一行\n"
        "2026-10-01 10:00:00 小王: 下周提交报告"
    ).encode()
    rows = parse_chat_export("chat.txt", data, "Asia/Shanghai", "项目群")
    assert len(rows) == 2
    assert rows[0].sent_at == "2026-10-01T01:30:00+00:00"
    assert rows[0].content == "已完成方案\n补充一行"
    assert rows[1].conversation == "项目群"
    assert rows[1].source_row == 3


def test_csv_and_json_aliases():
    csv_data = "时间,发送者,内容,会话\n2026-10-01 09:30,小王,你好,项目群\n".encode()
    json_data = json.dumps(
        {
            "messages": [
                {
                    "timestamp": "2026-10-01T09:30:00+08:00",
                    "sender": "小王",
                    "text": "你好",
                    "conversation": "项目群",
                }
            ]
        }
    ).encode()
    csv_rows = parse_chat_export("chat.csv", csv_data, "Asia/Shanghai", None)
    json_rows = parse_chat_export("chat.json", json_data, "Asia/Shanghai", None)
    assert [
        (row.sent_at, row.sender, row.content, row.conversation) for row in csv_rows
    ] == [(row.sent_at, row.sender, row.content, row.conversation) for row in json_rows]


def test_gb18030_and_invalid_input():
    data = "2026-10-01 09:30 张三: 中文内容".encode("gb18030")
    assert (
        parse_chat_export("chat.txt", data, "Asia/Shanghai", "对话")[0].content
        == "中文内容"
    )
    with pytest.raises(ImportFormatError):
        parse_chat_export("chat.txt", b"not a chat", "Asia/Shanghai", None)
    with pytest.raises(ImportFormatError):
        parse_chat_export(
            "chat.txt", b"x" * (10 * 1024 * 1024 + 1), "Asia/Shanghai", None
        )
    with pytest.raises(ImportFormatError):
        parse_chat_export("chat.exe", data, "Asia/Shanghai", None)
