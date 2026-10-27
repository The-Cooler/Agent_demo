from typing import Literal

from pydantic import BaseModel

from app.sessions.repository import Todo
from app.tools.base import ToolContext, ToolError


class TodoArgs(BaseModel):
    action: Literal["add", "list", "complete", "delete"]
    content: str | None = None
    todo_id: int | None = None


class TodoTool:
    name = "todo"
    description = "管理当前会话的待办事项：add 新增、list 列出、complete 完成、delete 删除。"
    args_model = TodoArgs

    async def run(self, ctx: ToolContext, args: BaseModel) -> str:
        if not isinstance(args, TodoArgs):
            raise ToolError("参数类型错误")
        if args.action == "add":
            return self._add(ctx, args)
        if args.action == "list":
            return self._list(ctx)
        if args.action == "complete":
            return self._complete(ctx, args)
        return self._delete(ctx, args)

    def _add(self, ctx: ToolContext, args: TodoArgs) -> str:
        if not args.content:
            raise ToolError("add 操作缺少 content 参数")
        todo = ctx.repo.add_todo(ctx.session_id, args.content)
        return f"已新增待办 #{todo.id}：{todo.content}"

    def _list(self, ctx: ToolContext) -> str:
        todos = ctx.repo.list_todos(ctx.session_id)
        if not todos:
            return "当前会话没有待办事项。"
        return "\n".join(_format(todo) for todo in todos)

    def _complete(self, ctx: ToolContext, args: TodoArgs) -> str:
        if args.todo_id is None:
            raise ToolError("complete 操作缺少 todo_id 参数")
        if not ctx.repo.complete_todo(ctx.session_id, args.todo_id):
            raise ToolError(f"待办 #{args.todo_id} 不存在或已完成")
        return f"已标记待办 #{args.todo_id} 为完成。"

    def _delete(self, ctx: ToolContext, args: TodoArgs) -> str:
        if args.todo_id is None:
            raise ToolError("delete 操作缺少 todo_id 参数")
        if not ctx.repo.delete_todo(ctx.session_id, args.todo_id):
            raise ToolError(f"待办 #{args.todo_id} 不存在")
        return f"已删除待办 #{args.todo_id}。"


def _format(todo: Todo) -> str:
    mark = "x" if todo.status == "done" else " "
    return f"[{mark}] #{todo.id} {todo.content}"
