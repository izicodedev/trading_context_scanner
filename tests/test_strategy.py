import csv
import os

import numpy as np, pandas as pd

from app.analysis import component_frequency
from app.evaluation import evaluate_signal
from app.paper_trading import simulate_trade
from app.storage import save
from app.strategy import analyze, classify_signal_state


def candles(n=300):
    rng=np.random.default_rng(1); close=60000+np.cumsum(rng.normal(20,100,n)); op=close-rng.normal(0,30,n)
    hi=np.maximum(op,close)+rng.uniform(10,80,n); lo=np.minimum(op,close)-rng.uniform(10,80,n)
    close_time = pd.date_range("2026-01-01", periods=n, freq="min")
    return pd.DataFrame({"open":op,"high":hi,"low":lo,"close":close,"volume":rng.uniform(10,100,n),"close_time":close_time})


def test_analyze_returns_signal():
    d=candles(); s=analyze(d,d,d); assert s.side in {"LONG","SHORT","WAIT"}; assert 0 <= s.score <= 100; assert s.long_score >= 0; assert s.short_score >= 0


def test_evaluation_tracks_horizons():
    d=candles(); s=analyze(d,d,d); ev=evaluate_signal(s, d)
    assert ev.signal_timestamp == s.timestamp
    assert ev.signal_side == s.side
    assert ev.signal_score == s.score
    assert ev.outcome in {None, "WIN", "LOSS", "NEUTRAL"}


def test_signal_classification_and_paper_trade():
    d=candles(); s=analyze(d,d,d)
    state = classify_signal_state(s.side, s.score, s.entry, 65)
    assert len(state) == 3
    if s.side != "WAIT":
        trade = simulate_trade(s, d)
        assert trade is None or trade.side == s.side


def test_component_totals_match_score_and_csv_record():
    d=candles(); s=analyze(d,d,d)
    long_total = sum(comp.points for comp in s.long_components.values() if comp.active)
    short_total = sum(comp.points for comp in s.short_components.values() if comp.active)
    assert long_total == s.long_score
    assert short_total == s.short_score

    out = "test_signal_output.csv"
    save(s, out)
    with open(out, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows
    row = rows[-1]
    assert "long_trend_ema_active" in row
    assert "long_trend_ema_points" in row
    assert "short_trend_ema_active" in row
    assert "short_trend_ema_points" in row
    assert int(row["long_score"]) == sum(int(row.get(f"{key}_points", 0) or 0) for key in [
        "long_trend_ema", "long_price_above_ema", "long_rsi_favorable", "long_rsi_extreme",
        "long_volume_confirmation", "long_fib", "long_liquidity_sweep", "long_structure"
    ] if row.get(f"{key}_active", "").lower() in {"true", "1", "yes"})
    assert int(row["short_score"]) == sum(int(row.get(f"{key}_points", 0) or 0) for key in [
        "short_trend_ema", "short_price_below_ema", "short_rsi_favorable", "short_rsi_extreme",
        "short_volume_confirmation", "short_fib", "short_liquidity_sweep", "short_structure"
    ] if row.get(f"{key}_active", "").lower() in {"true", "1", "yes"})

    counts = component_frequency(out)
    assert isinstance(counts, dict)
    os.remove(out)


def test_save_migrates_legacy_csv_without_component_columns():
    d=candles(); s=analyze(d,d,d)
    legacy = "legacy_signal_output.csv"
    with open(legacy, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "side", "score", "price", "entry", "stop", "target", "reasons"])
        writer.writeheader()
        writer.writerow({
            "timestamp": s.timestamp,
            "side": "WAIT",
            "score": "32",
            "price": str(s.price),
            "entry": "",
            "stop": "",
            "target": "",
            "reasons": "legacy",
        })

    save(s, legacy)
    with open(legacy, newline="", encoding="utf-8") as f:
        header = next(csv.reader(f))
    assert "long_trend_ema_active" in header
    assert "short_trend_ema_active" in header
    os.remove(legacy)
