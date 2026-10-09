import asyncio
import json
import os

from app.config import Settings
from app.models.fake import FakeModel
from app.models.openai_compatible import (
    ModelAuthError,
    ModelUnavailable,
    OpenAICompatibleModel,
)
from app.models.structured import parse_json_array

CALCULATOR_SCHEMA = {
    "type": "function",
    "function": {
        "name": "calculator",
        "description": "Evaluate a basic arithmetic expression.",
        "parameters": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
    },
}


def _failure_reason(error: Exception) -> str:
    if isinstance(error, ModelAuthError):
        return "authentication_failed"
    if isinstance(error, ModelUnavailable):
        return "provider_unavailable"
    return type(error).__name__


async def diagnose_model(settings: Settings, model) -> dict:
    checks = {}
    report = {
        "provider": settings.model_provider,
        "model": settings.model,
        "base_url": settings.base_url,
        "api_key_configured": bool(settings.api_key),
        "checks": checks,
        "ok": False,
    }
    if settings.model_provider != "fake" and not settings.api_key:
        checks["configuration"] = {"ok": False, "reason": "api_key_missing"}
        return report
    checks["configuration"] = {"ok": True}

    try:
        response = await model.complete(
            [{"role": "user", "content": "Reply with the single word OK."}], []
        )
        if not (response.content or "").strip():
            raise ValueError("empty_response")
        checks["chat"] = {"ok": True}
    except Exception as error:  # noqa: BLE001 - diagnostics return a safe category
        checks["chat"] = {"ok": False, "reason": _failure_reason(error)}
        return report

    try:
        response = await model.complete(
            [{"role": "user", "content": "Use calculator to calculate 2+3."}],
            [CALCULATOR_SCHEMA],
        )
        supported = any(call.name == "calculator" for call in response.tool_calls)
        checks["tool_calling"] = (
            {"ok": True}
            if supported
            else {"ok": False, "reason": "calculator_call_not_returned"}
        )
    except Exception as error:  # noqa: BLE001 - diagnostics return a safe category
        checks["tool_calling"] = {
            "ok": False,
            "reason": _failure_reason(error),
        }

    try:
        response = await model.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "Extract durable user preferences. Return a JSON array of "
                        "objects with content, kind and importance. No commentary."
                    ),
                },
                {"role": "user", "content": "I prefer dark mode."},
            ],
            [],
        )
        parsed = parse_json_array(
            response.content or "", wrapper_keys=("memories", "items")
        )
        checks["structured_json"] = (
            {"ok": True}
            if parsed and isinstance(parsed[0], dict) and parsed[0].get("content")
            else {"ok": False, "reason": "unexpected_json_value"}
        )
    except Exception as error:  # noqa: BLE001 - diagnostics return a safe category
        checks["structured_json"] = {
            "ok": False,
            "reason": _failure_reason(error),
        }

    report["ok"] = all(check["ok"] for check in checks.values())
    return report


def _configured_model(settings: Settings):
    if settings.model_provider == "fake":
        return FakeModel()
    return OpenAICompatibleModel(settings.model, settings.base_url, settings.api_key)


async def _run() -> int:
    settings = Settings(_env_file=os.getenv("LITECLAW_ENV_FILE", ".env"))
    report = await diagnose_model(settings, _configured_model(settings))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
