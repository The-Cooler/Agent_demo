import ast
import operator
from typing import Any, Callable

from pydantic import BaseModel

from app.tools.base import ToolContext, ToolError

_BIN_OPS: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}

_UNARY_OPS: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class ExpressionArgs(BaseModel):
    expression: str


class CalculatorTool:
    name = "calculator"
    description = "计算数学表达式，支持 + - * / % ** 与括号，参数 expression 为表达式字符串。"
    args_model = ExpressionArgs

    async def run(self, ctx: ToolContext, args: BaseModel) -> str:
        if not isinstance(args, ExpressionArgs):
            raise ToolError("参数类型错误")
        return str(_evaluate(args.expression))


def _evaluate(expression: str) -> Any:
    if not expression.strip():
        raise ToolError("表达式不能为空")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ToolError(f"表达式解析失败：{exc.msg}") from exc
    return _eval_node(tree.body)


def _eval_node(node: ast.AST) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ToolError("只支持数字常量")
        return node.value
    if isinstance(node, ast.BinOp):
        handler = _BIN_OPS.get(type(node.op))
        if handler is None:
            raise ToolError(f"不支持的运算符：{type(node.op).__name__}")
        return handler(_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp):
        unary_handler = _UNARY_OPS.get(type(node.op))
        if unary_handler is None:
            raise ToolError(f"不支持的一元运算符：{type(node.op).__name__}")
        return unary_handler(_eval_node(node.operand))
    raise ToolError(f"不支持的语法节点：{type(node).__name__}")
