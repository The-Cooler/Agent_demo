import json
from pathlib import Path

from pydantic import BaseModel

from app.tools.base import ToolContext, ToolError

CORPUS_PATH = Path(__file__).resolve().parents[2] / "data" / "corpus.json"
SNIPPET_CHARS = 80


class SearchArgs(BaseModel):
    query: str
    top_k: int = 5


class SearchTool:
    name = "search"
    description = "在本地知识库中按关键词检索文档，返回匹配文档的 id、标题与内容片段。"
    args_model = SearchArgs

    async def run(self, ctx: ToolContext, args: BaseModel) -> str:
        if not isinstance(args, SearchArgs):
            raise ToolError("参数类型错误")
        try:
            documents = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ToolError(f"语料读取失败：{exc}") from exc

        chars = sorted({ch for ch in args.query if not ch.isspace()})
        scored: list[tuple[int, dict]] = []
        for document in documents:
            title = document.get("title", "")
            content = document.get("content", "")
            score = 0
            for ch in chars:
                if ch in title:
                    score += 2
                if ch in content:
                    score += 1
            if score > 0:
                scored.append((score, document))

        scored.sort(key=lambda item: item[0], reverse=True)
        results = [
            {
                "id": document["id"],
                "title": document["title"],
                "片段": document["content"][:SNIPPET_CHARS],
            }
            for _, document in scored[: args.top_k]
        ]
        return json.dumps(results, ensure_ascii=False)
