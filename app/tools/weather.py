import json

from pydantic import BaseModel

from app.tools.base import ToolContext, ToolError

_WEATHER: dict[str, dict[str, object]] = {
    "北京": {"condition": "晴", "temperature": "12~24℃", "wind": "北风 3 级", "humidity": "35%"},
    "上海": {"condition": "多云", "temperature": "18~26℃", "wind": "东南风 2 级", "humidity": "68%"},
    "深圳": {"condition": "阵雨", "temperature": "24~30℃", "wind": "南风 3 级", "humidity": "82%"},
    "杭州": {"condition": "阴", "temperature": "16~23℃", "wind": "东风 2 级", "humidity": "72%"},
}


class WeatherArgs(BaseModel):
    city: str
    date: str | None = None


class WeatherTool:
    name = "weather"
    description = "查询指定城市的天气。注意：返回的是演示用固定示例数据，不是实时天气，只覆盖北京、上海、深圳、杭州。"
    args_model = WeatherArgs

    async def run(self, ctx: ToolContext, args: BaseModel) -> str:
        if not isinstance(args, WeatherArgs):
            raise ToolError("参数类型错误")
        weather = _WEATHER.get(args.city)
        if weather is None:
            return f"未找到城市「{args.city}」的天气数据（示例数据，仅覆盖：{'、'.join(_WEATHER)}）。"
        result: dict[str, object] = {"city": args.city, **weather}
        if args.date is not None:
            result["date"] = args.date
        return json.dumps(result, ensure_ascii=False)
