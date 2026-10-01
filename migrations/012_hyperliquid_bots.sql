-- A bot owns one sub-account. Positions in the same account are netted by the exchange.
CREATE TABLE IF NOT EXISTS hyperliquid_bots (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 3 AND 60),
    market TEXT NOT NULL DEFAULT 'BTC' CHECK (market ~ '^[A-Z0-9-]+$'),
    network TEXT NOT NULL CHECK (network IN ('testnet', 'mainnet')),
    master_address TEXT CHECK (master_address IS NULL OR master_address ~ '^0x[0-9a-f]{40}$'),
    wallet_address TEXT NOT NULL CHECK (wallet_address ~ '^0x[0-9a-f]{40}$'),
    account_address TEXT NOT NULL CHECK (account_address ~ '^0x[0-9a-f]{40}$'),
    coin TEXT,
    subaccount TEXT,
    strategy_key TEXT,
    strategy_name TEXT,
    strategy_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    capital_reserved DOUBLE PRECISION NOT NULL DEFAULT 0,
    max_utilization_pct DOUBLE PRECISION NOT NULL DEFAULT 70 CHECK (max_utilization_pct >= 0 AND max_utilization_pct <= 100),
    leverage INTEGER NOT NULL DEFAULT 1 CHECK (leverage >= 1 AND leverage <= 40),
    sizing_mode TEXT NOT NULL DEFAULT 'fixed' CHECK (sizing_mode IN ('fixed', 'available_balance')),
    status TEXT NOT NULL DEFAULT 'stopped' CHECK (status IN ('running', 'paused', 'stopped', 'error')),
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    risk_limits JSONB,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    agent_address TEXT,
    encrypted_key TEXT,
    agent_valid_until BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(network, account_address),
    UNIQUE(network, agent_address),
    CHECK (wallet_address <> account_address)
);
ALTER TABLE hyperliquid_runs ADD COLUMN IF NOT EXISTS bot_id BIGINT REFERENCES hyperliquid_bots(id);
DROP INDEX IF EXISTS one_managed_account;
DROP INDEX IF EXISTS one_managed_user;
CREATE UNIQUE INDEX IF NOT EXISTS one_managed_bot ON hyperliquid_runs(bot_id) WHERE managing AND bot_id IS NOT NULL;

-- Keep backward compatibility for existing single-account deployments.
ALTER TABLE hyperliquid_bots ADD COLUMN IF NOT EXISTS market TEXT;
ALTER TABLE hyperliquid_bots ADD COLUMN IF NOT EXISTS strategy_name TEXT;
ALTER TABLE hyperliquid_bots ADD COLUMN IF NOT EXISTS capital_reserved DOUBLE PRECISION;
ALTER TABLE hyperliquid_bots ADD COLUMN IF NOT EXISTS max_utilization_pct DOUBLE PRECISION;
ALTER TABLE hyperliquid_bots ADD COLUMN IF NOT EXISTS leverage INTEGER;
ALTER TABLE hyperliquid_bots ADD COLUMN IF NOT EXISTS sizing_mode TEXT;
ALTER TABLE hyperliquid_bots ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE hyperliquid_bots ADD COLUMN IF NOT EXISTS is_active BOOLEAN;
ALTER TABLE hyperliquid_bots ADD COLUMN IF NOT EXISTS strategy_config JSONB;
ALTER TABLE hyperliquid_bots ADD COLUMN IF NOT EXISTS metadata JSONB;
