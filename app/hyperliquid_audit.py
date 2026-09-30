"""Read-only paper replay on the public recent Hyperliquid perp candles."""
from dataclasses import replace
import time

import pandas as pd

from .hyperliquid_api import info
from .strategy_lab import LabConfig, replay, validate_history
from .strategy_research import candidates


def recent_candles(coin: str) -> pd.DataFrame:
    if coin not in ("BTC", "ETH"):
        raise ValueError("Moeda não suportada.")
    now_ms = int(time.time() * 1000)
    raw = info("mainnet", {"type": "candleSnapshot", "req": {
        "coin": coin, "interval": "5m", "startTime": now_ms - 5000 * 300_000,
        "endTime": now_ms,
    }})
    if not isinstance(raw, list) or not raw:
        raise ValueError("A Hyperliquid não retornou candles.")
    frame = pd.DataFrame([{
        "open_time": pd.Timestamp(int(candle["t"]), unit="ms", tz="UTC"),
        "close_time": pd.Timestamp(int(candle["T"]), unit="ms", tz="UTC"),
        "open": float(candle["o"]), "high": float(candle["h"]),
        "low": float(candle["l"]), "close": float(candle["c"]),
        "volume": float(candle["v"]),
    } for candle in raw])
    frame = frame.loc[frame.close_time < pd.Timestamp.now(tz="UTC")]
    frame = frame.sort_values("open_time").drop_duplicates("open_time").reset_index(drop=True)
    validate_history(frame)
    return frame


def main() -> None:
    frame = recent_candles("ETH")
    strategy = next(item for item in candidates() if item.key == "breakout_retest_0")
    print(f"ETH perp Hyperliquid: {len(frame)} candles de {frame.iloc[0].open_time} a {frame.iloc[-1].close_time}")
    for leverage, margin in ((5, .25), (5, 1.), (10, 1.), (20, 1.), (40, 1.)):
        config = replace(LabConfig(), margin_fraction=margin)
        variant = replace(strategy, leverage=leverage)
        result = replay(frame, variant, config, stop=True, symbol="ETHUSDT")
        stress = replay(frame, variant, replace(config, slippage_rate=.0005),
                        stop=True, symbol="ETHUSDT")
        print(dict(leverage=leverage, margin_fraction=margin,
                   trades=result["closed_trades"], win_rate=result["win_rate"],
                   return_pct=round(result["total_return_pct"], 2),
                   drawdown_pct=round(result["max_drawdown_pct"], 2),
                   more_slippage_return_pct=round(stress["total_return_pct"], 2)))


if __name__ == "__main__":
    main()
