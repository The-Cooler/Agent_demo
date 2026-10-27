# Agent Demo

从零实现的最小可用 Agent。不使用 LangGraph / OpenHands / LangChain 等 Agent 框架，ReAct 循环、工具注册、session、context 管理、trace 全部自行实现。

## 运行方式

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。

```powershell
cd agent_demo
copy .env.example .env      # 填写 OPENAI_API_KEY
uv sync
uv run uvicorn app.main:app --port 8000
```

浏览器打开 <http://127.0.0.1:8000/> 进入对话界面，接口文档在 <http://127.0.0.1:8000/docs>。

环境变量：

| 变量 | 说明 |
|---|---|
| `OPENAI_API_KEY` | 必填 |
| `OPENAI_BASE_URL` | 默认 `https://api.deepseek.com`，可换成任意 OpenAI 兼容端点 |
| `OPENAI_MODEL` | 默认 `deepseek-flash` |

> 数据说明：`weather` 返回固定示例数据（只覆盖北京、上海、深圳、杭州），`search` 检索 `data/corpus.json` 中的本地语料，两者都不是真实外部数据源。`calculator`、`todo`、`read_docs` 为真实功能。

## 系统设计

### 分层

```
Router → SessionService → AgentRuntime → ToolRegistry / LLMClient → Repository
```

- `app/api/`：HTTP 路由，不写业务逻辑
- `app/sessions/`：会话的创建、锁、状态流转与持久化
- `app/agent/`：ReAct 循环、输出解析、上下文组装与压缩
- `app/tools/`：工具定义与注册表
- `app/llm/`：通过官方 `openai` SDK 调用 chat completions
- `app/storage/`：SQLite（stdlib `sqlite3`，WAL 模式）

### ReAct 循环

使用 chat completions 的原生 function calling。每次请求都把 `registry.openai_tools()` 作为 `tools` 参数传给模型：

- 模型返回 `tool_calls`：按顺序执行，结果以 `role="tool"` 消息追加，`tool_call_id` 对应调用 id
- 模型不返回 `tool_calls`：`message.content` 即最终回答

工具不存在、参数不是合法 JSON、参数不符合 Schema、超时、抛错都不中断循环，统一转成观测回灌继续推理。单轮最多 8 步，超过后不带工具再调用一次模型收尾。

### 工具注册

每个工具由名称、描述、Pydantic 参数模型、异步执行函数组成。Schema 由 `model_json_schema()` 自动生成，用于 `tools` 参数、`GET /api/v1/tools` 展示、执行前参数校验。

| 工具 | 参数 | 说明 |
|---|---|---|
| `calculator` | `expression` | AST 白名单求值，不使用 `eval` |
| `search` | `query`, `top_k` | 检索本地 mock 语料 |
| `weather` | `city`, `date` | 示例天气数据 |
| `todo` | `action`, `content`, `todo_id` | 当前会话的待办 |
| `read_docs` | `doc_id` | 读取 `data/docs/` 下已登记的文档 |

会话 id 由 `ToolContext` 从服务端注入，不接受模型在参数中传入。

### Session 隔离

每个会话独立保存消息历史、压缩摘要、待办、运行状态和 trace。不同会话之间互不读取，对应题目中"窗口 1"和"窗口 2"互不影响的要求。同一会话的并发请求用数据库状态 CAS 拦截，第二个请求返回 409。

### Trace

- `runs`：一次运行的状态、错误、token 用量、起止时间
- `trace_steps`：每一步的思考、动作、参数、观测、耗时、状态

`GET /api/v1/sessions/{sid}/runs/{rid}` 返回完整 trace；界面中的"执行过程"可展开查看当前这一轮的步骤。

### 数据表

```
sessions(id, title, status, summary, summary_upto, created_at, updated_at)
messages(id, session_id, seq, role, content, meta_json, created_at)
runs(id, session_id, status, error, usage_json, started_at, ended_at)
trace_steps(run_id, step_no, thought, action, args_json, observation, status, duration_ms)
todos(id, session_id, content, status, created_at, completed_at)
```

详细设计见 [docs/DESIGN.md](docs/DESIGN.md)。

## Memory 的召回时机与放置方式

| 信息 | 存放位置 | 何时进入 context |
|---|---|---|
| 用户输入、Agent 最终回答 | `messages` 表 | 每次调用 LLM 前组装，取最近的消息原文 |
| 工具调用记录 | assistant 消息的 `meta_json` | 随该条 assistant 消息一起进入，渲染为"[工具调用记录] 工具名 + 参数 + 观测" |
| Agent 思考过程 | `trace_steps` 表 | 不进入后续轮次 context，只在当前 run 的 scratchpad 内有效 |
| 过期历史 | `sessions.summary` | 压缩发生后，作为 system 消息的一部分注入 |
| 当前待办 | `todos` 表 | 每次组装 context 时取未完成待办快照，写入 system prompt |

召回时机：每次用户发消息、调用 LLM 之前组装一次上下文。压缩只在检测到超过 `context_max_chars` 的 80% 时触发，把最旧的一批消息交给 LLM 生成摘要写回 `sessions.summary`，只保留最近若干条原文；压缩失败时降级为直接丢弃旧消息，不中断对话。

## 测试

```powershell
uv run pytest -q                        # 66 passed, 6 skipped
uv run pytest -q tests/live --run-live  # 6 passed，需要 .env 中配置 key
```

实际运行输出已提交：

| 文件 | 对应命令 | 结果 |
|---|---|---|
| [resources/pytest-单元集成.txt](resources/pytest-单元集成.txt) | `uv run pytest -q` | 66 passed, 6 skipped |
| [resources/pytest-真实LLM.txt](resources/pytest-真实LLM.txt) | `uv run pytest -q tests/live --run-live` | 6 passed |

- `tests/unit`、`tests/integration` 使用 `tests/fake_llm.py` 中的测试替身，结果确定、不产生费用，覆盖非法 JSON 参数、未知工具、超时、工具报错等真实模型难以复现的分支。
- `tests/live` 调用真实 LLM，断言结构性条件（是否调用工具、步数、跨会话隔离），默认跳过。

## 索引

| 内容 | 位置 |
|---|---|
| 架构设计详细文档 | [docs/DESIGN.md](docs/DESIGN.md) |
| AI Prompt 与问题解决记录 | [docs/AI_PROMPTS.md](docs/AI_PROMPTS.md) |
| 架构设计题答案（9 题） | [docs/questions/](docs/questions/) |
| 演示视频 | [resources/演示视频.mp4](resources/演示视频.mp4) |
