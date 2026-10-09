# LiteClaw 五分钟演示

## 0. 启动

按照 README 安装依赖和 Chromium。复制 `.env.example` 为 `.env`，设置 `LITECLAW_MODEL_PROVIDER=fake`，运行 `python -m liteclaw`。另开终端执行以下命令。

## 1. 展示 API 与工具循环

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
$reply = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/chat -ContentType application/json -Body '{"message":"calculate (1234*17+8)/3"}'
$reply | ConvertTo-Json -Depth 8
Invoke-RestMethod "http://127.0.0.1:8000/v1/runs/$($reply.run_id)" | ConvertTo-Json -Depth 8
```

观察 trace 的 `calculator` 调用和 `tool_events`。核心循环在 `app/core/runtime.py`。

## 2. 展示跨会话记忆

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/chat -ContentType application/json -Body '{"message":"Remember my test project is Atlas"}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/chat -ContentType application/json -Body '{"message":"What is my test project?"}'
Invoke-RestMethod 'http://127.0.0.1:8000/v1/memory/search?q=Atlas' | ConvertTo-Json -Depth 8
```

搜索结果包含 keyword/vector rank 和 RRF 分数；未配置 embedding 时只有关键词排名。

## 3. 展示浏览器

```powershell
python scripts/check_browser.py
```

脚本通过 Playwright 打开 `https://example.com`，返回标题和受长度限制的页面文本。

## 4. 展示 MCP

复制 `mcp_servers.example.yaml` 为 `mcp_servers.yaml`，修改其中的 Python 命令为当前虚拟环境解释器，重启 API。`/health` 的 `mcp.demo` 应为 `ready`。集成测试 `pytest -q tests/test_mcp_stdio.py` 会自动启动本地 stdio 服务并调用 `mcp.demo.echo`。

## 5. 展示成本与上下文指标

```powershell
python scripts/benchmark.py
```

脚本输出重复文本下 embedding 缓存的请求次数和长会话的上下文 token 估算。它只使用模拟数据，不应当把结果当作真实线上成本节约率。

## 6. 展示持久化任务

```powershell
$body = @{
  name = '两分钟后计算'
  prompt = 'calculate (1234*17+8)/3'
  schedule_type = 'once'
  run_at = (Get-Date).ToUniversalTime().AddMinutes(2).ToString('o')
} | ConvertTo-Json
$task = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/v1/tasks -ContentType application/json -Body $body
Invoke-RestMethod http://127.0.0.1:8000/v1/tasks/$($task.id) | ConvertTo-Json -Depth 8
```

重启服务后再次查询同一任务，任务定义和运行历史仍然存在。若任务调用 shell、覆盖文件或其他高风险工具，详情状态会显示 `waiting_approval`；使用返回的 approval API 批准后，任务继续完成。

## 7. 展示 SSE 实时 Agent 步骤

```powershell
$body = @{message='calculate (1234*17+8)/3'} | ConvertTo-Json
curl.exe -N -X POST http://127.0.0.1:8000/v1/chat/stream `
  -H 'Content-Type: application/json' `
  -d $body
```

终端会依次显示 `run_started`、`model_started`、`model_completed`、`tool_started`、`tool_completed`、`final` 和 `done`。把请求换成需要 shell 或覆盖文件的操作，可展示 `approval_required`；该事件不包含危险工具的完整参数。

## 8. 展示服务鉴权与容器部署

在 `.env` 中设置 `LITECLAW_SERVER_API_KEY=demo-secret` 并重启服务。此时不带密钥访问 `/v1/sessions` 会返回 401，带 Bearer 密钥可正常调用；`/health` 无需密钥。

```powershell
curl.exe -i http://127.0.0.1:8000/v1/sessions
curl.exe -i http://127.0.0.1:8000/health
curl.exe -i -H 'Authorization: Bearer demo-secret' http://127.0.0.1:8000/v1/sessions

$env:LITECLAW_SERVER_API_KEY='demo-secret'
docker compose up --build
```

## 9. 展示浏览器登录态恢复

生成 Fernet 密钥并写入 `.env` 的 `LITECLAW_BROWSER_STATE_KEY`，重启服务。使用同一个 LiteClaw session 完成网站登录后，浏览器工具动作会把 storage state 加密写入磁盘。

```powershell
Invoke-RestMethod -Headers $headers "http://127.0.0.1:8000/v1/browser/sessions/$sessionId/state"
```

重启 LiteClaw 并继续使用同一 session，Playwright context 会恢复登录态。演示结束后可调用同一路径的 `DELETE` 清除。

## 10. 展示 Eval 和坏案例回流

打开 `http://127.0.0.1:8000/evals`，输入服务 API Key。先通过 API 添加一个 calculator 案例，再在页面点击“运行已启用案例”，观察通过率和运行历史。任意对话结果不符合预期时，调用 `POST /v1/evals/cases/from-run/{run_id}` 将原始用户请求保存为回归案例。

## 11. 展示 pgvector 可选索引

设置服务密钥和 URL-safe PostgreSQL 密码，使用两个 Compose 文件启动。配置 embedding model 与模型 API Key 后，先显式写入一条 memory，再调用 memory search。

```powershell
$env:LITECLAW_SERVER_API_KEY='demo-secret'
$env:LITECLAW_POSTGRES_PASSWORD='postgres-secret'
docker compose -f compose.yaml -f compose.pgvector.yaml up --build
Invoke-RestMethod -Headers @{Authorization='Bearer demo-secret'} http://127.0.0.1:8000/health
```

health 中 `pgvector=ready` 表示远端索引已启用。停止 PostgreSQL 后，主 API 仍会使用本地向量路径完成搜索。

## 12. 展示 OpenTelemetry trace

启动支持 OTLP HTTP 的 collector，把 `.env` 中 `LITECLAW_OTLP_ENDPOINT` 指向其 `/v1/traces`。调用一次 chat 后，响应头的 `X-Trace-ID` 可用于查询整条 HTTP → Agent → Model → Tool trace。

```powershell
curl.exe -i -X POST http://127.0.0.1:8000/v1/chat `
  -H 'Content-Type: application/json' `
  -H 'Authorization: Bearer demo-secret' `
  -d '{"message":"calculate 2+3"}'
```

## 13. 展示模型兼容性自检

在 `.env` 中填写真实模型配置后运行：

```powershell
python -m app.model_doctor
```

检查结果应依次显示 `configuration`、`chat`、`tool_calling` 和 `structured_json` 为 `ok=true`，总结果也为 `ok=true`。输出不包含 API Key 和模型回复正文。该步骤会发出三次短请求。

## 14. 展示受控桌面工具

安装 desktop extra，在 `.env` 中设置 `LITECLAW_DESKTOP_ENABLED=true` 并保持 `LITECLAW_REQUIRE_APPROVAL=true`。请求助手保存桌面截图或点击指定坐标时，首次响应应为 HTTP 202；检查工具名和坐标后调用 approve API，操作才会发生。把鼠标移动到主屏幕左上角可触发 PyAutoGUI fail-safe。

截图会写入 `data/desktop_screenshots/<session_id>`。演示结束后把 `LITECLAW_DESKTOP_ENABLED` 恢复为 `false`。

## 15. 展示 RBAC

设置 `LITECLAW_RBAC_ENABLED=true` 和一个强随机 `LITECLAW_SERVER_API_KEY`。使用该管理员 Key 创建 `viewer` 和 `user`，分别签发 Token。viewer 可以读取会话但创建会话返回 403；user 可以创建会话；撤销 Token 后再次访问返回 401。Token 明文只会出现在签发响应中。
