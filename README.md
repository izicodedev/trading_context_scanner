# Trading Context Scanner

Local Python scanner for BTC/USDT using Binance public market data. It generates LONG/SHORT/WAIT context scores from trend, momentum, volume, volatility, Fibonacci pullback, liquidity sweeps and support/resistance.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m app.main
```

The scanner writes signals to `data/signals.csv` and logs to `logs/scanner.log`.
