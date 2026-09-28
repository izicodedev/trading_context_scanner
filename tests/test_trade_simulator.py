from dataclasses import replace

import pandas as pd
import pytest

from app.trade_simulator import SimulationConfig, TradeSimulator, TradeSpec


ENTRY = pd.Timestamp("2026-01-01T00:00:00Z")


def spec(side="LONG"):
    return TradeSpec("BTCUSDT", "15m", side, 100, ENTRY,
                     99 if side == "LONG" else 101,
                     103 if side == "LONG" else 97)


def bars(*prices):
    opens = pd.date_range(ENTRY, periods=len(prices), freq="15min")
    frame = pd.DataFrame(prices, columns=["open", "high", "low", "close"])
    frame["open_time"] = opens
    frame["close_time"] = pd.date_range("2026-01-01T00:14:59.999Z", periods=len(prices), freq="15min")
    return frame


@pytest.mark.parametrize("side,prices,status,exit_price,ret", [
    ("LONG", (100, 103, 99.5, 102), "TARGET", 103, 3),
    ("LONG", (100, 102, 99, 100), "STOP", 99, -1),
    ("SHORT", (100, 100.5, 97, 98), "TARGET", 97, 3),
    ("SHORT", (100, 101, 98, 100), "STOP", 101, -1),
])
def test_exact_barrier_touches(side, prices, status, exit_price, ret):
    result = TradeSimulator().simulate(spec(side), bars(prices))
    assert (result.status, result.exit_price, result.candles_held) == (status, exit_price, 1)
    assert result.price_return_pct == pytest.approx(ret)
    assert result.exit_time_basis == "bar_close_proxy"
    assert not result.ambiguous


@pytest.mark.parametrize("side", ["LONG", "SHORT"])
@pytest.mark.parametrize("policy,status", [
    ("conservative", "STOP"), ("optimistic", "TARGET"), ("unresolved", "AMBIGUOUS"),
])
def test_ambiguous_candle(side, policy, status):
    result = TradeSimulator().simulate(spec(side), bars((100, 104, 96, 100)),
                                       SimulationConfig(10, policy))
    assert result.status == status
    assert result.ambiguous
    assert result.ambiguity_policy == policy
    if status == "AMBIGUOUS":
        assert result.exit_price is None and result.price_return_pct is None


@pytest.mark.parametrize("side,opening,status,price", [
    ("LONG", 98, "STOP", 98), ("LONG", 104, "TARGET", 103),
    ("SHORT", 102, "STOP", 102), ("SHORT", 96, "TARGET", 97),
])
def test_opening_gap_precedes_intrabar_range(side, opening, status, price):
    result = TradeSimulator().simulate(spec(side), bars((opening, 105, 95, 100)))
    assert (result.status, result.exit_price) == (status, price)
    assert result.exit_time == ENTRY and result.duration == pd.Timedelta(0)
    assert result.exit_time_basis == "open" and not result.ambiguous


def test_first_barrier_wins_and_input_is_not_mutated():
    frame = bars((100, 101, 99, 100), (100, 104, 100, 103))
    frame.index = [42, 88]
    original = frame.copy(deep=True)
    simulator = TradeSimulator()
    result = simulator.simulate(spec(), frame)
    assert result.status == "STOP" and result.candles_held == 1
    assert result == simulator.simulate(spec(), frame)
    pd.testing.assert_frame_equal(frame, original)


def test_timeout_only_after_complete_horizon():
    frame = bars((100, 101, 99.5, 100.5), (100.5, 102, 100, 101))
    result = TradeSimulator().simulate(spec(), frame, SimulationConfig(2))
    assert result.status == "TIMEOUT" and result.candles_held == 2
    assert result.exit_price == 101 and result.price_return_pct == pytest.approx(1)
    assert result.duration.value == 1799999000000
    assert result.exit_time_basis == "close"
    incomplete = TradeSimulator().simulate(spec(), frame, SimulationConfig(3))
    assert incomplete.status == "INSUFFICIENT_DATA"
    assert incomplete.exit_price is None and incomplete.exit_time is None


def test_empty_history_is_insufficient():
    result = TradeSimulator().simulate(spec(), bars())
    assert result.status == "INSUFFICIENT_DATA" and result.candles_held == 0


def test_entry_candle_is_excluded():
    frame = bars((100, 110, 90, 100), (100, 103, 99.5, 102))
    trade = replace(spec(), entry_time=frame.iloc[0].close_time)
    result = TradeSimulator().simulate(trade, frame)
    assert result.status == "TARGET" and not result.ambiguous
    assert result.candles_held == 1


@pytest.mark.parametrize("change", [
    {"side": "WAIT"}, {"entry_price": 0}, {"stop_price": float("nan")},
    {"target_price": float("inf")}, {"stop_price": 101},
    {"entry_time": pd.Timestamp("2026-01-01")}, {"symbol": ""},
])
def test_invalid_spec(change):
    with pytest.raises(ValueError):
        TradeSimulator().simulate(replace(spec(), **change), bars())


@pytest.mark.parametrize("config", [SimulationConfig(0), SimulationConfig(-1),
                                     SimulationConfig(True), SimulationConfig(1.5),
                                     SimulationConfig(1, "unknown")])
def test_invalid_config(config):
    with pytest.raises(ValueError):
        TradeSimulator().simulate(spec(), bars(), config)


def test_intrabar_is_explicitly_unsupported():
    with pytest.raises(NotImplementedError):
        TradeSimulator().simulate(spec(), bars(), SimulationConfig(10, "intrabar"))


@pytest.mark.parametrize("case", ["unordered", "duplicate", "overlap", "nan", "infinite",
                                  "negative", "ohlc", "missing", "naive", "inside"])
def test_invalid_candles(case):
    frame = bars((100, 102, 99.5, 101), (101, 102, 100, 101))
    if case == "unordered":
        frame = frame.iloc[::-1]
    elif case == "duplicate":
        frame.loc[1, "open_time"] = frame.loc[0, "open_time"]
    elif case == "overlap":
        frame.loc[0, "close_time"] = frame.loc[1, "close_time"]
    elif case in ("nan", "infinite", "negative", "ohlc"):
        frame.loc[0, "low"] = {"nan": float("nan"), "infinite": float("inf"),
                                "negative": -1, "ohlc": 101}[case]
    elif case == "missing":
        frame = frame.drop(columns="high")
    elif case == "naive":
        frame["open_time"] = frame.open_time.dt.tz_localize(None)
    elif case == "inside":
        frame.loc[0, "open_time"] = pd.Timestamp("2025-12-31T23:59:00Z")
    with pytest.raises(ValueError):
        TradeSimulator().simulate(spec(), frame)


def test_requested_btc_example_after_a_neutral_candle():
    trade = replace(spec(), entry_price=84000, stop_price=83160, target_price=86520)
    frame = bars((84000, 85000, 83500, 84500), (84500, 86520, 84000, 86000))
    result = TradeSimulator().simulate(trade, frame)
    assert result.status == "TARGET" and result.exit_price == 86520
    assert result.price_return_pct == pytest.approx(3)
    assert result.candles_held == 2


def test_short_timeout_and_timezone_normalization():
    trade = replace(spec("SHORT"), entry_time=ENTRY.tz_convert("America/Sao_Paulo"))
    result = TradeSimulator().simulate(trade, bars((100, 100.5, 98, 99)), SimulationConfig(1))
    assert result.status == "TIMEOUT"
    assert result.price_return_pct == pytest.approx(1)
    assert str(result.entry_time.tz) == "UTC"
