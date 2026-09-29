ALTER TABLE strategy_sessions ADD COLUMN IF NOT EXISTS symbol TEXT NOT NULL DEFAULT 'BTCUSDT';
ALTER TABLE strategy_sessions DROP CONSTRAINT strategy_sessions_pkey;
ALTER TABLE strategy_sessions ADD PRIMARY KEY (user_id, symbol);
ALTER TABLE user_simulation_selection ADD COLUMN IF NOT EXISTS symbol TEXT NOT NULL DEFAULT 'BTCUSDT';
ALTER TABLE user_simulation_selection DROP CONSTRAINT user_simulation_selection_pkey;
ALTER TABLE user_simulation_selection ADD PRIMARY KEY (user_id, symbol);
CREATE TABLE IF NOT EXISTS user_market_preferences (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL DEFAULT 'BTCUSDT' CHECK (symbol IN ('BTCUSDT', 'ETHUSDT')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
