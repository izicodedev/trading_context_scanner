-- A bot owns one sub-account. Positions in the same account are netted by the exchange.
CREATE TABLE IF NOT EXISTS hyperliquid_bots (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 3 AND 60),
    network TEXT NOT NULL CHECK (network IN ('testnet', 'mainnet')),
    master_address TEXT NOT NULL CHECK (master_address ~ '^0x[0-9a-f]{40}$'),
    account_address TEXT NOT NULL CHECK (account_address ~ '^0x[0-9a-f]{40}$'),
    coin TEXT NOT NULL CHECK (coin IN ('BTC', 'ETH')),
    strategy_key TEXT NOT NULL,
    risk_limits JSONB NOT NULL,
    agent_address TEXT,
    encrypted_key TEXT,
    agent_valid_until BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(network, account_address),
    UNIQUE(network, agent_address),
    CHECK (master_address <> account_address)
);
ALTER TABLE hyperliquid_runs ADD COLUMN IF NOT EXISTS bot_id BIGINT REFERENCES hyperliquid_bots(id);
DROP INDEX IF EXISTS one_managed_user;
CREATE UNIQUE INDEX IF NOT EXISTS one_managed_bot ON hyperliquid_runs(bot_id) WHERE managing AND bot_id IS NOT NULL;
