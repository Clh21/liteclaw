import asyncio

import pytest

from app.tools.builtin.calculator import CalculatorTool
from app.tools.registry import ToolRegistry


def test_registry_exposes_schema_and_rejects_duplicates():
    registry = ToolRegistry()
    registry.register(CalculatorTool())
    assert registry.schemas_for_model()[0]["function"]["name"] == "calculator"
    with pytest.raises(ValueError):
        registry.register(CalculatorTool())


def test_registry_returns_observation_for_unknown_tool():
    result = asyncio.run(ToolRegistry().execute("missing", {}))
    assert result.error == "tool_not_found"
