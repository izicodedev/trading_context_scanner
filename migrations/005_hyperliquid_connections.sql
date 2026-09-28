CREATE TABLE IF NOT EXISTS hyperliquid_connections (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    network TEXT NOT NULL CHECK (network IN ('testnet', 'mainnet')),
    account_address TEXT NOT NULL CHECK (account_address ~ '^0x[0-9a-f]{40}$'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
