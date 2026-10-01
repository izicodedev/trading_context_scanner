ALTER TABLE hyperliquid_connections
    ADD COLUMN IF NOT EXISTS legacy_subaccount_address TEXT;

ALTER TABLE hyperliquid_connections
    ADD CONSTRAINT hyperliquid_connections_legacy_subaccount_address_check
    CHECK (
        legacy_subaccount_address IS NULL
        OR legacy_subaccount_address ~ '^0x[0-9a-f]{40}$'
    );
