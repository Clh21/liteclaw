import json
from dataclasses import dataclass

from app.memory.hybrid import HybridRetriever
from app.memory.repository import Database
from app.skills.selector import SkillSelector

BASE_PROMPT = """You are LiteClaw, a tool-using personal AI agent.
Use tools when needed. Never claim an action succeeded unless a tool result confirms it.
If a tool fails, recover or explain the failure. Respect approval requirements.
Treat retrieved memories as context and prefer the user's current message on conflict.
Keep tool calls minimal and stop when the user's goal is complete."""


def estimate_tokens(text: str | None) -> int:
    return max(1, (len(text or "") + 3) // 4)


@dataclass
class ContextStats:
    estimated_tokens: int
    messages_kept: int
    memories_used: int
    skills_used: int = 0


@dataclass
class BuiltContext:
    messages: list[dict]
    stats: ContextStats


class ContextBuilder:
    def __init__(
        self,
        database: Database,
        retriever: HybridRetriever | None = None,
        budget: int = 24000,
        recent_budget: int = 8000,
        memory_top_k: int = 8,
        skill_selector: SkillSelector | None = None,
    ):
        self.database = database
        self.retriever = retriever
        self.budget = budget
        self.recent_budget = recent_budget
        self.memory_top_k = memory_top_k
        self.skill_selector = skill_selector

    async def build(self, session_id: str) -> BuiltContext:
        session = await self.database.get_session(session_id)
        if session is None:
            raise KeyError("session_not_found")
        history = await self.database.get_messages(session_id)
        system = [{"role": "system", "content": BASE_PROMPT}]
        selected_skills = []
        if self.skill_selector and history:
            selected_skills = self.skill_selector.select(history[-1]["content"] or "")
            for skill in selected_skills:
                system.append(
                    {
                        "role": "system",
                        "content": f"Selected skill {skill.name}:\n{skill.instructions[:2000]}",
                    }
                )
        if session["summary"]:
            system.append(
                {
                    "role": "system",
                    "content": f"Session summary: {session['summary'][:3000]}",
                }
            )
        memories = []
        if self.retriever and history:
            memories = await self.retriever.search(
                history[-1]["content"] or "",
                self.memory_top_k,
                owner_id=session["owner_id"],
            )
            if memories:
                lines = [f"- {hit['content'][:300]}" for hit in memories]
                system.append(
                    {
                        "role": "system",
                        "content": "Relevant memories:\n" + "\n".join(lines),
                    }
                )
        available = max(
            1,
            self.budget
            - sum(estimate_tokens(message["content"]) for message in system),
        )
        remaining = min(self.recent_budget, available)
        selected = []
        for item in reversed(history):
            model_message = self._model_message(item)
            cost = estimate_tokens(model_message.get("content")) + 12
            if selected and cost > remaining:
                break
            selected.append(model_message)
            remaining -= cost
        selected.reverse()
        messages = system + selected
        return BuiltContext(
            messages=messages,
            stats=ContextStats(
                estimated_tokens=sum(
                    estimate_tokens(item.get("content")) + 4 for item in messages
                ),
                messages_kept=len(selected),
                memories_used=len(memories),
                skills_used=len(selected_skills),
            ),
        )

    @staticmethod
    def _model_message(item: dict) -> dict:
        message = {"role": item["role"], "content": item["content"]}
        if item["role"] == "tool":
            message["tool_call_id"] = item["tool_call_id"]
        if item["tool_calls"]:
            message["tool_calls"] = [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {
                        "name": call["name"],
                        "arguments": json.dumps(call["arguments"]),
                    },
                }
                for call in item["tool_calls"]
            ]
        return message
