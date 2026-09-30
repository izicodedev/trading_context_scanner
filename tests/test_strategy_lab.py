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
    assert result["liquidations"] == 1
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


def test_breakout_retest_waits_for_retest_confirmation():
    from types import SimpleNamespace
    strategy = lab.Strategy("breakout_retest_0", "Rompimento com reteste", 5,
                            .008, 1.5, 3, 144, "")
    previous = SimpleNamespace(close=101, hh48=100, ll48=90, vol_ratio=1.3)
    current = SimpleNamespace(open=100.1, close=100.5, low=99.8, high=100.8,
                              vol_ratio=.8, ema50=99, ema200=98, ema200_24=97)
    assert lab.decision(strategy, previous, current) == "LONG"
    current.low = 100.1
    assert lab.decision(strategy, previous, current) is None


def test_breakout_retest_trailing_stop_moves_only_after_one_r_close():
    from types import SimpleNamespace
    strategy = lab.Strategy("breakout_retest_0", "Rompimento com reteste", 5,
                            .008, 1.5, 3, 144, "")
    position = dict(side="LONG", entry_price=100., initial_risk=2., stop_price=98.)
    lab.advance_stop(position, strategy, SimpleNamespace(close=101.9, atr=1.), lab.LabConfig())
    assert position["stop_price"] == 98.
    lab.advance_stop(position, strategy, SimpleNamespace(close=102.1, atr=1.), lab.LabConfig())
    assert position["stop_price"] > 100.
    lab.advance_stop(position, strategy, SimpleNamespace(close=103., atr=.5), lab.LabConfig())
    assert position["stop_price"] == 102.


def test_trailing_stop_is_not_filled_before_its_candle_closes(monkeypatch):
    frame = candles(63)
    frame.loc[61, ["open", "high", "low", "close"]] = [100, 101.1, 99.5, 101]
    frame.loc[62, ["open", "high", "low", "close"]] = [100.9, 101, 99.5, 100]
    strategy = lab.Strategy("breakout_retest_0", "Rompimento com reteste", 5,
                            .008, 1.5, 3, 144, "")
    monkeypatch.setattr(lab, "decision", lambda *args: "LONG")
    result = lab.replay(frame, strategy, lab.LabConfig())
    assert result["closed_trades"] == 1
    trade = result["recent_trades"][0]
    assert trade["candles_held"] == 3
    assert trade["status"] == "STOP"
    assert trade["stop_price"] > trade["entry_price"]


def test_full_margin_forty_times_costs_before_price_movement():
    position = dict(side="LONG", quantity=40, entry_price=100, margin=100,
                    entry_time="2026-01-01T00:00:00Z")
    result = lab.settlement(position, 100, pd.Timestamp("2026-01-01T00:05:00Z"), lab.LabConfig())
    assert result["return_on_margin_pct"] == pytest.approx(-5.2)
