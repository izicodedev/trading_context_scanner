CREATE TABLE IF NOT EXISTS strategy_sessions (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    active BOOLEAN NOT NULL DEFAULT FALSE,
    started_at TIMESTAMPTZ NOT NULL,
    stopped_at TIMESTAMPTZ,
    history_start TIMESTAMPTZ NOT NULL,
    history_end TIMESTAMPTZ NOT NULL,
    processed_through TIMESTAMPTZ,
    heartbeat TIMESTAMPTZ,
    configuration JSONB NOT NULL,
    snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_error TEXT
);
