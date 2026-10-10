import csv
import io
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_BYTES = 10 * 1024 * 1024
MAX_MESSAGES = 50_000
TXT_HEADER = re.compile(
    r"^\[?(?P<time>\d{4}[-/]\d{1,2}[-/]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?)\]?\s+(?P<sender>[^:：]{1,120})[:：]\s*(?P<content>.*)$"
)
ALIASES = {
    "time": ("time", "timestamp", "date", "datetime", "时间", "日期"),
    "sender": ("sender", "from", "speaker", "发送者", "发言人", "昵称"),
    "content": ("content", "text", "message", "消息", "内容"),
    "conversation": ("conversation", "chat", "group", "会话", "群聊"),
}


class ImportFormatError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedMessage:
    sent_at: str
    sender: str
    content: str
    conversation: str
    source_row: int


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeError:
            continue
    raise ImportFormatError("file_encoding_unsupported")


def _time(value: object, zone: ZoneInfo) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ImportFormatError("message_time_missing")
    try:
        parsed = datetime.fromisoformat(
            value.strip().replace("/", "-").replace("Z", "+00:00")
        )
    except ValueError as error:
        raise ImportFormatError("message_time_invalid") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(timezone.utc).isoformat()


def _value(row: dict, field: str) -> object:
    for name in ALIASES[field]:
        if name in row:
            return row[name]
    return None


def _record(
    row: dict, source_row: int, zone: ZoneInfo, default_conversation: str | None
) -> ParsedMessage:
    sender = _value(row, "sender")
    content = _value(row, "content")
    conversation = _value(row, "conversation") or default_conversation
    if not isinstance(sender, str) or not sender.strip():
        raise ImportFormatError(f"message_sender_missing_at_row_{source_row}")
    if not isinstance(content, str) or not content.strip():
        raise ImportFormatError(f"message_content_missing_at_row_{source_row}")
    if not isinstance(conversation, str) or not conversation.strip():
        raise ImportFormatError("conversation_missing")
    return ParsedMessage(
        _time(_value(row, "time"), zone),
        sender.strip(),
        content.strip(),
        conversation.strip(),
        source_row,
    )


def _txt(text: str, zone: ZoneInfo, conversation: str | None) -> list[ParsedMessage]:
    if not conversation:
        raise ImportFormatError("conversation_missing")
    rows: list[ParsedMessage] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        match = TXT_HEADER.match(line)
        if match:
            rows.append(
                ParsedMessage(
                    _time(match["time"], zone),
                    match["sender"].strip(),
                    match["content"].strip(),
                    conversation,
                    line_number,
                )
            )
        elif rows:
            previous = rows[-1]
            rows[-1] = ParsedMessage(
                previous.sent_at,
                previous.sender,
                previous.content + "\n" + line.rstrip(),
                previous.conversation,
                previous.source_row,
            )
        else:
            raise ImportFormatError(f"message_header_invalid_at_row_{line_number}")
        if len(rows) > MAX_MESSAGES:
            raise ImportFormatError("message_limit_exceeded")
    return rows


def parse_chat_export(
    filename: str,
    data: bytes,
    timezone_name: str = "Asia/Shanghai",
    conversation: str | None = None,
) -> list[ParsedMessage]:
    if len(data) > MAX_BYTES:
        raise ImportFormatError("file_too_large")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".txt", ".csv", ".json"}:
        raise ImportFormatError("file_type_unsupported")
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ImportFormatError("timezone_invalid") from error
    text = _decode(data)
    if suffix == ".txt":
        rows = _txt(text, zone, conversation)
    else:
        if suffix == ".csv":
            items = list(csv.DictReader(io.StringIO(text)))
        else:
            try:
                items = json.loads(text)
            except json.JSONDecodeError as error:
                raise ImportFormatError("json_invalid") from error
            if isinstance(items, dict):
                items = items.get("messages")
        if not isinstance(items, list):
            raise ImportFormatError("message_list_invalid")
        if len(items) > MAX_MESSAGES:
            raise ImportFormatError("message_limit_exceeded")
        rows = []
        for index, item in enumerate(items, 2 if suffix == ".csv" else 1):
            if not isinstance(item, dict):
                raise ImportFormatError(f"message_invalid_at_row_{index}")
            rows.append(_record(item, index, zone, conversation))
    if not rows:
        raise ImportFormatError("no_messages")
    return rows
