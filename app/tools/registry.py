from app.tools.base import ToolRegistry
from app.tools.calculator import CalculatorTool
from app.tools.read_docs import ReadDocsTool
from app.tools.search import SearchTool
from app.tools.todo import TodoTool
from app.tools.weather import WeatherTool


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(CalculatorTool())
    registry.register(SearchTool())
    registry.register(WeatherTool())
    registry.register(TodoTool())
    registry.register(ReadDocsTool())
    return registry
