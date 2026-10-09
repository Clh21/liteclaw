import json

from app.logging import log_event
from app.memory.repository import Database
from app.models.base import BaseChatModel
from app.models.structured import parse_json_object

SUMMARY_KEYS = (
    "user_goals",
    "decisions",
    "important_facts",
    "artifacts",
    "open_items",
)


class SessionSummarizer:
    def __init__(
        self,
        database: Database,
        threshold: int = 12,
        model: BaseChatModel | None = None,
    ):
        self.database = database
        self.threshold = threshold
        self.model = model

    async def maybe_summarize(self, session_id: str) -> str | None:
        messages = await self.database.get_messages(session_id)
        session = await self.database.get_session(session_id)
        if session is None:
            raise KeyError("session_not_found")
        new = messages[session["summarized_message_count"] :]
        if (
            len(new) < self.threshold
            and sum(item["token_count"] for item in new) < 6000
        ):
            return None
        previous = self._parse_previous(session["summary"])
        extracted = {
            "user_goals": [
                item["content"][:200]
                for item in new
                if item["role"] == "user" and item["content"]
            ]
        }
        if self.model is not None:
            try:
                response = await self.model.complete(
                    [
                        {
                            "role": "system",
                            "content": (
                                "Summarize durable conversation state as one strict JSON object "
                                "with arrays user_goals, decisions, important_facts, "
                                "artifacts, open_items. Preserve factual details, files, "
                                "parameters and unfinished work. Ignore long raw tool output. "
                                "Use only information supported by the conversation."
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "previous": previous,
                                    "new_messages": [
                                        {
                                            "role": item["role"],
                                            "content": (item["content"] or "")[:500],
                                        }
                                        for item in new[-24:]
                                    ],
                                },
                                ensure_ascii=False,
                            ),
                        },
                    ],
                    [],
                )
                raw = parse_json_object(
                    response.content or "", wrapper_keys=("summary",)
                )
                if any(not isinstance(raw.get(key), list) for key in SUMMARY_KEYS):
                    raise TypeError("Summary must contain five arrays")
                extracted = raw
            except Exception as error:  # noqa: BLE001 - summary has a deterministic fallback
                log_event("summary.model_unavailable", error=type(error).__name__)
        structure = {}
        for key in SUMMARY_KEYS:
            prior = previous.get(key, [])
            fresh = extracted.get(key, [])
            if not isinstance(prior, list) or not isinstance(fresh, list):
                raise TypeError("Summary fields must be arrays")
            items = [item[:100] for item in prior + fresh if isinstance(item, str)]
            structure[key] = list(dict.fromkeys(items))[-4:]
        summary = json.dumps(structure, ensure_ascii=False)
        await self.database.update_summary(session_id, summary)
        return summary

    @staticmethod
    def _parse_previous(text: str | None) -> dict:
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return {"important_facts": [text[:100]]}
        return parsed if isinstance(parsed, dict) else {}
