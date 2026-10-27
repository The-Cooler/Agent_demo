import json

import pytest

from app.tools.base import ToolError, ToolRegistry
from app.tools.calculator import CalculatorTool
from app.tools.read_docs import ReadDocsTool
from app.tools.registry import build_registry
from app.tools.search import SearchTool
from app.tools.todo import TodoTool
from app.tools.weather import WeatherTool


async def _run(tool, ctx, **kwargs):
    return await tool.run(ctx, tool.args_model(**kwargs))


# ----- calculator -----


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1+2*3", "7"),
        ("(1+2)*3", "9"),
        ("2**10", "1024"),
        ("10%3", "1"),
        ("-5+3", "-2"),
        ("7/2", "3.5"),
    ],
)
async def test_calculator_valid_expressions(tool_ctx, expression, expected):
    result = await _run(CalculatorTool(), tool_ctx, expression=expression)
    assert result == expected


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os')",
        "os.system('ls')",
        "abs(-1)",
        "1+",
        "x+1",
        "1;2",
        "True",
    ],
)
async def test_calculator_rejects_unsafe_or_invalid(tool_ctx, expression):
    with pytest.raises(ToolError):
        await _run(CalculatorTool(), tool_ctx, expression=expression)


async def test_calculator_rejects_empty_expression(tool_ctx):
    with pytest.raises(ToolError):
        await _run(CalculatorTool(), tool_ctx, expression="   ")


# ----- search -----


async def test_search_hit(tool_ctx):
    raw = await _run(SearchTool(), tool_ctx, query="快速排序")
    results = json.loads(raw)
    assert results
    assert results[0]["id"] == "doc-001"


async def test_search_no_hit(tool_ctx):
    raw = await _run(SearchTool(), tool_ctx, query="量子纠缠")
    assert json.loads(raw) == []


@pytest.mark.parametrize("top_k", [1, 2])
async def test_search_top_k_limits_results(tool_ctx, top_k):
    raw = await _run(SearchTool(), tool_ctx, query="。", top_k=top_k)
    assert len(json.loads(raw)) == top_k


# ----- weather -----


async def test_weather_known_city(tool_ctx):
    raw = await _run(WeatherTool(), tool_ctx, city="北京")
    data = json.loads(raw)
    assert data["city"] == "北京"
    assert data["condition"] == "晴"
    assert "date" not in data


async def test_weather_unknown_city(tool_ctx):
    raw = await _run(WeatherTool(), tool_ctx, city="火星")
    assert "未找到城市「火星」" in raw


async def test_weather_with_date(tool_ctx):
    raw = await _run(WeatherTool(), tool_ctx, city="上海", date="2026-10-27")
    data = json.loads(raw)
    assert data["city"] == "上海"
    assert data["date"] == "2026-10-27"


# ----- todo -----


async def test_todo_full_flow(tool_ctx):
    tool = TodoTool()

    added = await _run(tool, tool_ctx, action="add", content="买牛奶")
    assert "已新增待办 #1" in added

    listed = await _run(tool, tool_ctx, action="list")
    assert "买牛奶" in listed
    assert "[ ] #1" in listed

    completed = await _run(tool, tool_ctx, action="complete", todo_id=1)
    assert "已标记待办 #1 为完成" in completed

    listed_after = await _run(tool, tool_ctx, action="list")
    assert "[x] #1" in listed_after

    deleted = await _run(tool, tool_ctx, action="delete", todo_id=1)
    assert "已删除待办 #1" in deleted

    assert await _run(tool, tool_ctx, action="list") == "当前会话没有待办事项。"


@pytest.mark.parametrize(
    ("action", "kwargs"),
    [
        ("add", {}),
        ("complete", {}),
        ("delete", {}),
        ("complete", {"todo_id": 999}),
        ("delete", {"todo_id": 999}),
    ],
)
async def test_todo_missing_or_unknown_target_raises(tool_ctx, action, kwargs):
    with pytest.raises(ToolError):
        await _run(TodoTool(), tool_ctx, action=action, **kwargs)


async def test_todo_isolated_between_sessions(repo, tool_ctx):
    from app.tools.base import ToolContext

    other = repo.create_session("另一个窗口")
    other_ctx = ToolContext(session_id=other.id, repo=repo)
    tool = TodoTool()

    await _run(tool, tool_ctx, action="add", content="窗口 1 的待办")
    await _run(tool, other_ctx, action="add", content="窗口 2 的待办")

    first_list = await _run(tool, tool_ctx, action="list")
    second_list = await _run(tool, other_ctx, action="list")
    assert "窗口 1 的待办" in first_list
    assert "窗口 2 的待办" not in first_list
    assert "窗口 2 的待办" in second_list
    assert "窗口 1 的待办" not in second_list


# ----- read_docs -----


async def test_read_docs_registered_document(tool_ctx):
    content = await _run(ReadDocsTool(), tool_ctx, doc_id="doc-001.md")
    assert "快速排序" in content


@pytest.mark.parametrize("doc_id", ["../corpus.json", "not-registered.md"])
async def test_read_docs_rejects_unregistered(tool_ctx, doc_id):
    with pytest.raises(ToolError):
        await _run(ReadDocsTool(), tool_ctx, doc_id=doc_id)


# ----- registry -----


def test_registry_has_five_tools():
    registry = build_registry()
    assert set(registry.names()) == {
        "calculator",
        "search",
        "weather",
        "todo",
        "read_docs",
    }
    assert len(registry.names()) == 5


def test_registry_schemas_structure():
    schemas = build_registry().schemas()
    assert len(schemas) == 5
    by_name = {schema["name"]: schema for schema in schemas}
    calculator = by_name["calculator"]
    assert calculator["description"]
    assert calculator["parameters"]["type"] == "object"
    assert "expression" in calculator["parameters"]["properties"]


def test_registry_openai_tools_format():
    tools = build_registry().openai_tools()
    assert len(tools) == 5
    by_name = {tool["function"]["name"]: tool for tool in tools}
    calculator = by_name["calculator"]
    assert calculator["type"] == "function"
    assert calculator["function"]["description"]
    assert calculator["function"]["parameters"]["type"] == "object"
    assert "expression" in calculator["function"]["parameters"]["properties"]


def test_registry_duplicate_registration_raises():
    registry = ToolRegistry()
    registry.register(CalculatorTool())
    with pytest.raises(ValueError):
        registry.register(CalculatorTool())
