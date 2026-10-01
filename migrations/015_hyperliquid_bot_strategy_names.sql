UPDATE hyperliquid_bots
SET name = strategy_name,
    updated_at = NOW()
WHERE metadata->>'source' = 'legacy_connection'
  AND name = 'Bot BTC'
  AND strategy_name IS NOT NULL
  AND length(strategy_name) BETWEEN 3 AND 60;
