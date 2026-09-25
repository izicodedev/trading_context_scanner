from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .strategy import Signal


@dataclass
class PaperTrade:
    timestamp: str
    side: str
    entry_price: float
    stop: float | None
    target: float | None
    exit_price: float | None = None
    result: float | None = None
    duration: int | None = None
    mfe: float | None = None
    mae: float | None = None
    outcome: str | None = None


def simulate_trade(signal: Signal, series: pd.DataFrame, lookahead: int = 10) -> PaperTrade | None:
    if signal.side == "WAIT" or signal.entry is None:
        return None

    if series.empty or "close" not in series.columns or "close_time" not in series.columns:
        return None

    try:
        signal_time = pd.Timestamp(signal.timestamp)
    except Exception:
        signal_time = pd.Timestamp(str(signal.timestamp))

    matches = series[series["close_time"] == signal_time]
    if matches.empty:
        base_idx = len(series) - 1
    else:
        base_idx = matches.index[0]

    exit_idx = min(base_idx + lookahead, len(series) - 1)
    exit_price = float(series.iloc[exit_idx]["close"])
    result = (exit_price - signal.entry) / signal.entry if signal.entry else 0.0

    outcome = "WIN" if result > 0 else "LOSS" if result < 0 else "NEUTRAL"
    duration = max(lookahead, exit_idx - base_idx)

    price_series = series["close"].astype(float).iloc[base_idx:exit_idx + 1].tolist()
    if not price_series:
        mfe = mae = 0.0
    else:
        relative = [(p - signal.entry) / signal.entry for p in price_series]
        mfe = max(relative) if relative else 0.0
        mae = min(relative) if relative else 0.0

    return PaperTrade(
        timestamp=signal.timestamp,
        side=signal.side,
        entry_price=signal.entry,
        stop=signal.stop,
        target=signal.target,
        exit_price=exit_price,
        result=result,
        duration=duration,
        mfe=mfe,
        mae=mae,
        outcome=outcome,
    )
