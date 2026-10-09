import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Response
from fastapi.responses import JSONResponse

from app.api.approvals import router as approvals_router
from app.api.browser import router as browser_router
from app.api.chat import router as chat_router
from app.api.evals import router as evals_router
from app.api.memory import router as memory_router
from app.api.sessions import router as sessions_router
from app.api.streaming import router as streaming_router
from app.api.tasks import router as tasks_router
from app.config import Settings
from app.core.context import ContextBuilder
from app.core.planner import Planner
from app.core.runtime import AgentRuntime
from app.evals.repository import EvalRepository
from app.evals.service import EvalService
from app.logging import configure_logging, get_logger, log_event
from app.memory.embeddings import CachedEmbeddings, OpenAIEmbeddingProvider
from app.memory.hybrid import HybridRetriever
from app.memory.pgvector import PgVectorStore
from app.memory.repository import Database
from app.memory.writer import MemoryWriter
from app.models.agentscope_adapter import AgentScopeModelAdapter
from app.models.fake import FakeModel
from app.models.openai_compatible import OpenAICompatibleModel
from app.observability.tracing import Tracing
from app.security import credentials_valid
from app.skills.loader import SkillLoader
from app.skills.selector import SkillSelector
from app.tasks.models import utc_now
from app.tasks.repository import TaskRepository
from app.tasks.scheduler import TaskScheduler
from app.tasks.service import TaskService
from app.tools.browser.manager import BrowserManager
from app.tools.browser.state import BrowserStateStore
from app.tools.browser.tools import (
    BrowserClickTool,
    BrowserExtractTool,
    BrowserOpenTool,
    BrowserScreenshotTool,
    BrowserTypeTool,
)
from app.tools.builtin.calculator import CalculatorTool
from app.tools.builtin.datetime_tool import DateTimeTool
from app.tools.builtin.file_tools import FileReadTool, FileWriteTool
from app.tools.builtin.shell import ShellRunTool
from app.tools.mcp.client import MCPClientManager
from app.tools.registry import ToolRegistry


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    tracing = Tracing(
        settings.otlp_endpoint, settings.otel_service_name, settings.otlp_headers
    )
    database = Database(settings.database_path)
    registry = ToolRegistry()
    registry.register(CalculatorTool())
    registry.register(DateTimeTool())
    registry.register(FileReadTool(settings.workspace_root))
    registry.register(FileWriteTool(settings.workspace_root))
    registry.register(ShellRunTool(settings.workspace_root))
    browser_state_store = BrowserStateStore(
        settings.workspace_root / "data" / "browser_state",
        settings.browser_state_key,
    )
    browser = BrowserManager(
        settings.workspace_root,
        settings.browser_headless,
        state_store=browser_state_store,
    )
    mcp_manager = MCPClientManager(settings.mcp_config_path)
    for tool in (
        BrowserOpenTool,
        BrowserExtractTool,
        BrowserClickTool,
        BrowserTypeTool,
        BrowserScreenshotTool,
    ):
        registry.register(tool(browser))
    if settings.model_provider == "fake":
        model = FakeModel()
    elif settings.model_provider == "agentscope" and settings.api_key:
        try:
            model = AgentScopeModelAdapter(
                settings.model, settings.base_url, settings.api_key
            )
        except ImportError:
            model = OpenAICompatibleModel(
                settings.model, settings.base_url, settings.api_key
            )
    elif settings.model_provider in {"agentscope", "openai_compatible"}:
        model = OpenAICompatibleModel(
            settings.model, settings.base_url, settings.api_key
        )
    else:
        raise ValueError(f"Unknown model provider: {settings.model_provider}")
    embeddings = (
        CachedEmbeddings(
            database,
            OpenAIEmbeddingProvider(
                settings.embedding_model, settings.base_url, settings.api_key
            ),
        )
        if settings.embedding_model and settings.api_key
        else None
    )
    pgvector = PgVectorStore(settings.pgvector_url, settings.pgvector_table)
    retriever = HybridRetriever(database, embeddings, pgvector)
    memory_extractor_model = (
        model if settings.api_key and settings.model_provider != "fake" else None
    )
    skills = SkillLoader(settings.workspace_root / "skills").load()
    selector = SkillSelector(skills, {tool.name for tool in registry._tools.values()})
    context_builder = ContextBuilder(
        database,
        retriever,
        settings.context_token_budget,
        settings.recent_message_tokens,
        settings.memory_top_k,
        selector,
    )
    runtime = AgentRuntime(
        database,
        model,
        registry,
        settings.max_agent_steps,
        context_builder,
        MemoryWriter(
            database,
            embeddings,
            memory_extractor_model,
            vector_store=pgvector,
        ),
        settings.workspace_root,
        settings.require_approval,
        tracing,
    )
    task_repository = TaskRepository(database)
    task_service = TaskService(task_repository, runtime)
    eval_repository = EvalRepository(database)
    eval_service = EvalService(database, eval_repository, runtime)
    scheduler = TaskScheduler(
        task_repository,
        task_service,
        settings.tasks_enabled,
        settings.task_poll_seconds,
        settings.task_max_concurrency,
        settings.task_shutdown_timeout,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        configure_logging(settings.log_level)
        tracing.initialize()
        await database.initialize()
        if await pgvector.initialize():
            await pgvector.sync(await database.all_memories())
        await mcp_manager.start(registry)
        await task_repository.recover_expired(utc_now(), settings.task_lease_seconds)
        await scheduler.start()
        logger = get_logger(__name__)
        if hasattr(logger, "bind"):
            logger.info("database.ready", path=str(database.path))
        else:
            logger.info(
                "database.ready", extra={"fields": {"path": str(database.path)}}
            )
        try:
            yield
        finally:
            await scheduler.stop()
            streaming_tasks = list(application.state.streaming_tasks)
            if streaming_tasks:
                _, pending = await asyncio.wait(
                    streaming_tasks, timeout=settings.task_shutdown_timeout
                )
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
            await mcp_manager.close()
            await browser.close()
            await pgvector.close()
            tracing.shutdown()

    application = FastAPI(title="LiteClaw", version="0.7.0", lifespan=lifespan)
    application.state.settings = settings
    application.state.database = database
    application.state.registry = registry
    application.state.runtime = runtime
    application.state.planner = Planner(
        database,
        model,
        lambda: AgentRuntime(
            database,
            model,
            registry,
            4,
            context_builder,
            MemoryWriter(
                database,
                embeddings,
                memory_extractor_model,
                vector_store=pgvector,
            ),
            settings.workspace_root,
            settings.require_approval,
            tracing,
        ),
    )
    application.state.retriever = retriever
    application.state.embeddings = embeddings
    application.state.pgvector = pgvector
    application.state.browser = browser
    application.state.mcp = mcp_manager
    application.state.task_repository = task_repository
    application.state.task_service = task_service
    application.state.eval_repository = eval_repository
    application.state.eval_service = eval_service
    application.state.scheduler = scheduler
    application.state.tracing = tracing
    application.state.streaming_tasks = set()

    @application.middleware("http")
    async def request_logging(request, call_next):
        request_id = uuid4().hex
        request_tracing = application.state.tracing
        with request_tracing.span(
            "http.request",
            request_id=request_id,
            http_method=request.method,
            http_path=request.url.path,
        ) as span:
            if (
                settings.server_api_key
                and request.url.path.startswith("/v1")
                and not credentials_valid(request.headers, settings.server_api_key)
            ):
                response = JSONResponse(
                    status_code=401,
                    content={"detail": {"code": "unauthorized"}},
                    headers={"WWW-Authenticate": "Bearer"},
                )
            else:
                response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            trace_id = request_tracing.trace_id(span)
            if trace_id:
                response.headers["X-Trace-ID"] = trace_id
            if span is not None:
                span.set_attribute("http.status_code", response.status_code)
            log_event(
                "http.request",
                request_id=request_id,
                trace_id=trace_id,
                path=request.url.path,
                status_code=response.status_code,
            )
            return response

    application.include_router(sessions_router)
    application.include_router(browser_router)
    application.include_router(chat_router)
    application.include_router(memory_router)
    application.include_router(approvals_router)
    application.include_router(tasks_router)
    application.include_router(streaming_router)
    application.include_router(evals_router)

    @application.get("/health")
    async def health(response: Response) -> dict:
        if await database.ready():
            return {
                "status": "ok",
                "database": "ready",
                "mcp": mcp_manager.status,
                "embedding": embeddings.stats if embeddings else "disabled",
                "pgvector": pgvector.status,
                "tracing": tracing.status,
                "tasks": scheduler.health(),
            }
        response.status_code = 503
        return {"status": "unavailable", "database": "unavailable"}

    return application


app = create_app()
