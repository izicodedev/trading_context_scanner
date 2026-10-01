INSERT INTO hyperliquid_bots (
    user_id,
    name,
    market,
    coin,
    network,
    master_address,
    wallet_address,
    account_address,
    subaccount,
    strategy_key,
    strategy_name,
    strategy_config,
    capital_reserved,
    max_utilization_pct,
    leverage,
    sizing_mode,
    status,
    is_active,
    risk_limits,
    metadata
)
SELECT
    run.user_id,
    run.configuration->'strategy'->>'name',
    'BTC',
    'BTC',
    run.network,
    lower(connection.account_address),
    lower(connection.account_address),
    lower(run.account_address),
    lower(run.account_address),
    run.configuration->'strategy'->>'key',
    run.configuration->'strategy'->>'name',
    COALESCE(run.configuration->'strategy', '{}'::jsonb),
    COALESCE(NULLIF(run.configuration->'limits'->>'capital_usdc', '')::DOUBLE PRECISION, 0),
    CASE
        WHEN run.configuration->'limits'->>'sizing_mode' = 'available_balance' THEN 100
        ELSE 70
    END,
    COALESCE(NULLIF(run.configuration->'limits'->>'max_leverage', '')::INTEGER, 1),
    COALESCE(run.configuration->'limits'->>'sizing_mode', 'fixed'),
    'stopped',
    FALSE,
    run.configuration->'limits',
    jsonb_build_object('source', 'legacy_run', 'run_id', run.id)
FROM hyperliquid_runs AS run
JOIN hyperliquid_connections AS connection
  ON connection.user_id = run.user_id
 AND connection.network = run.network
WHERE run.id = 7
  AND run.bot_id IS NULL
  AND lower(run.configuration->>'account_address') = lower(run.account_address)
  AND lower(connection.account_address) <> lower(run.account_address)
  AND (
      lower(run.configuration->>'master_address') = lower(connection.account_address)
      OR lower(connection.legacy_subaccount_address) = lower(run.account_address)
  )
  AND NOT EXISTS (
      SELECT 1
      FROM hyperliquid_bots AS bot
      WHERE bot.network = run.network
        AND bot.account_address = lower(run.account_address)
  );

UPDATE hyperliquid_runs AS run
SET bot_id = bot.id
FROM hyperliquid_bots AS bot
JOIN hyperliquid_connections AS connection
  ON connection.user_id = bot.user_id
 AND connection.network = bot.network
WHERE run.id = 7
  AND run.bot_id IS NULL
  AND bot.user_id = run.user_id
  AND bot.network = run.network
  AND bot.account_address = lower(run.account_address)
  AND bot.master_address = lower(connection.account_address)
  AND bot.wallet_address = bot.master_address
  AND lower(run.configuration->>'account_address') = lower(run.account_address)
  AND lower(connection.account_address) <> lower(run.account_address)
  AND (
      lower(run.configuration->>'master_address') = lower(connection.account_address)
      OR lower(connection.legacy_subaccount_address) = lower(run.account_address)
  );
