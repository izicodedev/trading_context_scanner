# Trading Context Scanner

Local Python scanner for BTC/USDT and ETH/USDT using Binance public market data. It generates LONG/SHORT/WAIT context scores from trend, momentum, volume, volatility, Fibonacci pullback, liquidity sweeps and support/resistance.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.main
```

With `DATABASE_URL`, the scanner stores signals and closed candles separately for both symbols in PostgreSQL and fills gaps after downtime. Without a database, it writes separate signal CSV files. See [multi-market setup](docs/multi-market.md).
