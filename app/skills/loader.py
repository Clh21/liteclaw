from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Skill:
    name: str
    description: str
    triggers: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    instructions: str = ""


class SkillLoader:
    def __init__(self, root: Path):
        self.root = root

    def load(self) -> list[Skill]:
        skills = []
        for path in sorted(self.root.glob("*/SKILL.md")):
            raw = path.read_text(encoding="utf-8")
            if not raw.startswith("---\n"):
                continue
            parts = raw.split("---\n", 2)
            if len(parts) != 3:
                continue
            metadata = yaml.safe_load(parts[1]) or {}
            skills.append(
                Skill(
                    name=metadata.get("name", path.parent.name),
                    description=metadata.get("description", ""),
                    triggers=metadata.get("triggers", []),
                    required_tools=metadata.get("required_tools", []),
                    instructions=parts[2].strip(),
                )
            )
        return skills
