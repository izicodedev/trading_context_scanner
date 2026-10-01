ALTER TABLE hyperliquid_bots ADD COLUMN IF NOT EXISTS market TEXT;
ALTER TABLE hyperliquid_bots ADD COLUMN IF NOT EXISTS wallet_address TEXT;
ALTER TABLE hyperliquid_bots ADD COLUMN IF NOT EXISTS subaccount TEXT;
ALTER TABLE hyperliquid_bots ADD COLUMN IF NOT EXISTS subaccount_name TEXT;
ALTER TABLE hyperliquid_bots ADD COLUMN IF NOT EXISTS strategy_name TEXT;
ALTER TABLE hyperliquid_bots ADD COLUMN IF NOT EXISTS strategy_config JSONB;
ALTER TABLE hyperliquid_bots ADD COLUMN IF NOT EXISTS capital_reserved DOUBLE PRECISION;
ALTER TABLE hyperliquid_bots ADD COLUMN IF NOT EXISTS max_utilization_pct DOUBLE PRECISION;
ALTER TABLE hyperliquid_bots ADD COLUMN IF NOT EXISTS leverage INTEGER;
ALTER TABLE hyperliquid_bots ADD COLUMN IF NOT EXISTS sizing_mode TEXT;
ALTER TABLE hyperliquid_bots ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE hyperliquid_bots ADD COLUMN IF NOT EXISTS is_active BOOLEAN;
ALTER TABLE hyperliquid_bots ADD COLUMN IF NOT EXISTS metadata JSONB;

UPDATE hyperliquid_bots
SET market = COALESCE(NULLIF(market, ''), NULLIF(coin, ''), 'BTC'),
    wallet_address = COALESCE(NULLIF(wallet_address, ''), master_address),
    strategy_config = COALESCE(strategy_config, '{}'::jsonb),
    metadata = COALESCE(metadata, '{}'::jsonb),
    capital_reserved = COALESCE(capital_reserved, NULLIF(risk_limits->>'capital_usdc', '')::DOUBLE PRECISION, 0),
    max_utilization_pct = COALESCE(max_utilization_pct,
        CASE WHEN risk_limits->>'sizing_mode' = 'available_balance' THEN 100 ELSE 70 END),
    leverage = COALESCE(leverage, NULLIF(risk_limits->>'max_leverage', '')::INTEGER, 1),
    sizing_mode = COALESCE(sizing_mode, risk_limits->>'sizing_mode', 'fixed'),
    status = COALESCE(status, CASE WHEN EXISTS (
        SELECT 1 FROM hyperliquid_runs r WHERE r.bot_id = hyperliquid_bots.id AND r.managing AND r.active
    ) THEN 'running' ELSE 'stopped' END),
    is_active = COALESCE(is_active, FALSE);

ALTER TABLE hyperliquid_bots ALTER COLUMN market SET DEFAULT 'BTC';
ALTER TABLE hyperliquid_bots ALTER COLUMN market SET NOT NULL;
ALTER TABLE hyperliquid_bots ALTER COLUMN wallet_address SET NOT NULL;
ALTER TABLE hyperliquid_bots ALTER COLUMN strategy_config SET DEFAULT '{}'::jsonb;
ALTER TABLE hyperliquid_bots ALTER COLUMN strategy_config SET NOT NULL;
ALTER TABLE hyperliquid_bots ALTER COLUMN capital_reserved SET DEFAULT 0;
ALTER TABLE hyperliquid_bots ALTER COLUMN capital_reserved SET NOT NULL;
ALTER TABLE hyperliquid_bots ALTER COLUMN max_utilization_pct SET DEFAULT 70;
ALTER TABLE hyperliquid_bots ALTER COLUMN max_utilization_pct SET NOT NULL;
ALTER TABLE hyperliquid_bots ALTER COLUMN leverage SET DEFAULT 1;
ALTER TABLE hyperliquid_bots ALTER COLUMN leverage SET NOT NULL;
ALTER TABLE hyperliquid_bots ALTER COLUMN sizing_mode SET DEFAULT 'fixed';
ALTER TABLE hyperliquid_bots ALTER COLUMN sizing_mode SET NOT NULL;
ALTER TABLE hyperliquid_bots ALTER COLUMN status SET DEFAULT 'stopped';
ALTER TABLE hyperliquid_bots ALTER COLUMN status SET NOT NULL;
ALTER TABLE hyperliquid_bots ALTER COLUMN is_active SET DEFAULT FALSE;
ALTER TABLE hyperliquid_bots ALTER COLUMN is_active SET NOT NULL;
ALTER TABLE hyperliquid_bots ALTER COLUMN metadata SET DEFAULT '{}'::jsonb;
ALTER TABLE hyperliquid_bots ALTER COLUMN metadata SET NOT NULL;

ALTER TABLE hyperliquid_bots DROP CONSTRAINT IF EXISTS hyperliquid_bots_coin_check;
ALTER TABLE hyperliquid_bots DROP CONSTRAINT IF EXISTS hyperliquid_bots_market_check;
ALTER TABLE hyperliquid_bots ADD CONSTRAINT hyperliquid_bots_market_check CHECK (market ~ '^[A-Z0-9:-]+$');
ALTER TABLE hyperliquid_bots DROP CONSTRAINT IF EXISTS hyperliquid_bots_max_utilization_pct_check;
ALTER TABLE hyperliquid_bots ADD CONSTRAINT hyperliquid_bots_max_utilization_pct_check
    CHECK (max_utilization_pct > 0 AND max_utilization_pct <= 100);
ALTER TABLE hyperliquid_bots DROP CONSTRAINT IF EXISTS hyperliquid_bots_leverage_check;
ALTER TABLE hyperliquid_bots ADD CONSTRAINT hyperliquid_bots_leverage_check
    CHECK (leverage >= 1 AND leverage <= 40);
ALTER TABLE hyperliquid_bots DROP CONSTRAINT IF EXISTS hyperliquid_bots_sizing_mode_check;
ALTER TABLE hyperliquid_bots ADD CONSTRAINT hyperliquid_bots_sizing_mode_check
    CHECK (sizing_mode IN ('fixed', 'available_balance'));
ALTER TABLE hyperliquid_bots DROP CONSTRAINT IF EXISTS hyperliquid_bots_status_check;
ALTER TABLE hyperliquid_bots ADD CONSTRAINT hyperliquid_bots_status_check
    CHECK (status IN ('running', 'paused', 'stopped', 'error'));
ALTER TABLE hyperliquid_runs ADD COLUMN IF NOT EXISTS bot_id BIGINT REFERENCES hyperliquid_bots(id);
DROP INDEX IF EXISTS one_managed_account;
DROP INDEX IF EXISTS one_managed_user;
CREATE UNIQUE INDEX IF NOT EXISTS one_managed_bot ON hyperliquid_runs(bot_id) WHERE managing AND bot_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS hyperliquid_bots_user_status ON hyperliquid_bots(user_id, status, id);
CREATE INDEX IF NOT EXISTS hyperliquid_runs_bot_created ON hyperliquid_runs(bot_id, created_at DESC);
