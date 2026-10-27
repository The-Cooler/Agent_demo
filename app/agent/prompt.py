import json


def build_system_prompt(todos: list[dict]) -> str:
    if todos:
        todo_lines = "\n".join(
            f"- #{todo['id']} [{todo['status']}] {todo['content']}" for todo in todos
        )
    else:
        todo_lines = "（当前没有待办）"

    return f"""你是智能助手，负责理解用户需求，必要时调用工具获取信息，然后给出准确、简洁的中文回答。

# 工具调用

可用工具已通过 function calling 提供。需要调用工具时直接发起工具调用，不要用文字描述调用意图。
每次回复最多调用一次工具；收到工具结果后判断是否继续调用或直接回答。

# 规则

1. 只能调用已提供的工具，不要虚构工具名或参数。
2. 参数必须符合工具定义的类型；不要传入未定义的字段。
3. 不要传入 session_id，会话身份由系统自动注入。
4. 不需要工具时直接用中文回答。

# 当前待办快照

{todo_lines}
"""
