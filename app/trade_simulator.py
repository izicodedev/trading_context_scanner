"""Deterministic price-barrier simulation, independent of signals and exchanges."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal

import pandas as pd

Side = Literal["LONG", "SHORT"]
Policy = Literal["conservative", "optimistic", "unresolved"]
Status = Literal["TARGET", "STOP", "AMBIGUOUS", "TIMEOUT", "INSUFFICIENT_DATA"]


@dataclass(frozen=True)
class TradeSpec:
    symbol: str
    timeframe: str
    side: Side
    entry_price: float
    entry_time: pd.Timestamp
    stop_price: float
    target_price: float


@dataclass(frozen=True)
class SimulationConfig:
    max_candles: int = 10
    ambiguity_policy: Policy = "conservative"


@dataclass(frozen=True)
class TradeResult:
    status: Status
    entry_price: float
    exit_price: float | None
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp | None
    price_return_pct: float | None
    duration: pd.Timedelta | None
    candles_held: int
    ambiguous: bool
    ambiguity_policy: Policy
    exit_time_basis: Literal["open", "close", "bar_close_proxy"] | None


def _utc(value: object) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp) or timestamp.tzinfo is None:
        raise ValueError("Timestamps must be valid and timezone-aware")
    return timestamp.tz_convert("UTC")


def _validate_spec(spec: TradeSpec, config: SimulationConfig) -> pd.Timestamp:
    if not spec.symbol or not spec.timeframe:
        raise ValueError("symbol and timeframe are required")
    if spec.side not in ("LONG", "SHORT"):
        raise ValueError("side must be LONG or SHORT")
    if any(not isfinite(p) or p <= 0 for p in
           (spec.entry_price, spec.stop_price, spec.target_price)):
        raise ValueError("Prices must be finite and positive")
    ordered = (spec.stop_price < spec.entry_price < spec.target_price
               if spec.side == "LONG" else
               spec.target_price < spec.entry_price < spec.stop_price)
    if not ordered:
        raise ValueError("Stop and target must bracket entry in the side's direction")
    if type(config.max_candles) is not int or config.max_candles <= 0:
        raise ValueError("max_candles must be a positive integer")
    if config.ambiguity_policy == "intrabar":
        raise NotImplementedError("Intrabar resolution requires lower-timeframe data")
    if config.ambiguity_policy not in ("conservative", "optimistic", "unresolved"):
        raise ValueError("Unknown ambiguity policy")
    return _utc(spec.entry_time)


def _validated_candles(candles: pd.DataFrame, entry_time: pd.Timestamp) -> pd.DataFrame:
    required = ["open_time", "close_time", "open", "high", "low", "close"]
    if not candles.columns.is_unique or not set(required).issubset(candles.columns):
        raise ValueError("Candles require unique open_time, close_time and OHLC columns")
    frame = candles.loc[:, required].copy().reset_index(drop=True)
    for column in ("open_time", "close_time"):
        frame[column] = pd.to_datetime([_utc(value) for value in frame[column]], utc=True)
    if not frame.open_time.is_monotonic_increasing or frame.open_time.duplicated().any():
        raise ValueError("Candles must be ordered with unique opening times")
    if (frame.close_time <= frame.open_time).any():
        raise ValueError("Each close_time must follow open_time")
    if (frame.open_time < frame.close_time.shift()).any():
        raise ValueError("Candle intervals must not overlap")
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if not frame[column].map(lambda value: isfinite(value) and value > 0).all():
            raise ValueError("OHLC prices must be finite and positive")
    if ((frame.low > frame[["open", "close"]].min(axis=1)) |
            (frame.high < frame[["open", "close"]].max(axis=1)) |
            (frame.low > frame.high)).any():
        raise ValueError("Inconsistent OHLC prices")
    if ((frame.open_time < entry_time) & (frame.close_time > entry_time)).any():
        raise ValueError("Entry inside a candle requires intrabar data")
    return frame.loc[frame.open_time >= entry_time]


def resolve_barriers(spec: TradeSpec, bar, policy: Policy = "conservative"):
    """Resolve a validated candle; shared by single-trade and continuous replay."""
    open_stop = bar.open <= spec.stop_price if spec.side == "LONG" else bar.open >= spec.stop_price
    open_target = bar.open >= spec.target_price if spec.side == "LONG" else bar.open <= spec.target_price
    if open_stop:
        return "STOP", float(bar.open), bar.open_time, False, "open"
    if open_target:
        return "TARGET", spec.target_price, bar.open_time, False, "open"
    stop = bar.low <= spec.stop_price if spec.side == "LONG" else bar.high >= spec.stop_price
    target = bar.high >= spec.target_price if spec.side == "LONG" else bar.low <= spec.target_price
    ambiguous = bool(stop and target)
    if ambiguous and policy == "unresolved":
        return "AMBIGUOUS", None, bar.close_time, True, "bar_close_proxy"
    if stop or target:
        stop_first = stop and (not target or policy == "conservative")
        return ("STOP" if stop_first else "TARGET",
                spec.stop_price if stop_first else spec.target_price,
                bar.close_time, ambiguous, "bar_close_proxy")
    return None


class TradeSimulator:
    def simulate(self, spec: TradeSpec, candles: pd.DataFrame,
                 config: SimulationConfig = SimulationConfig()) -> TradeResult:
        entry_time = _validate_spec(spec, config)
        future = _validated_candles(candles, entry_time).head(config.max_candles)

        def result(status: Status, held: int, price: float | None = None,
                   time: pd.Timestamp | None = None, ambiguous: bool = False,
                   basis: Literal["open", "close", "bar_close_proxy"] | None = None) -> TradeResult:
            direction = 1 if spec.side == "LONG" else -1
            return TradeResult(
                status, spec.entry_price, price, entry_time, time,
                direction * (price / spec.entry_price - 1) * 100 if price is not None else None,
                time - entry_time if time is not None else None,
                held, ambiguous, config.ambiguity_policy, basis,
            )

        for held, bar in enumerate(future.itertuples(index=False), start=1):
            event = resolve_barriers(spec, bar, config.ambiguity_policy)
            if event:
                status, price, time, ambiguous, basis = event
                return result(status, held, price, time, ambiguous, basis)
        if len(future) == config.max_candles:
            last = future.iloc[-1]
            return result("TIMEOUT", len(future), float(last.close), last.close_time, basis="close")
        return result("INSUFFICIENT_DATA", len(future))
