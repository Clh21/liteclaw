from datetime import date, datetime, time, timedelta
from datetime import timezone as utc_timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel

from app.api.access import owner_scope, resolve_creation_owner
from app.chat_records.analysis import (
    add_model_observations,
    analyze_messages,
    attach_evidence,
    period_bounds,
)
from app.chat_records.parser import MAX_BYTES, ImportFormatError, parse_chat_export
from app.chat_records.report import report_to_markdown

router = APIRouter(prefix="/v1/chat-records", tags=["chat-records"])


class AnalyzeRequest(BaseModel):
    source_id: str | None = None
    conversation: str | None = None
    contact: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    start_date: date | None = None
    end_date: date | None = None
    timezone: str = "Asia/Shanghai"


class ReportRequest(BaseModel):
    period: Literal["week", "month", "year"]
    anchor_date: date
    source_id: str | None = None
    conversation: str | None = None
    timezone: str = "Asia/Shanghai"


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise HTTPException(422, detail={"code": "timezone_invalid"}) from error


def _utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise HTTPException(422, detail={"code": "timezone_required"})
    return value.astimezone(utc_timezone.utc).isoformat()


def _analysis_bounds(body: AnalyzeRequest) -> tuple[str | None, str | None]:
    zone = _zone(body.timezone)
    if (body.start_date or body.end_date) and (body.start_at or body.end_at):
        raise HTTPException(422, detail={"code": "time_filter_conflict"})
    if body.start_date and body.end_date and body.start_date > body.end_date:
        raise HTTPException(422, detail={"code": "time_range_invalid"})
    if body.start_date or body.end_date:
        try:
            start = (
                _utc(datetime.combine(body.start_date, time.min, zone))
                if body.start_date
                else None
            )
            end = (
                _utc(
                    datetime.combine(body.end_date + timedelta(days=1), time.min, zone)
                )
                if body.end_date
                else None
            )
        except OverflowError as error:
            raise HTTPException(422, detail={"code": "time_range_invalid"}) from error
    else:
        start, end = _utc(body.start_at), _utc(body.end_at)
    if start and end and start >= end:
        raise HTTPException(422, detail={"code": "time_range_invalid"})
    return start, end


async def _analysis_rows(
    request: Request,
    source_id: str | None,
    conversation: str | None,
    start_at: str | None,
    end_at: str | None,
) -> list[dict]:
    repository = request.app.state.chat_record_repository
    if (
        source_id
        and await repository.get_source(source_id, owner_scope(request)) is None
    ):
        raise HTTPException(404, detail={"code": "source_not_found"})
    return await repository.list_messages(
        owner_scope(request), source_id, conversation, start_at, end_at, limit=None
    )


@router.post("/import", status_code=201)
async def import_chat_records(
    request: Request,
    filename: str = Query(min_length=1),
    self_sender: str = Query(min_length=1),
    conversation: str | None = None,
    timezone: str = "Asia/Shanghai",
    owner_id: str | None = None,
):
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BYTES:
            raise HTTPException(413, detail={"code": "file_too_large"})
        chunks.append(chunk)
    data = b"".join(chunks)
    try:
        rows = parse_chat_export(filename, data, timezone, conversation)
    except ImportFormatError as error:
        raise HTTPException(422, detail={"code": str(error)}) from error
    assigned_owner = await resolve_creation_owner(request, owner_id)
    return await request.app.state.chat_record_repository.import_messages(
        filename,
        data,
        rows,
        assigned_owner,
        self_sender.strip(),
        timezone,
        conversation,
    )


@router.get("/sources")
async def list_chat_sources(request: Request):
    return {
        "sources": await request.app.state.chat_record_repository.list_sources(
            owner_scope(request)
        )
    }


@router.get("/messages")
async def list_chat_messages(
    request: Request,
    source_id: str | None = None,
    conversation: str | None = None,
    start_at: str | None = None,
    end_at: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    repository = request.app.state.chat_record_repository
    if (
        source_id
        and await repository.get_source(source_id, owner_scope(request)) is None
    ):
        raise HTTPException(404, detail={"code": "source_not_found"})
    return {
        "messages": await repository.list_messages(
            owner_scope(request),
            source_id,
            conversation,
            start_at,
            end_at,
            limit,
            offset,
        )
    }


@router.delete("/sources/{source_id}")
async def delete_chat_source(source_id: str, request: Request):
    if not await request.app.state.chat_record_repository.delete_source(
        source_id, owner_scope(request)
    ):
        raise HTTPException(404, detail={"code": "source_not_found"})
    return {"deleted": True}


@router.post("/analyze")
async def analyze_chat_records(body: AnalyzeRequest, request: Request):
    start_at, end_at = _analysis_bounds(body)
    rows = await _analysis_rows(
        request, body.source_id, body.conversation, start_at, end_at
    )
    if body.contact:
        rows = [
            row for row in rows if row["sender"] in {row["self_sender"], body.contact}
        ]
    result = analyze_messages(rows, body.timezone)
    result = await add_model_observations(
        result, rows, request.app.state.chat_record_model
    )
    return attach_evidence(result, rows)


async def _build_report(body: ReportRequest, request: Request) -> dict:
    try:
        start_at, end_at = period_bounds(body.period, body.anchor_date, body.timezone)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise HTTPException(422, detail={"code": "timezone_invalid"}) from error
    rows = await _analysis_rows(
        request, body.source_id, body.conversation, start_at, end_at
    )
    result = analyze_messages(rows, body.timezone)
    result = await add_model_observations(
        result, rows, request.app.state.chat_record_model
    )
    result = attach_evidence(result, rows)
    result.update(
        {
            "period": body.period,
            "timezone": body.timezone,
            "period_start": start_at,
            "period_end": end_at,
            "summary": (
                f"本周期共 {result['message_count']} 条消息，"
                f"确认完成 {len([item for item in result['completed_items'] if item['is_self']])} 项，"
                f"待核实 {len(result['open_items'])} 项。"
            ),
        }
    )
    return result


@router.post("/reports")
async def create_chat_report(body: ReportRequest, request: Request):
    return await _build_report(body, request)


@router.post("/reports/markdown")
async def download_chat_report(body: ReportRequest, request: Request):
    report = await _build_report(body, request)
    return Response(
        report_to_markdown(report),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="liteclaw-report.md"'},
    )
