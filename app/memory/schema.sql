PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK(role IN ('admin','user','viewer')),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    label TEXT,
    created_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_api_tokens_user ON api_tokens(user_id);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    owner_id TEXT,
    title TEXT,
    agent_id TEXT NOT NULL DEFAULT 'main',
    summary TEXT,
    summarized_message_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT,
    tool_calls_json TEXT,
    tool_call_id TEXT,
    token_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session_created ON messages(session_id, created_at);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    owner_id TEXT,
    agent_id TEXT NOT NULL,
    session_id TEXT,
    content TEXT NOT NULL,
    kind TEXT NOT NULL,
    importance REAL NOT NULL DEFAULT 0.5,
    embedding_model TEXT,
    embedding BLOB,
    content_hash TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_agent ON memories(agent_id);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(memory_id UNINDEXED, content, tokenize='unicode61');

CREATE TABLE IF NOT EXISTS embedding_cache (
    content_hash TEXT NOT NULL,
    model TEXT NOT NULL,
    embedding BLOB NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(content_hash, model)
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    status TEXT NOT NULL,
    trace_json TEXT,
    error TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS tool_events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    arguments_json TEXT,
    result_json TEXT,
    elapsed_ms INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    tool_call_id TEXT,
    tool_name TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    decided_at TEXT
);

CREATE TABLE IF NOT EXISTS planner_runs (
    parent_run_id TEXT PRIMARY KEY REFERENCES agent_runs(id) ON DELETE CASCADE,
    plan_json TEXT NOT NULL,
    results_json TEXT NOT NULL DEFAULT '[]',
    next_index INTEGER NOT NULL DEFAULT 0,
    worker_run_id TEXT,
    worker_session_id TEXT
);

CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE RESTRICT,
    prompt TEXT NOT NULL,
    schedule_type TEXT NOT NULL,
    run_at TEXT,
    interval_seconds INTEGER,
    next_run_at TEXT NOT NULL,
    status TEXT NOT NULL,
    max_retries INTEGER NOT NULL DEFAULT 2,
    retry_count INTEGER NOT NULL DEFAULT 0,
    claimed_at TEXT,
    pause_requested INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_due
ON scheduled_tasks(status, next_run_at);

CREATE TABLE IF NOT EXISTS scheduled_task_runs (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES scheduled_tasks(id) ON DELETE CASCADE,
    agent_run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    status TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    answer TEXT,
    error TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_scheduled_task_runs_task
ON scheduled_task_runs(task_id, started_at DESC);

CREATE TABLE IF NOT EXISTS eval_cases (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    prompt TEXT NOT NULL,
    expected_contains TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    source_run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_runs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    total INTEGER NOT NULL DEFAULT 0,
    passed INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS eval_results (
    id TEXT PRIMARY KEY,
    eval_run_id TEXT NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    case_id TEXT REFERENCES eval_cases(id) ON DELETE SET NULL,
    case_name TEXT NOT NULL,
    prompt TEXT NOT NULL,
    expected_contains TEXT,
    agent_run_id TEXT REFERENCES agent_runs(id) ON DELETE SET NULL,
    status TEXT NOT NULL,
    answer TEXT,
    error TEXT,
    elapsed_ms INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eval_results_run ON eval_results(eval_run_id, created_at);

CREATE TABLE IF NOT EXISTS chat_sources (
    id TEXT PRIMARY KEY,
    owner_id TEXT,
    scope_key TEXT NOT NULL,
    filename TEXT NOT NULL,
    format TEXT NOT NULL,
    conversation TEXT,
    self_sender TEXT NOT NULL,
    timezone TEXT NOT NULL,
    file_digest TEXT NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    first_at TEXT,
    last_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(scope_key, file_digest)
);
CREATE INDEX IF NOT EXISTS idx_chat_sources_owner ON chat_sources(owner_id, created_at);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES chat_sources(id) ON DELETE CASCADE,
    owner_id TEXT,
    scope_key TEXT NOT NULL,
    conversation TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    sender TEXT NOT NULL,
    content TEXT NOT NULL,
    source_row INTEGER NOT NULL,
    fingerprint TEXT NOT NULL,
    UNIQUE(source_id, fingerprint)
);
CREATE INDEX IF NOT EXISTS idx_chat_messages_scope_time
ON chat_messages(scope_key, sent_at);
CREATE INDEX IF NOT EXISTS idx_chat_messages_source_time
ON chat_messages(source_id, sent_at);
