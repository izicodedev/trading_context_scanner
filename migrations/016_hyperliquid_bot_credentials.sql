-- API agents may be shared by more than one isolated bot subaccount.
ALTER TABLE hyperliquid_bots
    DROP CONSTRAINT IF EXISTS hyperliquid_bots_network_agent_address_key;

CREATE INDEX IF NOT EXISTS hyperliquid_bots_network_agent_address_idx
    ON hyperliquid_bots(network, agent_address)
    WHERE agent_address IS NOT NULL;

-- Preserve the already-enrolled account agent for existing bots. The key remains
-- encrypted and is never included in bot API responses.
UPDATE hyperliquid_bots AS bot
SET agent_address = connection.agent_address,
    encrypted_key = connection.encrypted_key,
    agent_valid_until = connection.agent_valid_until
FROM hyperliquid_connections AS connection
WHERE bot.user_id = connection.user_id
  AND bot.network = connection.network
  AND bot.master_address = connection.account_address
  AND bot.encrypted_key IS NULL
  AND connection.encrypted_key IS NOT NULL;
