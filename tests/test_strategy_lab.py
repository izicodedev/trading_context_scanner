from dataclasses import replace

import pandas as pd
import pytest

from app import strategy_lab as lab


def candles(n=75):
    times = pd.date_range("2026-01-01T00:00:00Z", periods=n, freq="5min")
    return pd.DataFrame({"open_time": times,
                         "close_time": pd.date_range("2026-01-01T00:04:59.999Z", periods=n, freq="5min"),
                         "open": 100., "high": 100.1, "low": 99.9, "close": 100., "volume": 10.})


def test_costs_on_notional_and_hourly_funding_sign():
    p = dict(side="LONG", quantity=10, entry_price=100, margin=100,
             entry_time="2026-01-01T00:30:00Z")
    costs = lab.settlement(p, 103, pd.Timestamp("2026-01-01T02:00:00Z"), lab.LabConfig())
    assert costs["gross_pnl"] == 30
    assert costs["fees"] == pytest.approx(2030 * .00045)
    assert costs["slippage"] == pytest.approx(2030 * .0002)
    assert costs["funding"] == pytest.approx(1000 * .0000125 * 2)
    assert costs["net_pnl"] == pytest.approx(30 - 2030 * .00065 - .025)
    short = lab.settlement(dict(p, side="SHORT"), 97, pd.Timestamp("2026-01-01T02:00:00Z"), lab.LabConfig())
    assert short["gross_pnl"] == 30 and short["funding"] == pytest.approx(-.025)


def test_causal_next_open_and_no_overlapping_positions(monkeypatch):
    frame = candles()
    monkeypatch.setattr(lab, "decision", lambda *args: "LONG")
    strategy = replace(lab.STRATEGIES[0], max_candles=3)
    result = lab.replay(frame, strategy, lab.LabConfig())
    assert result["closed_trades"] == 5
    assert result["wins"] == 0 and result["losses"] == 5
    trades = result["recent_trades"]
    assert trades[0]["entry_time"] == frame.iloc[60].open_time.isoformat()
    assert all(pd.Timestamp(a["exit_time"]) < pd.Timestamp(b["entry_time"]) for a, b in zip(trades, trades[1:]))
    assert result["max_drawdown_pct"] > 0


def test_both_barriers_resolve_conservatively(monkeypatch):
    frame = candles(61)
    frame.loc[60, ["high", "low"]] = [110, 90]
    monkeypatch.setattr(lab, "decision", lambda *args: "LONG")
    result = lab.replay(frame, lab.STRATEGIES[0], lab.LabConfig())
    trade = result["recent_trades"][0]
    assert trade["status"] == "STOP" and trade["ambiguous"]
    assert trade["net_pnl"] < 0


def test_live_excludes_historical_entries_and_stop_closes_position(monkeypatch):
    frame = candles()
    monkeypatch.setattr(lab, "decision", lambda *args: "LONG")
    started = frame.iloc[70].open_time
    result = lab.replay(frame, lab.STRATEGIES[0], lab.LabConfig(), live_start=started)
    assert result["closed_trades"] == 0
    assert result["open_position"]["entry_time"] == started.isoformat()
    closed = lab.replay(frame, lab.STRATEGIES[0], lab.LabConfig(), live_start=started, stop=True)
    assert closed["open_position"] is None and closed["closed_trades"] == 1
    assert closed["recent_trades"][0]["status"] == "STOPPED"


def test_replay_deterministic_and_future_does_not_change_past(monkeypatch):
    frame = candles(90)
    monkeypatch.setattr(lab, "decision", lambda *args: "LONG")
    strategy = replace(lab.STRATEGIES[0], max_candles=3)
    first = lab.replay(frame.iloc[:75], strategy, lab.LabConfig())
    assert first == lab.replay(frame.iloc[:75], strategy, lab.LabConfig())
    frame.loc[80:, "high"] = 150
    longer = lab.replay(frame, strategy, lab.LabConfig())
    assert longer["recent_trades"][:5] == first["recent_trades"]


def test_liquidation_gap_is_not_a_profitable_target(monkeypatch):
    frame = candles(62)
    frame.loc[61, ["open", "high", "low", "close"]] = [50, 55, 45, 50]
    monkeypatch.setattr(lab, "decision", lambda *args: "LONG")
    result = lab.replay(frame, lab.STRATEGIES[2], lab.LabConfig())
    assert result["recent_trades"][0]["status"] == "LIQUIDATION"
    assert result["net_pnl"] < 0


def test_history_requires_contiguous_closed_candles():
    with pytest.raises(ValueError):
        lab.validate_history(candles(60))
    with pytest.raises(ValueError):
        lab.validate_history(candles().drop(index=65))


def test_direction_rules():
    from types import SimpleNamespace
    prev = SimpleNamespace(rsi=28)
    bar = SimpleNamespace(ema21=100, ema50=99, low=99, high=103, close=102,
                          open=100, rsi=55, vol_ratio=1.5, hh20=101, ll20=98)
    assert lab.decision(lab.STRATEGIES[0], prev, bar) == "LONG"
    assert lab.decision(lab.STRATEGIES[1], prev, bar) == "LONG"
    assert lab.decision(lab.STRATEGIES[2], prev, bar) == "LONG"
    bar.vol_ratio = .5
    assert lab.decision(lab.STRATEGIES[1], prev, bar) is None
