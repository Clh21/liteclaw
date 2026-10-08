import re

from app.skills.loader import Skill


class SkillSelector:
    def __init__(self, skills: list[Skill], available_tools: set[str] | None = None):
        self.skills = skills
        self.available_tools = available_tools

    def select(self, query: str, top_k: int = 3) -> list[Skill]:
        lowered = query.casefold()
        words = set(re.findall(r"\w+", lowered))
        ranked = []
        for skill in self.skills:
            if self.available_tools is not None and not set(
                skill.required_tools
            ).issubset(self.available_tools):
                continue
            trigger_score = sum(
                3 for trigger in skill.triggers if trigger.casefold() in lowered
            )
            description_score = len(
                words & set(re.findall(r"\w+", skill.description.casefold()))
            )
            score = trigger_score + description_score
            if score:
                ranked.append((score, skill))
        return [
            skill
            for _, skill in sorted(ranked, key=lambda item: (-item[0], item[1].name))[
                :top_k
            ]
        ]
