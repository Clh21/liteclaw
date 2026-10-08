from pathlib import Path

from app.skills.loader import SkillLoader
from app.skills.selector import SkillSelector


def test_web_research_skill_is_selected():
    root = Path(__file__).resolve().parents[1] / "skills"
    skills = SkillLoader(root).load()
    selected = SkillSelector(skills).select(
        "Research and compare the latest browser tools"
    )
    assert selected
    assert selected[0].name == "web_research"
    assert "browser_open" in selected[0].required_tools
