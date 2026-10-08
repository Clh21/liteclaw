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
