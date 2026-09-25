from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from .indicators import enrich

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

def analyze(context, structure, trigger, rr=2.0, atr_mult=1.2, min_score=65):
    c = enrich(context).iloc[-1]
    s = enrich(structure)
    t = enrich(trigger)
    last = t.iloc[-1]
    price = float(last.close)
    fib = fibonacci(context)
    bull_sweep, bear_sweep = liquidity(structure)
    long_score = short_score = 0
    lr, sr = [], []

    if c.ema21 > c.ema50: long_score += 20; lr.append("1H EMA21 acima da EMA50")
    elif c.ema21 < c.ema50: short_score += 20; sr.append("1H EMA21 abaixo da EMA50")
    if c.close > c.ema21: long_score += 8; lr.append("1H preço acima da EMA21")
    elif c.close < c.ema21: short_score += 8; sr.append("1H preço abaixo da EMA21")

    if 52 <= last.rsi <= 68: long_score += 12; lr.append("RSI favorável ao pullback comprador")
    if 32 <= last.rsi <= 48: short_score += 12; sr.append("RSI favorável ao pullback vendedor")
    if last.rsi > 72: short_score += 6; sr.append("RSI sobrecomprado")
    if last.rsi < 28: long_score += 6; lr.append("RSI sobrevendido")

    if last.vol_ratio >= 1.2:
        if last.close >= last.open: long_score += 8; lr.append("volume acima da média com candle comprador")
        else: short_score += 8; sr.append("volume acima da média com candle vendedor")

    fib_dist = abs(price-fib["0.618"]) / max(float(last.atr), 1e-9)
    if fib_dist <= 1.0:
        if c.ema21 > c.ema50: long_score += 15; lr.append("preço próximo do Fib 0.618 em tendência de alta")
        if c.ema21 < c.ema50: short_score += 15; sr.append("preço próximo do Fib 0.618 em tendência de baixa")

    if bull_sweep: long_score += 15; lr.append("sweep de liquidez abaixo do fundo")
    if bear_sweep: short_score += 15; sr.append("sweep de liquidez acima do topo")

    recent_hi = float(s.high.tail(30).max()); recent_lo = float(s.low.tail(30).min())
    if price > recent_hi * .998: long_score += 5; lr.append("preço junto à resistência/rompimento")
    if price < recent_lo * 1.002: short_score += 5; sr.append("preço junto ao suporte/rompimento")

    side = "WAIT"; score = max(long_score, short_score); reasons=[]; entry=stop=target=None
    if long_score >= min_score and long_score > short_score + 5:
        side="LONG"; score=long_score; reasons=lr; entry=price; stop=price-max(float(last.atr)*atr_mult, price*.002); target=price+(price-stop)*rr
    elif short_score >= min_score and short_score > long_score + 5:
        side="SHORT"; score=short_score; reasons=sr; entry=price; stop=price+max(float(last.atr)*atr_mult, price*.002); target=price-(stop-price)*rr
    else:
        reasons=[f"LONG={long_score}", f"SHORT={short_score}"]
    return Signal(side, int(score), price, entry, stop, target, reasons, str(last.close_time))
