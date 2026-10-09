# LiteClaw

LiteClaw v0.7 是一个个人 AI Agent Runtime。它维护自己的有界 Agent Loop、Tool Registry、Context Builder、混合记忆检索和持久化任务调度器；FastAPI 对外提供会话、对话、SSE 实时事件、记忆、审批、任务和评测接口。服务支持 API Key 访问控制、加密浏览器登录态、Eval 仪表盘、可选 pgvector 记忆索引、OpenTelemetry 追踪和 Docker Compose 部署。AgentScope 仅作为可选模型适配层，核心循环不依赖框架内部执行逻辑。

```text
Client → FastAPI → Session / SQLite → Context Builder → Agent Runtime → Model Adapter
                              ↑               ↓                 ↓
                        FTS5 + Vector      Skills           Tool Registry
                        Hybrid Memory                    File / Shell / Browser / MCP
```

## 环境

- Python 3.10+；当前依赖组合在 Python 3.10 上验证。
- 浏览器工具需要 Playwright Chromium。
- 本地 MCP 示例只需要 Python；其他 MCP server 可能需要 Node.js。
- AgentScope 1.x 可选。它与 Python 3.10 和 MCP 1.x 兼容；AgentScope 2.x 需要 Python 3.11+，不在当前锁定组合中。

## 一分钟启动

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m playwright install chromium
Copy-Item .env.example .env
python scripts/init_db.py
python -m liteclaw
```

macOS/Linux 把激活命令改成 `source .venv/bin/activate`，复制配置用 `cp .env.example .env`。也可用 `uvicorn app.main:app --reload` 启动。访问 `http://127.0.0.1:8000/health` 应返回 `status=ok` 与 `database=ready`。

无 API Key 时，把 `.env` 中 `LITECLAW_MODEL_PROVIDER` 改成 `fake`。FakeModel 可稳定展示 calculator 的“模型发出工具调用 → 工具返回观察结果 → 模型形成答案”闭环，也能演示明确要求保存的记忆。它不是通用语言模型。

## 服务鉴权与 Docker 部署（v0.4）

设置 `LITECLAW_SERVER_API_KEY` 后，所有 `/v1` 接口都要求 `Authorization: Bearer <key>` 或 `X-API-Key: <key>`；`/health` 保持公开，供容器健康检查使用。未设置该变量时，本地开发默认关闭服务鉴权。

```powershell
$headers = @{Authorization='Bearer replace-with-a-long-random-key'}
Invoke-RestMethod -Headers $headers -Method Post -Uri http://127.0.0.1:8000/v1/sessions -ContentType application/json -Body '{}'
```

Docker Compose 会强制要求服务密钥，并把数据库保存在命名卷、文件工具工作区映射到仓库的 `workspace` 目录：

```powershell
$env:LITECLAW_SERVER_API_KEY='replace-with-a-long-random-key'
docker compose up --build
```

镜像内使用非 root 用户运行，并预装 Playwright Chromium。可用 `LITECLAW_PORT` 改变宿主机暴露端口；容器内部固定监听 8000。

## 浏览器登录态持久化（v0.5）

设置 Fernet 密钥后，Playwright cookie 与 local storage 会按 LiteClaw session 加密保存，并在服务重启后恢复。未设置密钥时保持 v0.4 的仅内存行为。

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# 把输出写入 .env 的 LITECLAW_BROWSER_STATE_KEY
```

状态文件位于 `data/browser_state`，只包含密文。`GET /v1/browser/sessions/{session_id}/state` 只返回启用状态、是否存在和更新时间；`DELETE` 同一路径可关闭该会话的 browser context 并清除登录态。密钥遗失后原有状态无法恢复。

## Eval 仪表盘与坏案例回流（v0.5）

访问 `http://127.0.0.1:8000/evals` 可查看案例、运行所有启用案例和比较最近通过率。若配置了服务 API Key，在页面顶部输入；密钥仅保存在当前标签页的 `sessionStorage`。评测使用当前模型和完整 Agent loop，每个案例拥有独立 session，单个错误不会中断其余案例。

```powershell
$case = Invoke-RestMethod -Headers $headers -Method Post -Uri http://127.0.0.1:8000/v1/evals/cases -ContentType application/json -Body (@{
  name='calculator regression'; prompt='calculate 2+3'; expected_contains='5'
} | ConvertTo-Json)
Invoke-RestMethod -Headers $headers -Method Post -Uri http://127.0.0.1:8000/v1/evals/run -ContentType application/json -Body '{}'
Invoke-RestMethod -Headers $headers -Method Post -Uri "http://127.0.0.1:8000/v1/evals/cases/from-run/$runId" -ContentType application/json -Body '{"name":"bad case"}'
```

当前断言是大小写不敏感的文本包含判断。删除案例不会删除已保存的运行快照。

## PostgreSQL pgvector 记忆索引（v0.6）

SQLite 仍保存全部事实数据。配置 `LITECLAW_PGVECTOR_URL` 后，已有和新增 memory embedding 会同步到 PostgreSQL，向量检索优先使用 pgvector cosine distance；连接、扩展或查询失败时自动退回 sqlite-vec，再退回 Python cosine。`/health` 的 `pgvector` 字段显示 `disabled`、`ready` 或 `unavailable`，不会暴露连接 URL。

本地连接已有 PostgreSQL：

```powershell
python -m pip install -e ".[postgres]"
$env:LITECLAW_PGVECTOR_URL='postgresql://liteclaw:password@127.0.0.1:5432/liteclaw'
python -m liteclaw
```

使用仓库提供的 pgvector Compose 叠加文件：

```powershell
$env:LITECLAW_SERVER_API_KEY='replace-with-a-long-random-key'
$env:LITECLAW_POSTGRES_PASSWORD='use-a-url-safe-password'
docker compose -f compose.yaml -f compose.pgvector.yaml up --build
```

该部署使用固定的 `pgvector/pgvector:0.8.7-pg17-bookworm` 镜像和独立数据卷。当前表使用无固定维度的 `vector` 列以兼容不同 embedding provider；达到大规模数据后，应按实际维度增加 HNSW 或 IVFFlat 索引。

## OpenTelemetry 追踪（v0.7）

安装 telemetry extra 并配置 OTLP HTTP traces endpoint 后，LiteClaw 会导出 `http.request`、`agent.run`、`model.complete` 和 `tool.execute` spans。它们共享 trace context，API 响应通过 `X-Trace-ID` 返回定位标识。span 不记录 prompt、工具参数、API Key 或 cookie。

```powershell
python -m pip install -e ".[telemetry]"
$env:LITECLAW_OTLP_ENDPOINT='http://127.0.0.1:4318/v1/traces'
$env:LITECLAW_OTEL_SERVICE_NAME='liteclaw-local'
python -m liteclaw
```

需要 collector 鉴权时，可设置逗号分隔的 `LITECLAW_OTLP_HEADERS`。未配置 endpoint 时 health 显示 `tracing=disabled`；依赖缺失或初始化失败时显示 `unavailable`，主 API 仍可运行。

## API 示例

```powershell
$session = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/sessions -ContentType application/json -Body '{}'
$session.id
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/chat -ContentType application/json -Body (@{session_id=$session.id; message='calculate (1234*17+8)/3'} | ConvertTo-Json)
Invoke-RestMethod -Uri "http://127.0.0.1:8000/v1/sessions/$($session.id)"
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/v1/memory/search?q=Atlas'
```

`POST /v1/chat` 可省略 `session_id`，系统会创建会话。`GET /v1/runs/{run_id}` 返回执行状态、trace 和 tool events。显式记忆使用 `POST /v1/memory`，删除使用 `DELETE /v1/memory/{id}`。

## SSE 实时事件（v0.3）

`POST /v1/chat/stream` 使用和普通 chat 相同的 JSON 请求体，返回 `text/event-stream`。事件按顺序包含 `session`、Agent run、模型步骤、工具步骤、最终回答或审批等待，最后以 `done` 结束。

```powershell
$body = @{message='calculate (1234*17+8)/3'} | ConvertTo-Json
curl.exe -N -X POST http://127.0.0.1:8000/v1/chat/stream `
  -H 'Content-Type: application/json' `
  -d $body
```

高风险工具会产生 `approval_required`，随后连接结束，不会持续占用连接等待人工操作。调用原有 approve/reject API 后，可从审批响应或 `GET /v1/runs/{run_id}` 获取恢复结果。流事件不会包含完整工具参数、密码或 token。客户端提前断开不会取消已经开始的 Agent 工作。

当前版本传输真实的 Agent 步骤事件，不伪造 token 增量。模型级 token streaming 需要 OpenAI-compatible 和 AgentScope 适配器提供统一增量接口，将在后续兼容版本实现。

## 模型配置

默认使用 OpenAI-compatible Chat Completions。复制 `.env.example`，设置 `LITECLAW_MODEL`、`LITECLAW_BASE_URL`、`LITECLAW_API_KEY`，再把 provider 设为 `openai_compatible`。密钥仅存放在 `.env` 或环境变量中；`.env` 已列入 `.gitignore`。

可选 AgentScope 适配层：

```powershell
python -m pip install -e ".[agentscope]"
```

然后设置 `LITECLAW_MODEL_PROVIDER=agentscope`。当前适配器针对 AgentScope 1.0.21；无密钥时自动退回本项目的 OpenAI-compatible adapter，并明确返回认证错误。没有配置真实模型时，服务、FakeModel、记忆和本地工具测试仍可运行。

## 工具与审批

内置工具有 `calculator`、`datetime_now`、`file_read`、`file_write`、`shell_run`，以及 `browser_open`、`browser_extract`、`browser_click`、`browser_type`、`browser_screenshot`。文件工具限定在 `LITECLAW_WORKSPACE_ROOT` 下，路径逃逸会被拒绝；calculator 仅解析白名单 AST，不执行 Python 代码；浏览器默认阻止 `file://`、localhost 和内网地址。

`shell_run`、`browser_click`、MCP 工具与覆盖已有文件默认需要审批。收到 HTTP 202 时，先检查返回的 `tool_name` 和 `arguments`，然后调用 `POST /v1/approvals/{approval_id}/approve` 或 `/reject`。测试环境可显式设置 `LITECLAW_REQUIRE_APPROVAL=false`。

添加 Python Tool：继承 `app.tools.base.BaseTool`，定义 `name`、`description`、Pydantic `args_model`，实现异步 `run`，然后在 `app/main.py` 注册。Tool Registry 负责参数校验、超时和错误观察结果。

## MCP

配置文件默认是工作区根目录的 `mcp_servers.yaml`。每个服务使用 `transport: stdio`、`command` 和 `args`。可以复制 `mcp_servers.example.yaml` 并按本机虚拟环境路径调整命令。启动时自动发现工具，内部注册名为 `mcp.{server}.{tool}`；提供给模型的函数名转换为兼容格式，如 `mcp_demo_echo`。服务不可用时主 API 仍能启动。

## Skills

在 `skills/<name>/SKILL.md` 中写 YAML front matter：`name`、`description`、`triggers`、`required_tools`，后面写具体说明。SkillSelector 按请求关键词选最多三个，并在 token 限额内注入系统上下文。仓库自带 `web_research` 和 `python_env` 示例。

## Memory 与上下文

原始消息保存在 SQLite；长期记忆单独保存并同步写入 FTS5。配置 `LITECLAW_EMBEDDING_MODEL` 且有 API Key 后，embedding 使用缓存，查询时将关键词与向量结果用 RRF 融合。安装 `.[vector]` 可启用 sqlite-vec KNN；未安装或加载失败时退回 Python 余弦检索；无 embedding 配置时仅用 FTS5。

Context Builder 保留系统规则、选中的 Skills、滚动会话摘要、相关记忆与近期消息，并限制 token 预算。摘要在新增约 12 条消息或 6000 tokens 后更新；配置真实模型时使用结构化 JSON 摘要，模型不可用时退回确定性摘要。明确说“记住…”或 “Remember…” 会写入长期记忆；说“不要记住”会跳过该轮写入，说“忘记…”会删除匹配记忆。配置真实模型后，每轮还会尝试以严格 JSON 抽取稳定的事实、偏好与目标；解析失败不会影响主回答。

可选 Planner 通过 `LITECLAW_ENABLE_PLANNER=true` 开启，请求 `POST /v1/chat` 时加 `"plan":true`。Planner 最多分成五个顺序子任务，为每个 Worker 创建独立会话，并汇总结果。子任务等待高风险工具审批时，API 返回 202；审批后从 SQLite 中保存的计划状态继续执行。普通请求仍走单 Agent。

## 持久化任务（v0.2）

任务调度器支持一次性任务和固定间隔周期任务。定义、下一次执行时间、重试次数和最近 20 次执行记录保存在 SQLite，服务重启后仍会恢复。当前版本面向单进程 Uvicorn；不要用多个 worker 同时运行同一个数据库。

```powershell
$body = @{
  name = 'Atlas 状态检查'
  prompt = '检查 Atlas 项目状态并给出简短总结'
  schedule_type = 'once'
  run_at = (Get-Date).ToUniversalTime().AddMinutes(2).ToString('o')
} | ConvertTo-Json
$task = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/tasks -ContentType application/json -Body $body
Invoke-RestMethod http://127.0.0.1:8000/v1/tasks/$($task.id)
Invoke-RestMethod -Method Post http://127.0.0.1:8000/v1/tasks/$($task.id)/pause
Invoke-RestMethod -Method Post http://127.0.0.1:8000/v1/tasks/$($task.id)/resume
```

周期任务把 `schedule_type` 设为 `interval`，并提供至少 10 秒的 `interval_seconds`。失败默认最多重试两次，间隔依次为 5 秒和 15 秒；可用 `max_retries` 调整为 0–5。任务触发高风险工具时进入 `waiting_approval`，调用原有审批接口后继续执行。`GET /health` 的 `tasks` 字段显示调度器状态、正在执行数量和最近轮询时间。

## 验证

```powershell
pytest -q
ruff check .
ruff format --check .
python scripts/check_browser.py
python scripts/benchmark.py
```

真实模型验证需要用户自己配置有效 API Key。浏览器 demo 需要 Chromium 和网络；其余核心测试不访问公网。详细的五分钟演示见 `DEMO.md`。

当前 v0.7 验收覆盖同步调用、真实 HTTP SSE 事件流、工具调用、审批边界、持久化任务、服务鉴权、加密浏览器状态、Eval 回归、pgvector 降级、OpenTelemetry span 层级和部署文件。由于 Docker Desktop 引擎未启动，只验证 Compose 配置；由于本机没有 PostgreSQL 和 OTLP collector，外部服务集成使用适配层和降级测试验证。

当前开发环境完整测试为 `88 passed`；不安装可选 sqlite-vec 扩展的干净环境为 `87 passed, 1 skipped`。跳过项只覆盖 sqlite-vec 原生扩展，Python 余弦降级路径仍通过测试。
