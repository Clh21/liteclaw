from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LITECLAW_", env_file=".env", extra="ignore"
    )

    model_provider: str = "openai_compatible"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    model: str = "gpt-5-mini"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = Field(default="", repr=False)
    server_api_key: str = Field(default="", repr=False)
    db_path: Path = Path("data/liteclaw.db")
    workspace_root: Path = Field(default_factory=Path.cwd)
    max_agent_steps: int = Field(default=8, ge=1, le=100)
    context_token_budget: int = Field(default=24000, ge=1)
    recent_message_tokens: int = Field(default=8000, ge=1)
    memory_top_k: int = Field(default=8, ge=1)
    browser_headless: bool = True
    browser_state_key: str = Field(default="", repr=False)
    require_approval: bool = True
    log_level: str = "INFO"
    mcp_servers_path: Path = Path("mcp_servers.yaml")
    embedding_model: str = ""
    pgvector_url: str = Field(default="", repr=False)
    pgvector_table: str = "liteclaw_memory_vectors"
    enable_planner: bool = False
    tasks_enabled: bool = True
    task_poll_seconds: float = Field(default=1.0, ge=0.1, le=60)
    task_max_concurrency: int = Field(default=2, ge=1, le=20)
    task_shutdown_timeout: float = Field(default=15.0, ge=1, le=120)
    task_lease_seconds: int = Field(default=300, ge=10, le=86400)

    @property
    def database_path(self) -> Path:
        root = self.workspace_root.resolve()
        return (root / self.db_path).resolve()

    @property
    def mcp_config_path(self) -> Path:
        return (self.workspace_root.resolve() / self.mcp_servers_path).resolve()
