from dataclasses import replace
from types import SimpleNamespace

import pandas as pd

from app import strategy_research as research
from app.strategy_lab import LabConfig, decision


def test_selection_rejects_high_accuracy_with_negative_following_return(monkeypatch):
    original_candidates = research.candidates()[:9]
    monkeypatch.setattr(research, "candidates", lambda: original_candidates)
    times = pd.date_range("2026-01-01T00:00:00Z", periods=220, freq="5min")
    frame = pd.DataFrame(dict(open_time=times, close_time=times))
    calls = []
    def replay(data, strategy, config, live_start=None, stop=False, symbol="BTCUSDT"):
        calls.append((strategy.key, len(data), live_start))
        variant = int(strategy.key[-1])
        return dict(closed_trades=20, win_rate=variant * 10 if live_start is None else 100 - variant * 10,
                    total_return_pct=variant if live_start is None else -variant,
                    max_drawdown_pct=0, net_pnl=variant + 1 if live_start is None else -variant - 1,
                    profit_factor=1.5 if live_start is None else .5)
    monkeypatch.setattr(research, "replay", replay)
    selected, report = research.select_strategies(frame, LabConfig())
    assert selected == []
    assert len(calls) == 18
    assert all(size == 154 and start is None for _, size, start in calls[::2])
    assert all(start == times[154] for _, _, start in calls[1::2])
    assert report["eligible_count"] == 0
    assert report["selection_message"]
    assert len(report["data_sha256"]) == 64
    assert all(item["win_rate"] is not None for item in report["trials"])


def test_default_selection_prefers_accuracy_among_profitable_both_periods(monkeypatch):
    pool = research.candidates()[:5]
    monkeypatch.setattr(research, "candidates", lambda: pool)
    times = pd.date_range("2026-01-01T00:00:00Z", periods=220, freq="5min")
    frame = pd.DataFrame(dict(open_time=times, close_time=times))
    rates = {pool[0].key: 90, pool[1].key: 80, pool[2].key: 70, pool[3].key: 100, pool[4].key: 95}
    counts = {pool[0].key: 20, pool[1].key: 20, pool[2].key: 20, pool[3].key: 20, pool[4].key: 2}
    def replay(data, strategy, config, live_start=None, stop=False, symbol="BTCUSDT"):
        return dict(closed_trades=counts[strategy.key], win_rate=rates[strategy.key],
                    total_return_pct=-1 if live_start is not None and strategy == pool[3] else 1,
                    max_drawdown_pct=0,
                    net_pnl=-1 if live_start is not None and strategy == pool[3] else 1,
                    profit_factor=.8 if live_start is not None and strategy == pool[3] else 1.2)
    monkeypatch.setattr(research, "replay", replay)
    selected, _ = research.select_strategies(frame, LabConfig())
    assert [item.key for item in selected] == [pool[0].key, pool[1].key, pool[2].key]


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


def test_direction_applies_to_predefined_rules():
    strategy = next(item for item in research.candidates() if item.key == "trend_carry_15")
    current = SimpleNamespace(ema21=101, ema50=100, close=102, rsi=60)
    assert decision(strategy, None, current) == "LONG"
    assert decision(replace(strategy, direction="SHORT"), None, current) is None


def test_swing_breakout_uses_prior_channel_and_long_term_trend():
    strategy = next(item for item in research.candidates() if item.key == "swing_breakout_0")
    previous = SimpleNamespace(close=99, hh48=100, ll48=90)
    current = SimpleNamespace(close=101, hh48=100, ll48=90, vol_ratio=1,
                              ema50=99, ema200=98, ema200_24=97)
    assert decision(strategy, previous, current) == "LONG"
    current.ema200_24 = 99
    assert decision(strategy, previous, current) is None


def test_new_research_families_are_not_available_to_real_execution():
    all_keys = {item.key for item in research.candidates()}
    real_keys = {item.key for item in research.real_execution_candidates()}
    assert len(all_keys) == 76
    assert len(real_keys) == 63
    assert "trend_carry_15" in real_keys
    assert "swing_breakout_0" not in real_keys
    assert "breakout_retest_0" not in real_keys
