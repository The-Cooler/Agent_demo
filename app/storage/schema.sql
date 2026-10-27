CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'idle',
    summary TEXT NOT NULL DEFAULT '',
    summary_upto INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    meta_json TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (session_id, seq)
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    error TEXT,
    usage_json TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT
);

CREATE TABLE IF NOT EXISTS trace_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    step_no INTEGER NOT NULL,
    thought TEXT NOT NULL DEFAULT '',
    action TEXT,
    args_json TEXT,
    observation TEXT,
    status TEXT NOT NULL,
    duration_ms INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    completed_at TEXT
);
