from types import SimpleNamespace

import pandas as pd

from app import strategy_research as research
from app.strategy_lab import LabConfig, decision


def test_selection_never_uses_validation_return(monkeypatch):
    original_candidates = research.candidates()[:9]
    monkeypatch.setattr(research, "candidates", lambda: original_candidates)
    times = pd.date_range("2026-01-01T00:00:00Z", periods=220, freq="5min")
    frame = pd.DataFrame(dict(open_time=times, close_time=times))
    calls = []
    def replay(data, strategy, config, live_start=None, stop=False):
        calls.append((strategy.key, len(data), live_start))
        variant = int(strategy.key[-1])
        return dict(closed_trades=20, total_return_pct=variant if live_start is None else -100 * variant,
                    max_drawdown_pct=0, net_pnl=variant if live_start is None else -100 * variant,
                    profit_factor=.5)
    monkeypatch.setattr(research, "replay", replay)
    selected, report = research.select_strategies(frame, LabConfig())
    assert all(strategy.key.endswith("_2") for strategy in selected)
    assert all(strategy.leverage == 5 for strategy in selected)
    assert len(calls) == 12
    assert all(size == 154 and start is None for _, size, start in calls[:9])
    assert all(start == times[154] for _, _, start in calls[9:])
    assert all(item["status"] == "not_confirmed" for item in report["assessments"])
    assert len(report["data_sha256"]) == 64


def test_new_rules_use_observed_signal_and_prior_bar():
    pool = research.candidates()
    previous = SimpleNamespace(rsi=49, close=105, hh20=104, ll20=98)
    current = SimpleNamespace(low=97, high=103, ll20=98, hh20=104, close=100, open=99,
                              rsi=45, ema21=99, ema50=98, vol_ratio=1.3)
    assert decision(pool[0], previous, current) == "LONG"
    current.rsi = 55
    assert decision(pool[3], previous, current) == "LONG"
    assert decision(pool[6], previous, current) == "SHORT"
    current.vol_ratio = .1
    assert decision(pool[6], previous, current) is None
