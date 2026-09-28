CREATE TABLE IF NOT EXISTS hyperliquid_runs (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    network TEXT NOT NULL,
    account_address TEXT NOT NULL,
    configuration JSONB NOT NULL,
    state JSONB NOT NULL,
    active BOOLEAN NOT NULL DEFAULT FALSE,
    managing BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    heartbeat TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS one_managed_account ON hyperliquid_runs(network, account_address) WHERE managing;
CREATE UNIQUE INDEX IF NOT EXISTS one_managed_user ON hyperliquid_runs(user_id) WHERE managing;
CREATE TABLE IF NOT EXISTS hyperliquid_actions (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES hyperliquid_runs(id),
    action_key TEXT NOT NULL,
    cloid TEXT NOT NULL UNIQUE,
    request JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(run_id, action_key)
);
