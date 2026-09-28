ALTER TABLE hyperliquid_connections
    ADD COLUMN IF NOT EXISTS agent_address TEXT,
    ADD COLUMN IF NOT EXISTS encrypted_key TEXT,
    ADD COLUMN IF NOT EXISTS agent_valid_until BIGINT,
    ADD COLUMN IF NOT EXISTS risk_limits JSONB;
