CREATE TABLE IF NOT EXISTS strategy_session_archive (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    session_data JSONB NOT NULL
);
