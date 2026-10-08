# LiteClaw P0 基础实现计划

**目标：** 从空目录建立可启动、可测试的 API 和 SQLite 基础。

**架构：** 配置由 `app.config` 集中加载；`app.memory.repository` 初始化数据库；FastAPI 生命周期负责启动迁移，`/health` 检查真实数据库连接。日志只输出结构化字段，不输出配置中的密钥。

**技术栈：** Python 3.10+、FastAPI、Pydantic Settings、aiosqlite、uvicorn。

## 文件职责

- `pyproject.toml`：声明运行和开发依赖、测试配置。
- `.env.example`：提供无密钥示例配置。
- `app/config.py`：解析和校验环境变量。
- `app/logging.py`：输出 JSON 日志并保护敏感字段。
- `app/memory/schema.sql`：建表和索引。
- `app/memory/repository.py`：数据库初始化及健康探测。
- `app/main.py`：应用生命周期和健康路由。
- `app/cli.py`、`app/__main__.py`、`scripts/init_db.py`：启动和初始化入口。
- `tests/test_p0.py`：验证配置、迁移幂等性和健康路由。
- `README.md`：记录当前 P0 能力与启动命令。

## 执行步骤

- [x] 写配置、迁移、健康路由的失败测试，运行并确认因缺少实现而失败。
- [x] 实现配置、日志、数据库和 API 的最小闭环。
- [x] 实现启动脚本、依赖声明和示例环境变量。
- [x] 运行单元与 API 测试，确认迁移可重复执行。
- [x] 运行实际服务器，对 `/health` 进行 HTTP 检查。
- [x] 更新 README，报告验证结果与下一阶段 P1。
