import ast
import math
import operator

from pydantic import BaseModel, Field

from app.tools.base import BaseTool, ToolContext, ToolResult


class CalculatorArgs(BaseModel):
    expression: str = Field(min_length=1, max_length=128)


OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}


def calculate(expression: str) -> int | float:
    def visit(node: ast.AST, depth: int = 0) -> int | float:
        if depth > 20:
            raise ValueError("Expression is too complex")
        if isinstance(node, ast.Expression):
            return visit(node.body, depth + 1)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = node.value
        elif isinstance(node, ast.UnaryOp) and isinstance(
            node.op, (ast.UAdd, ast.USub)
        ):
            value = visit(node.operand, depth + 1)
            value = +value if isinstance(node.op, ast.UAdd) else -value
        elif isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
            left = visit(node.left, depth + 1)
            right = visit(node.right, depth + 1)
            if isinstance(node.op, ast.Pow) and (
                abs(right) > 12 or abs(left) > 1_000_000
            ):
                raise ValueError("Exponent is too large")
            value = OPERATORS[type(node.op)](left, right)
        else:
            raise ValueError("Unsupported expression")
        if not math.isfinite(value) or abs(value) > 1_000_000_000_000:
            raise ValueError("Result is out of range")
        return value

    return visit(ast.parse(expression, mode="eval"))


class CalculatorTool(BaseTool):
    name = "calculator"
    description = "Evaluate a safe arithmetic expression"
    args_model = CalculatorArgs

    async def run(
        self, arguments: CalculatorArgs, context: ToolContext | None = None
    ) -> ToolResult:
        value = calculate(arguments.expression)
        return ToolResult(ok=True, content=str(value), data={"value": value})
