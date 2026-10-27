# Agent Demo 架构设计

> 对应题目：从零实现一个最小可用 Agent。
> 约束：不使用 LangGraph / OpenHands / LangChain 等 Agent 框架；FastAPI 作为 Web 层，Pydantic 用于数据模型与校验，LLM 调用使用官方 `openai` SDK；ReAct 循环、工具注册、session、memory、trace 自行实现。
> search、weather 使用本地 mock 数据；9 道架构设计题不在本代码交付范围内。

---

## 1. 边界与选型

| 层 | 选型 | 职责 |
|---|---|---|
| Web | FastAPI | HTTP 路由、依赖注入、异常映射 |
| 数据校验 | Pydantic v2 | 工具参数 Schema、LLM 输出模型、请求/响应模型 |
| LLM 调用 | `openai` SDK | 调用 chat completions 接口 |
| Agent 运行时 | 自研 | ReAct 循环、解析、上下文组装、压缩 |
| 存储 | SQLite（stdlib `sqlite3`，WAL） | 会话、消息、运行记录、trace、待办 |

---

## 2. 项目结构

```
agent_demo/
├── app/
│   ├── main.py                    # FastAPI 实例、异常处理器、路由挂载、/ui 静态页面
│   ├── config.py                  # pydantic-settings 读取 .env
│   ├── deps.py                    # 依赖注入：仓储、runtime
│   ├── static/
│   │   └── index.html             # 对话界面
│   ├── api/
│   │   ├── sessions.py            # 会话 CRUD
│   │   ├── chat.py                # 发送消息、获取历史、获取 trace
│   │   └── tools.py               # 工具列表与 Schema
│   ├── agent/
│   │   ├── runtime.py             # ReAct 主循环
│   │   ├── prompt.py              # system prompt / 工具与待办说明
│   │   ├── context.py             # 上下文组装 + 压缩
│   │   └── models.py              # TraceStep / RunResult
│   ├── llm/
│   │   ├── base.py                # LLMClient 接口
│   │   └── openai_client.py       # 使用官方 openai SDK 实现
│   ├── tools/
│   │   ├── base.py                # Tool 协议、ToolRegistry、ToolContext
│   │   ├── calculator.py
│   │   ├── search.py              # mock 语料
│   │   ├── weather.py             # mock 天气
│   │   ├── todo.py                # 会话级待办
│   │   └── read_docs.py
│   ├── sessions/
│   │   ├── service.py             # 会话锁、状态流转
│   │   └── repository.py
│   └── storage/
│       ├── db.py                  # SQLite 连接
│       └── schema.sql
├── data/
│   ├── docs/                      # read_docs 的文档
│   ├── corpus.json                # search 的 mock 语料
│   └── agent.db                   # SQLite 数据库（运行时生成）
├── tests/
│   ├── conftest.py
│   ├── fake_llm.py                # 仅测试用：模拟 LLM 响应的测试替身，不进入运行路径
│   ├── unit/                      # tools / context / runtime
│   ├── integration/               # API、多 session 隔离
│   └── live/                      # 真实 LLM 测试，默认跳过，--run-live 开启
├── docs/
│   └── DESIGN.md
├── .env.example
├── pyproject.toml
└── README.md
```

调用链固定为：`Router → SessionService → AgentRuntime → ToolRegistry / LLMClient → Repository`。Router 不写业务逻辑，工具不直接碰 HTTP。

---

## 3. ReAct 核心设计

### 3.1 输出协议

使用 chat completions 的原生 function calling：`AgentRuntime` 每次请求都带上 `registry.openai_tools()`，模型通过 `tool_calls` 发起调用，不需要自定义文本协议。

- 模型返回 `tool_calls`：按顺序执行每个调用，结果以 `role="tool"` 消息追加，`tool_call_id` 对应调用 id。
- 模型不返回 `tool_calls`：`message.content` 即最终回答。

### 3.2 工具调用校验

`runtime.py` 的 `_execute_tool` 负责校验，不直接抛给用户，而是生成一条观测：

| 情况 | trace_status | 观测内容 |
|---|---|---|
| 工具名不存在 | `unknown_tool` | 工具不存在，附带可用工具列表 |
| `arguments` 不是合法 JSON 对象 | `invalid_args` | 原始参数文本 |
| 参数不符合工具的 Pydantic 模型 | `invalid_args` | 校验错误详情 |
| 执行超时 | `timeout` | 超时秒数 |
| 工具抛 `ToolError` 或其他异常 | `error` | 异常信息 |

失败不会中断循环，观测作为 `role="tool"` 消息回灌，模型继续决策。思考内容写入 trace，但不进入后续轮次的上下文。

### 3.3 主循环

```
run(session_id, user_input):
    CAS 抢占 session 状态 idle -> running，失败返回 409
    try:
        保存 user message
        构建 context
        tools = registry.openai_tools()
        scratchpad = []
        for step in 1..MAX_REACT_STEPS(默认 8):
            result = llm.complete(context + scratchpad, tools=tools)
            if 没有 tool_calls: 保存 assistant message，返回
            scratchpad += [assistant 消息（含 tool_calls）]
            for call in result.tool_calls:
                observation = await execute_with_timeout(tool, call.arguments)
                scratchpad += [{"role": "tool", "tool_call_id": call.id, "content": observation}]
        超步数：额外调用一次 LLM（不带 tools），取其 content 作为回答，标记 max_steps
    finally:
        session 状态 running -> idle
```

关键限制：

- `MAX_REACT_STEPS`：单轮对话的工具循环上限；
- `TOOL_TIMEOUT`：单次工具超时；
- 上下文字符预算：控制会话历史长度。

---

## 4. 工具注册机制

`Tool` 由四部分组成：名称、描述、Pydantic 参数模型、异步执行函数。注册表启动时一次性注册，Schema 由 `model_json_schema()` 自动生成，同时用于：

- 转成 `tools` 参数传给 chat completions（`ToolRegistry.openai_tools()`）；
- `GET /api/v1/tools` 展示；
- 执行前用该工具的 `args_model` 校验参数。

| 工具 | 参数 | 行为 |
|---|---|---|
| `calculator` | `expression: str` | AST 白名单求值，禁止 `eval` |
| `search` | `query: str, top_k: int = 5` | 查本地 mock 语料 |
| `weather` | `city: str, date: str \| None` | 本地 mock 数据 |
| `todo` | `action: add/list/complete/delete` + 对应字段 | 会话级待办，落 SQLite |
| `read_docs` | `doc_id: str` | 只读 `data/docs` 下登记过的文档 |

`ToolContext` 携带 `session_id` 和仓储依赖。**会话 id 只能来自服务端上下文，绝不接受模型在参数里传入**，否则模型可以读写别的会话的待办。

todo 用会话级而不是用户级：窗口 1 和窗口 2 各记各的待办，直接对应题目里的隔离要求。

---

## 5. Session 模型

每个会话独立保存：消息历史、滚动摘要、待办、运行状态、trace。

- 不同会话的上下文、待办、摘要互不读取，窗口 1 和窗口 2 可以并行存在；
- 调用时通过 `session_id` 续聊，进程重启后从 SQLite 恢复；
- 同一会话并发请求用数据库状态 CAS（`try_start_run`）拦截，第二个请求返回 409，避免两条 run 同时写历史。

---

## 6. Context / Memory 设计

| 信息 | 存放位置 | 是否进入下一轮 context | 说明 |
|---|---|---|---|
| 用户输入 | messages 表 | 是 | 最近消息原文 |
| Agent 最终回答 | messages 表 | 是 | 最近消息原文 |
| 工具调用记录 | assistant message 的 meta | 是，摘要形式 | 工具名 + 参数 + 结果前 N 字，供“带工具的追问” |
| Agent 思考过程 | trace_steps 表 | 否 | 只在当前 run 的 scratchpad 内有效，减少 token 和漂移 |
| 过期历史 | sessions.summary | 是 | 超预算时由 LLM 压缩 |
| 当前待办 | todos 表 | 是，快照 | 每轮以简短列表注入 system，支持“把刚才那条完成” |

**召回时机**：每次用户发消息、调用 LLM 之前组装一次上下文；压缩只在组装时检测到超预算才触发。

**上下文结构**：

```
[system]  角色 + 工具使用说明 + 当前待办快照 + 会话摘要
[history] 最近 N 条 user / assistant 消息（工具记录作为 assistant 的附加信息渲染）
[user]    当前输入
[assistant/user] 当前 run 的 scratchpad（在循环内追加）
```

**压缩逻辑**：

1. 按字符数估算（中文按 1 字符 ≈ 0.7 token 保守计），超过 `CONTEXT_MAX_CHARS` 的 80% 触发；
2. 取最旧的一批完整轮次交给 LLM 生成 ≤1500 字摘要，要求保留：用户偏好、已确认事实、未完成待办、上一轮结论；
3. 写回 `sessions.summary` 和 `summary_upto`，之后只保留最近 6~8 条消息原文；
4. 压缩调用失败时记录日志并退化为丢弃最旧消息，保证对话不中断；该路径单独测试。

这样两种追问都能工作：纯对话追问靠最近消息和摘要；带工具的追问靠持久化的工具记录摘要和待办快照。

---

## 7. 数据表

SQLite，WAL 模式，不引 ORM。

```
sessions(id, title, status, summary, summary_upto, created_at, updated_at)
messages(id, session_id, seq, role, content, meta_json, created_at)
runs(id, session_id, status, error, usage_json, started_at, ended_at)
trace_steps(run_id, step_no, thought, action, args_json, observation, status, duration_ms)
todos(id, session_id, content, status, created_at, completed_at)
```

---

## 8. HTTP 接口

```
GET    /                            # 重定向到 /ui/
GET    /ui/                         # 对话界面
GET    /health
GET    /api/v1/tools
POST   /api/v1/sessions
GET    /api/v1/sessions
GET    /api/v1/sessions/{sid}
DELETE /api/v1/sessions/{sid}
POST   /api/v1/sessions/{sid}/messages     # 同步执行一次 Agent run
GET    /api/v1/sessions/{sid}/messages
GET    /api/v1/sessions/{sid}/runs/{rid}   # 完整 trace
```

`POST messages` 返回：最终回答、run 状态、逐步 trace（thought / action / observation / 耗时）、token usage。

同步接口先做最小可用；流式 SSE 不在题目硬要求内，暂不实现。

异常映射：404 资源不存在、409 会话正在运行、422 参数错误、502 LLM 上游失败。工具自身异常不升为 HTTP 错误，转成 Observation 让 Agent 自行处理。

---

## 9. Trace 与日志

trace 分两层：

- `runs`：一次运行的状态、错误、token usage、起止时间；
- `trace_steps`：每一步的思考、动作、参数、观测、耗时、状态。

同时用 stdlib `logging` 输出带 `run_id / session_id / step_no` 的结构化日志。

---

## 10. 测试计划

测试中出现的 `FakeLLM` 是**测试替身（test double）**，只存在于 `tests/` 下，用于在单元测试里替换 `LLMClient` 接口、按预设脚本返回响应。生产代码运行时不加载它，Agent 实际调用的是 `llm/openai_client.py` 里的真实 LLM API。

两者分工：

- `FakeLLM`：测错误分支和确定性逻辑（非法 JSON、未知工具、max steps、超时），这些路径真实模型无法稳定复现；
- 真实 LLM：测 Agent 的核心决策能力（是否调工具、多步循环、追问、跨 session 隔离），断言结构性条件而非精确字符串。

| 要求 | 测试 | 用哪个 LLM |
|---|---|---|
| 直接回复 / 调工具 / 多步工具 | 测 runtime 状态与输出 | FakeLLM + 真实 LLM |
| 输出解析 | 合法 JSON、代码块包裹、前后噪声、缺字段、未知工具、非法参数 | FakeLLM |
| 工具注册与 Schema | 名称唯一、Schema 可生成、参数校验生效 | 不涉及 LLM |
| 三个以上工具 | calculator 安全求值、search / weather mock、todo 增删查、read_docs 路径限制 | 不涉及 LLM |
| 多 session 隔离 | 同一进程两个会话：历史、待办、摘要互不影响 | FakeLLM + 真实 LLM |
| 跨轮记忆与追问 | 第二轮纯对话追问；第二轮引用上一轮工具结果再调工具 | FakeLLM + 真实 LLM |
| 最大轮次 | 超过 `MAX_REACT_STEPS` 后的强制收尾与状态标记 | FakeLLM |
| 上下文压缩 | 超预算触发摘要、原文保留窗口、摘要失败降级 | FakeLLM |
| 异常处理 | LLM 超时 / 5xx、工具超时、工具抛错、格式连续失败 | FakeLLM + 假 API key |
| trace | 每一步落表、接口可查 | 不涉及 LLM |
| 真实 LLM 冒烟 | 单步计算、多步工具、纯对话追问、带工具追问、跨 session 隔离 | 真实 LLM（`@pytest.mark.live`，默认跳过，配置 API key 后运行） |

---

## 11. 待确认事项

1. **真实 LLM 提供方**：当前按 `openai` SDK 的 chat completions 接口设计；若使用 Anthropic 等非 OpenAI 兼容接口，需要另写适配器。
