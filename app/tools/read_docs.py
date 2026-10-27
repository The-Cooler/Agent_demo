import json
from pathlib import Path

from pydantic import BaseModel

from app.tools.base import ToolContext, ToolError

DOCS_DIR = Path(__file__).resolve().parents[2] / "data" / "docs"
INDEX_PATH = DOCS_DIR / "index.json"


class ReadDocsArgs(BaseModel):
    doc_id: str


class ReadDocsTool:
    name = "read_docs"
    description = "读取知识库文档正文，doc_id 为 index.json 中登记的文档文件名，例如 doc-001.md。"
    args_model = ReadDocsArgs

    async def run(self, ctx: ToolContext, args: BaseModel) -> str:
        if not isinstance(args, ReadDocsArgs):
            raise ToolError("参数类型错误")
        try:
            index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ToolError(f"文档索引读取失败：{exc}") from exc

        path = (DOCS_DIR / args.doc_id).resolve()
        if not path.is_relative_to(DOCS_DIR.resolve()):
            raise ToolError("文档路径非法")

        if args.doc_id not in index:
            raise ToolError(f"文档「{args.doc_id}」未登记，可用文档：{'、'.join(index)}")

        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ToolError(f"文档读取失败：{exc}") from exc
