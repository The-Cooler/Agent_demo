# AI Prompt 与问题解决记录

本次题目用 Claude Code 作为开发工具。下面按时间顺序记录实际用到的关键 prompt、遇到的具体问题和最后怎么解决的。失败和返工也记在里面，不挑好看的说。


## 一、关键 prompt 与产出

### 1. 技术选型

- 原始表述：「核心 Agent Runtime 不依赖任何 Agent 框架，Web 层使用 OpenAI 库，数据模型与校验使用 Pydantic，Agent 模式采用 ReAct，并支持相互隔离的多 session 管理」
- 提炼需求：
  - 核心 Agent Runtime 不得依赖任何 Agent 框架（LangGraph / OpenHands / LangChain 等）
  - Web 层使用 OpenAI 框架，数据模型与校验使用 Pydantic
  - Agent 模式采用 ReAct
  - 支持多 session 管理，不同 session 相互隔离

### 2. 架构落盘

- 原始表述：「将系统架构写成 Markdown 文档，落到 `docs/DESIGN.md`」
- 提炼需求：将系统架构写成 Markdown 文档，落到 `docs/DESIGN.md`

### 3. 工程化约束

- 原始表述：「依赖管理统一使用 uv，按模块拆分，由多个 subagent 并行实现，所有命令在 Windows 环境执行，不通过 bash 内联脚本」
- 提炼需求：
  - 依赖管理统一使用 uv
  - 按模块拆分，由多个 subagent 并行实现
  - 所有命令在 Windows 环境执行，不通过 bash 内联脚本
  - 环境变量缺失时先向用户确认，不自行编造

### 4. 前端

- 原始表述：「交付物必须包含可直接使用的对话界面，用户通过界面完成会话操作，前端代码按职责拆分为独立文件，不把 HTML、CSS、JS 全部放在同一个文件里」
- 提炼需求：
  - 交付物必须包含可直接使用的对话界面，用户通过界面完成会话操作，不需要手工构造 HTTP 请求
  - 前端代码按职责拆分为独立文件，不允许把 HTML、CSS、JS 全部放在同一个文件里


## 二、问题与解决

### 问题 1：新会话首条消息被过滤

- 现象：每个会话的第一条用户消息不会进入 LLM 上下文。
- 原因：`add_message` 从 `seq=0` 开始编号，而 `ContextBuilder` 用 `after_seq=summary_upto`（默认 0），`list_messages` 的条件是 `seq > after_seq`，所以 seq=0 被排除。
- 修复：`app/agent/context.py` 改为 `after_seq=session.summary_upto - 1`。
- 验证：`tests/unit/test_context.py::test_context_has_system_and_history` 先按真实（错误）行为写了断言，修完后改成正确期望，全套 76 条测试通过。

### 问题 2：超步数收尾不解析 final_answer

- 现象：达到 `max_react_steps` 后，额外调用一次 LLM 的返回被整段当答案，即使模型按协议返回了 JSON。
- 原因：`runtime.py` 直接取 `forced.content.strip()`，没有走 `parse_llm_output`。
- 修复：新增 `_forced_answer()`，能解析出 `FinalStep` 就取 `final_answer`，否则退回原文。
- 验证：新增 `test_exceed_max_react_steps_parses_final_answer`，原有非法 JSON 用例保留。

### 问题 3：会话标题不自动设置

- 现象：新建会话后标题一直是空。
- 原因：`SessionService` 从未更新过 `sessions.title`。
- 修复：新增 `SessionRepository.set_title()`；`send_message` 结束后调用 `_ensure_title()`，用首条消息前 20 字生成标题。
- 验证：浏览器实测，API 返回 `"title":"12乘以12等于多少"`。

### 问题 4：前端标题栏不刷新

- 现象：后端已经写好标题，但左侧列表和标题栏还是旧的。
- 修复：`app/static/sessions.js` 新增 `refreshSessionTitle()`，`chat.js` 发送成功后调用。
- 验证：浏览器实测，发送后标题立刻更新。

### 问题 5：设计文档与实现不一致

- 发现 8 处，包括：parser 的解析流程、重试次数语义、未实现的 LLM 网络重试、未实现的 `asyncio.Lock`、目录树缺少 `static/` 和 `tests/live/`、目录树多出 `AI_PROMPTS.md`。
- 处理：
  - 实现本身有问题的（如 max_steps 解析）改代码；
  - 文档描述不准的改文档；
  - 题目要求但缺失的（`AI_PROMPTS.md`）补文件，不靠删文档蒙混过去。

### 问题 6：Windows 下命令执行

- 现象：`uv` 和 `powershell` 在 Git Bash 里直接调用容易被内联脚本拦截，或者引号转义出错。
- 处理：所有需要执行的脚本先写成 `tmp/*.ps1` 或 `tmp/*.py`，再以文件方式运行；临时文件用完清理。

### 问题 7：工具调用没有使用原生 function calling

- 现象：模型被要求输出自定义 JSON 协议，工具定义以文本形式塞进 system prompt，工具结果和用户输入同为 `user` 角色，靠 `Observation: ` 前缀区分。
- 原因：最初把 `LLMClient.complete()` 设计成只接收 `messages`，没有设计 `tools` 通道，用提示词约束代替了 SDK 已有的能力。
- 修复：
  - `LLMClient.complete(messages, tools)`，`LLMResult` 增加 `tool_calls`
  - `OpenAIClient` 透传 `tools`，解析响应中的 `tool_calls`，`arguments` 解析失败时标记 `arguments_valid=False`
  - `ToolRegistry.openai_tools()` 输出 `{"type": "function", ...}` 格式
  - `AgentRuntime` 按 `tool_calls` 执行，结果以 `role="tool"` 和 `tool_call_id` 回灌
  - 删除 `parser.py`、`ActionStep`、`FinalStep` 及对应的解析失败分支
  - 测试替身 `FakeLLM` 改为返回 `ToolCall`，新增 `test_tools_passed_to_llm`、`test_tool_result_uses_tool_role`、`test_registry_openai_tools_format`
- 验证：`uv run pytest -q` 66 passed, 6 skipped；`uv run pytest -q tests/live --run-live` 6 passed。