CREATE TABLE IF NOT EXISTS user_simulation_strategies (
    strategy_key TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    definition JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS user_simulation_strategies_user_idx
    ON user_simulation_strategies(user_id, created_at);
CREATE TABLE IF NOT EXISTS user_simulation_selection (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    strategy_keys JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
