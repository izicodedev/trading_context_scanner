from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from .strategy import Signal


@dataclass
class SignalEvaluation:
    signal_timestamp: str
    signal_side: str
    signal_score: int
    price: float
    long_score: int
    short_score: int
    trend_bias: str | None
    price_after_1: float | None = None
    price_after_3: float | None = None
    price_after_5: float | None = None
    price_after_10: float | None = None
    ret_1: float | None = None
    ret_3: float | None = None
    ret_5: float | None = None
    ret_10: float | None = None
    mfe: float | None = None
    mae: float | None = None
    max_favorable_move: float | None = None
    max_adverse_move: float | None = None
    outcome: str | None = None


def evaluate_signal(signal: Signal, series: pd.DataFrame, horizons=(1, 3, 5, 10)) -> SignalEvaluation:
    if series.empty:
        return SignalEvaluation(
            signal_timestamp=signal.timestamp,
            signal_side=signal.side,
            signal_score=signal.score,
            price=signal.price,
            long_score=signal.long_score,
            short_score=signal.short_score,
            trend_bias=signal.trend_bias,
        )

    try:
        signal_time = pd.Timestamp(signal.timestamp)
    except Exception:
        signal_time = pd.Timestamp(str(signal.timestamp))

    if "close" not in series.columns:
        return SignalEvaluation(
            signal_timestamp=signal.timestamp,
            signal_side=signal.side,
            signal_score=signal.score,
            price=signal.price,
            long_score=signal.long_score,
            short_score=signal.short_score,
            trend_bias=signal.trend_bias,
        )

    idx = series.index[series["close_time"] == signal_time]
    if len(idx) == 0 and len(series) > 0:
        idx = [len(series) - 1]
    target_idx = int(idx[0]) if len(idx) > 0 else len(series) - 1

    future_prices = []
    for horizon in horizons:
        future_index = target_idx + horizon
        if future_index < len(series):
            future_prices.append((horizon, float(series.iloc[future_index]["close"])))
        else:
            future_prices.append((horizon, None))

    horizon_map = {h: p for h, p in future_prices if p is not None}
    returns = {}
    for horizon, future_price in horizon_map.items():
        returns[horizon] = (future_price - signal.price) / signal.price if signal.price else 0.0

    price_after_1 = horizon_map.get(1)
    price_after_3 = horizon_map.get(3)
    price_after_5 = horizon_map.get(5)
    price_after_10 = horizon_map.get(10)

    ret_1 = returns.get(1)
    ret_3 = returns.get(3)
    ret_5 = returns.get(5)
    ret_10 = returns.get(10)

    move_values = [v for v in returns.values() if v is not None]
    mfe = max(move_values) if move_values else None
    mae = min(move_values) if move_values else None

    outcome = None
    if move_values:
        if ret_10 is not None:
            outcome = "WIN" if ret_10 > 0 else "LOSS" if ret_10 < 0 else "NEUTRAL"
        elif ret_5 is not None:
            outcome = "WIN" if ret_5 > 0 else "LOSS" if ret_5 < 0 else "NEUTRAL"
        elif ret_3 is not None:
            outcome = "WIN" if ret_3 > 0 else "LOSS" if ret_3 < 0 else "NEUTRAL"
        elif ret_1 is not None:
            outcome = "WIN" if ret_1 > 0 else "LOSS" if ret_1 < 0 else "NEUTRAL"

    return SignalEvaluation(
        signal_timestamp=signal.timestamp,
        signal_side=signal.side,
        signal_score=signal.score,
        price=signal.price,
        long_score=signal.long_score,
        short_score=signal.short_score,
        trend_bias=signal.trend_bias,
        price_after_1=price_after_1,
        price_after_3=price_after_3,
        price_after_5=price_after_5,
        price_after_10=price_after_10,
        ret_1=ret_1,
        ret_3=ret_3,
        ret_5=ret_5,
        ret_10=ret_10,
        mfe=mfe,
        mae=mae,
        max_favorable_move=mfe,
        max_adverse_move=mae,
        outcome=outcome,
    )
