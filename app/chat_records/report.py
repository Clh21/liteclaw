from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

PERIOD_NAMES = {"week": "周报", "month": "月报", "year": "年报"}


def _safe(value: object) -> str:
    text = str(value).replace("\\", "\\\\")
    for marker in ("`", "*", "_", "[", "]", "#", "<", ">"):
        text = text.replace(marker, "\\" + marker)
    return text.replace("\r", " ").replace("\n", " ")


def _items(report: dict, items: list[dict]) -> list[str]:
    if not items:
        return ["- 无"]
    lines = []
    for item in items:
        lines.append(f"- {_safe(item['text'])}")
        for item_id in item.get("evidence_ids", []):
            evidence = report.get("evidence", {}).get(item_id)
            if evidence:
                lines.append(
                    f"> {_safe(evidence['sent_at'])} {_safe(evidence['sender'])}："
                    f"{_safe(evidence['content'])}"
                )
    return lines


def report_to_markdown(report: dict) -> str:
    zone = ZoneInfo(report.get("timezone", "Asia/Shanghai"))
    start = datetime.fromisoformat(report["period_start"]).astimezone(zone).date()
    end = datetime.fromisoformat(report["period_end"]).astimezone(
        zone
    ).date() - timedelta(days=1)
    lines = [
        f"# {PERIOD_NAMES[report['period']]}",
        "",
        f"周期：{start.isoformat()} 至 {end.isoformat()}（{zone.key}）",
        f"消息：{report['message_count']} 条",
        "参与者："
        + (
            "、".join(
                f"{_safe(name)} {count} 条"
                for name, count in report["participants"].items()
            )
            or "无"
        ),
        "",
        "## 每日活动",
        *(
            [f"- {day}：{count} 条" for day, count in report["activity_by_day"].items()]
            or ["- 无"]
        ),
        "",
        "## 本人完成事项",
        *_items(
            report, [item for item in report["completed_items"] if item["is_self"]]
        ),
        "",
        "## 待核实事项",
        *_items(report, report["open_items"]),
    ]
    for title, key in (
        ("做得好的地方", "strengths"),
        ("可改进的地方", "improvements"),
        ("对方的沟通表现", "counterpart"),
    ):
        lines.extend(
            ["", f"## {title}", *_items(report, report["communication"].get(key, []))]
        )
    lines.extend(["", "内容依据导入记录；待核实事项需对照原聊天确认。", ""])
    return "\n".join(lines)
