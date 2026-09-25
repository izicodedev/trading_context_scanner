from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from .indicators import enrich


@dataclass
class ScoreComponent:
    active: bool = False
    points: int = 0
    value: float | str | None = None


@dataclass
class Signal:
    side: str
    score: int
    price: float
    entry: float | None
    stop: float | None
    target: float | None
    reasons: list[str]
    timestamp: str
    long_score: int = 0
    short_score: int = 0
    ema21: float | None = None
    ema50: float | None = None
    rsi: float | None = None
    atr: float | None = None
    vol_ratio: float | None = None
    trend_bias: str | None = None
    signal_state: str = "SIGNAL"
    setup_state: str = "UNSET"
    entry_state: str = "UNSET"
    long_components: dict[str, ScoreComponent] = field(default_factory=dict)
    short_components: dict[str, ScoreComponent] = field(default_factory=dict)


def swing_range(df, lookback=80):
    w = df.tail(lookback)
    return float(w.low.min()), float(w.high.max())

def fibonacci(df):
    lo, hi = swing_range(df)
    span = hi-lo
    return {"low": lo, "high": hi, "0.382": hi-span*.382, "0.5": hi-span*.5, "0.618": hi-span*.618, "0.786": hi-span*.786}

def liquidity(df):
    x = df.tail(4)
    prev_high = float(df.high.iloc[-6:-1].max())
    prev_low = float(df.low.iloc[-6:-1].min())
    last = x.iloc[-1]
    bearish_sweep = last.high > prev_high and last.close < prev_high
    bullish_sweep = last.low < prev_low and last.close > prev_low
    return bullish_sweep, bearish_sweep

def classify_signal_state(side: str, score: int, entry: float | None, min_score: int = 65):
    if side == "WAIT":
        return "SIGNAL", "NO_SETUP", "NO_ENTRY"
    if score >= min_score:
        return "SIGNAL", "SETUP", "ENTRY"
    return "SIGNAL", "SETUP", "NO_ENTRY"


def build_long_components(c, last, price, fib, bull_sweep, s):
    comps = {}
    if c.ema21 > c.ema50:
        comps["long_trend_ema"] = ScoreComponent(active=True, points=20, value=float(c.ema21 - c.ema50))
    else:
        comps["long_trend_ema"] = ScoreComponent(active=False, points=0, value=float(c.ema21 - c.ema50))

    if c.close > c.ema21:
        comps["long_price_above_ema"] = ScoreComponent(active=True, points=8, value=float(c.close - c.ema21))
    else:
        comps["long_price_above_ema"] = ScoreComponent(active=False, points=0, value=float(c.close - c.ema21))

    if 52 <= last.rsi <= 68:
        comps["long_rsi_favorable"] = ScoreComponent(active=True, points=12, value=float(last.rsi))
    else:
        comps["long_rsi_favorable"] = ScoreComponent(active=False, points=0, value=float(last.rsi))

    if last.rsi < 28:
        comps["long_rsi_extreme"] = ScoreComponent(active=True, points=6, value=float(last.rsi))
    else:
        comps["long_rsi_extreme"] = ScoreComponent(active=False, points=0, value=float(last.rsi))

    if last.vol_ratio >= 1.2:
        if last.close >= last.open:
            comps["long_volume_confirmation"] = ScoreComponent(active=True, points=8, value=float(last.vol_ratio))
        else:
            comps["long_volume_confirmation"] = ScoreComponent(active=False, points=0, value=float(last.vol_ratio))
    else:
        comps["long_volume_confirmation"] = ScoreComponent(active=False, points=0, value=float(last.vol_ratio) if pd.notna(last.vol_ratio) else None)

    fib_dist = abs(price-fib["0.618"]) / max(float(last.atr), 1e-9)
    if fib_dist <= 1.0 and c.ema21 > c.ema50:
        comps["long_fib"] = ScoreComponent(active=True, points=15, value=float(fib_dist))
    else:
        comps["long_fib"] = ScoreComponent(active=False, points=0, value=float(fib_dist))

    if bull_sweep:
        comps["long_liquidity_sweep"] = ScoreComponent(active=True, points=15, value=float(last.low))
    else:
        comps["long_liquidity_sweep"] = ScoreComponent(active=False, points=0, value=float(last.low))

    recent_hi = float(s.high.tail(30).max()); recent_lo = float(s.low.tail(30).min())
    if price > recent_hi * .998:
        comps["long_structure"] = ScoreComponent(active=True, points=5, value=float(recent_hi))
    else:
        comps["long_structure"] = ScoreComponent(active=False, points=0, value=float(recent_hi))
    return comps


def build_short_components(c, last, price, fib, bear_sweep, s):
    comps = {}
    if c.ema21 < c.ema50:
        comps["short_trend_ema"] = ScoreComponent(active=True, points=20, value=float(c.ema50 - c.ema21))
    else:
        comps["short_trend_ema"] = ScoreComponent(active=False, points=0, value=float(c.ema50 - c.ema21))

    if c.close < c.ema21:
        comps["short_price_below_ema"] = ScoreComponent(active=True, points=8, value=float(c.ema21 - c.close))
    else:
        comps["short_price_below_ema"] = ScoreComponent(active=False, points=0, value=float(c.ema21 - c.close))

    if 32 <= last.rsi <= 48:
        comps["short_rsi_favorable"] = ScoreComponent(active=True, points=12, value=float(last.rsi))
    else:
        comps["short_rsi_favorable"] = ScoreComponent(active=False, points=0, value=float(last.rsi))

    if last.rsi > 72:
        comps["short_rsi_extreme"] = ScoreComponent(active=True, points=6, value=float(last.rsi))
    else:
        comps["short_rsi_extreme"] = ScoreComponent(active=False, points=0, value=float(last.rsi))

    if last.vol_ratio >= 1.2:
        if last.close < last.open:
            comps["short_volume_confirmation"] = ScoreComponent(active=True, points=8, value=float(last.vol_ratio))
        else:
            comps["short_volume_confirmation"] = ScoreComponent(active=False, points=0, value=float(last.vol_ratio))
    else:
        comps["short_volume_confirmation"] = ScoreComponent(active=False, points=0, value=float(last.vol_ratio) if pd.notna(last.vol_ratio) else None)

    fib_dist = abs(price-fib["0.618"]) / max(float(last.atr), 1e-9)
    if fib_dist <= 1.0 and c.ema21 < c.ema50:
        comps["short_fib"] = ScoreComponent(active=True, points=15, value=float(fib_dist))
    else:
        comps["short_fib"] = ScoreComponent(active=False, points=0, value=float(fib_dist))

    if bear_sweep:
        comps["short_liquidity_sweep"] = ScoreComponent(active=True, points=15, value=float(last.high))
    else:
        comps["short_liquidity_sweep"] = ScoreComponent(active=False, points=0, value=float(last.high))

    recent_hi = float(s.high.tail(30).max()); recent_lo = float(s.low.tail(30).min())
    if price < recent_lo * 1.002:
        comps["short_structure"] = ScoreComponent(active=True, points=5, value=float(recent_lo))
    else:
        comps["short_structure"] = ScoreComponent(active=False, points=0, value=float(recent_lo))
    return comps


def validate_component_totals(signal: "Signal"):
    long_total = sum(component.points for component in signal.long_components.values() if component.active)
    short_total = sum(component.points for component in signal.short_components.values() if component.active)
    if long_total != signal.long_score:
        raise ValueError(f"LONG component points sum mismatch: {long_total} != {signal.long_score}")
    if short_total != signal.short_score:
        raise ValueError(f"SHORT component points sum mismatch: {short_total} != {signal.short_score}")


def analyze(context, structure, trigger, rr=2.0, atr_mult=1.2, min_score=65):
    c = enrich(context).iloc[-1]
    s = enrich(structure)
    t = enrich(trigger)
    last = t.iloc[-1]
    price = float(last.close)
    fib = fibonacci(context)
    bull_sweep, bear_sweep = liquidity(structure)
    long_components = build_long_components(c, last, price, fib, bull_sweep, s)
    short_components = build_short_components(c, last, price, fib, bear_sweep, s)
    long_score = sum(component.points for component in long_components.values() if component.active)
    short_score = sum(component.points for component in short_components.values() if component.active)
    lr, sr = [], []

    if c.ema21 > c.ema50: lr.append("1H EMA21 acima da EMA50")
    elif c.ema21 < c.ema50: sr.append("1H EMA21 abaixo da EMA50")
    if c.close > c.ema21: lr.append("1H preço acima da EMA21")
    elif c.close < c.ema21: sr.append("1H preço abaixo da EMA21")

    if 52 <= last.rsi <= 68: lr.append("RSI favorável ao pullback comprador")
    if 32 <= last.rsi <= 48: sr.append("RSI favorável ao pullback vendedor")
    if last.rsi > 72: sr.append("RSI sobrecomprado")
    if last.rsi < 28: lr.append("RSI sobrevendido")

    if last.vol_ratio >= 1.2:
        if last.close >= last.open: lr.append("volume acima da média com candle comprador")
        else: sr.append("volume acima da média com candle vendedor")

    fib_dist = abs(price-fib["0.618"]) / max(float(last.atr), 1e-9)
    if fib_dist <= 1.0:
        if c.ema21 > c.ema50: lr.append("preço próximo do Fib 0.618 em tendência de alta")
        if c.ema21 < c.ema50: sr.append("preço próximo do Fib 0.618 em tendência de baixa")

    if bull_sweep: lr.append("sweep de liquidez abaixo do fundo")
    if bear_sweep: sr.append("sweep de liquidez acima do topo")

    recent_hi = float(s.high.tail(30).max()); recent_lo = float(s.low.tail(30).min())
    if price > recent_hi * .998: lr.append("preço junto à resistência/rompimento")
    if price < recent_lo * 1.002: sr.append("preço junto ao suporte/rompimento")

    trend_bias = "LONG" if c.ema21 > c.ema50 else "SHORT" if c.ema21 < c.ema50 else "FLAT"
    side = "WAIT"; score = max(long_score, short_score); reasons=[]; entry=stop=target=None
    if long_score >= min_score and long_score > short_score + 5:
        side="LONG"; score=long_score; reasons=lr; entry=price; stop=price-max(float(last.atr)*atr_mult, price*.002); target=price+(price-stop)*rr
    elif short_score >= min_score and short_score > long_score + 5:
        side="SHORT"; score=short_score; reasons=sr; entry=price; stop=price+max(float(last.atr)*atr_mult, price*.002); target=price-(stop-price)*rr
    else:
        reasons=[f"LONG={long_score}", f"SHORT={short_score}"]
    signal_state, setup_state, entry_state = classify_signal_state(side, int(score), entry, min_score)
    signal = Signal(
        side=side,
        score=int(score),
        price=price,
        entry=entry,
        stop=stop,
        target=target,
        reasons=reasons,
        timestamp=str(last.close_time),
        long_score=long_score,
        short_score=short_score,
        ema21=float(c.ema21),
        ema50=float(c.ema50),
        rsi=float(last.rsi),
        atr=float(last.atr),
        vol_ratio=float(last.vol_ratio) if pd.notna(last.vol_ratio) else None,
        trend_bias=trend_bias,
        signal_state=signal_state,
        setup_state=setup_state,
        entry_state=entry_state,
        long_components=long_components,
        short_components=short_components,
    )
    validate_component_totals(signal)
    return signal
