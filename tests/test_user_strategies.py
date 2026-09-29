from dataclasses import asdict
from types import SimpleNamespace

import pytest

from app import user_strategies
from app.strategy_lab import decision


def example(**changes):
    return dict(name="Canal com RSI", entry_rule="channel_breakout", direction="BOTH",
                ema_filter=True, volume_min=1.2, rsi_lower=40, rsi_upper=70,
                leverage=5, stop_pct=1.5, atr_multiple=1.5,
                reward_risk=2, max_candles=144) | changes


def builder(**changes):
    return dict(name="Sinais combinados", entry_rule="rule_builder", direction="BOTH",
                entry_triggers=["channel_breakout"], trigger_mode="ANY", entry_filters=[],
                volume_min=1.2, rsi_lower=40, rsi_upper=70, leverage=5,
                stop_pct=1.5, atr_multiple=1.5, reward_risk=2, max_candles=144) | changes


def bars():
    previous = SimpleNamespace(open=99, close=99, high=104, low=95, ema21=100,
                               ema50=99, hh20=104, ll20=95, rsi=35, vol_ratio=1)
    current = SimpleNamespace(open=100, close=102, high=103, low=99, ema21=100,
                              ema50=99, hh20=104, ll20=95, rsi=45, vol_ratio=1.3)
    return previous, current


def test_custom_rule_uses_configured_filters_and_direction():
    strategy = user_strategies.validate_definition(example())
    assert strategy.key.startswith("custom_")
    previous = SimpleNamespace(rsi=35)
    bar = SimpleNamespace(open=101, close=105, ema21=103, ema50=102,
                          hh20=104, ll20=95, rsi=58, vol_ratio=1.3)
    assert decision(strategy, previous, bar) == "LONG"
    bar.vol_ratio = 1.1
    assert decision(strategy, previous, bar) is None
    bar.vol_ratio = 1.3
    bar.ema50 = 104
    assert decision(strategy, previous, bar) is None
    assert decision(user_strategies.validate_definition(example(ema_filter=False)), previous, bar) == "LONG"
    assert decision(user_strategies.validate_definition(example(direction="SHORT", ema_filter=False)), previous, bar) is None


@pytest.mark.parametrize("changes", [
    {"entry_rule": "python"}, {"entry_rule": []}, {"direction": "ALL"},
    {"rsi_lower": 75, "rsi_upper": 60}, {"leverage": 100},
    {"stop_pct": 0}, {"max_candles": 1.5}, {"volume_min": float("nan")},
    {"ema_filter": "true"},
])
def test_invalid_custom_rules_are_rejected(changes):
    with pytest.raises(ValueError):
        user_strategies.validate_definition(example(**changes))


def test_custom_strategy_is_reconstructed_from_saved_definition():
    strategy = user_strategies.validate_definition(example())
    from app.strategy_lab import Strategy
    assert Strategy(**asdict(strategy)) == strategy


def test_saved_selection_resolves_only_builtin_and_user_owned_definitions():
    custom = user_strategies.validate_definition(example())
    builtin = user_strategies.candidates()[0]
    class Connection:
        def execute(self, query, params):
            assert params == (7, "BTCUSDT") if "user_simulation_selection" in query else params == (7,)
            rows = ([{"strategy_keys": [custom.key, builtin.key]}]
                    if "user_simulation_selection" in query
                    else [{"definition": asdict(custom)}])
            return SimpleNamespace(fetchone=lambda: rows[0], fetchall=lambda: rows)
    assert user_strategies.selected_for_session(Connection(), 7) == [custom, builtin]


@pytest.mark.parametrize("trigger,previous_changes,current_changes,side", [
    ("channel_breakout", {}, {"close": 105}, "LONG"),
    ("ema_cross", {}, {}, "LONG"),
    ("ema_pullback", {}, {}, "LONG"),
    ("rsi_recovery", {}, {}, "LONG"),
    ("liquidity_sweep", {}, {"low": 94, "close": 100}, "LONG"),
    ("failed_breakout", {"close": 94}, {"close": 100}, "LONG"),
    ("channel_breakout", {}, {"close": 94}, "SHORT"),
    ("ema_cross", {"close": 101}, {"close": 98}, "SHORT"),
    ("ema_pullback", {}, {"high": 101, "close": 98}, "SHORT"),
    ("rsi_recovery", {"rsi": 65}, {"rsi": 55, "close": 98}, "SHORT"),
    ("liquidity_sweep", {}, {"high": 105, "close": 100}, "SHORT"),
    ("failed_breakout", {"close": 105}, {"close": 100}, "SHORT"),
])
def test_builder_triggers_are_directional(trigger, previous_changes, current_changes, side):
    previous, current = bars()
    for key, value in previous_changes.items(): setattr(previous, key, value)
    for key, value in current_changes.items(): setattr(current, key, value)
    strategy = user_strategies.validate_definition(builder(entry_triggers=[trigger], direction=side))
    assert decision(strategy, previous, current) == side


def test_builder_combines_any_all_and_filters():
    previous, current = bars()
    current.close = 105
    any_strategy = user_strategies.validate_definition(builder(
        entry_triggers=["channel_breakout", "ema_cross"], trigger_mode="ANY",
        entry_filters=["ema_alignment", "price_ema21", "rsi_band", "volume", "candle_color"]))
    assert decision(any_strategy, previous, current) == "LONG"
    previous.close = 101  # no EMA cross, but the channel still breaks
    assert decision(any_strategy, previous, current) == "LONG"
    all_strategy = user_strategies.validate_definition(builder(
        entry_triggers=["channel_breakout", "ema_cross"], trigger_mode="ALL"))
    assert decision(all_strategy, previous, current) is None
    previous.close = 99
    assert decision(all_strategy, previous, current) == "LONG"
    current.vol_ratio = 1.1
    assert decision(any_strategy, previous, current) is None


@pytest.mark.parametrize("changes", [
    {"entry_triggers": []}, {"entry_triggers": ["ema_cross", "ema_cross"]},
    {"entry_triggers": ["python"]}, {"entry_triggers": "ema_cross"},
    {"entry_filters": ["volume", "volume"]}, {"entry_filters": ["custom_code"]},
    {"trigger_mode": "XOR"}, {"entry_rule": "ema_trend"},
    {"entry_triggers": ["rsi_recovery"], "rsi_lower": 60},
    {"entry_filters": ["volume"], "volume_min": 0},
])
def test_builder_rejects_unsupported_or_duplicate_rules(changes):
    with pytest.raises(ValueError):
        user_strategies.validate_definition(builder(**changes))


def test_builder_survives_saved_json_definition():
    from app.strategy_lab import Strategy
    strategy = user_strategies.validate_definition(builder(entry_triggers=["ema_cross", "ema_pullback"],
                                                          entry_filters=["rsi_band", "volume"]))
    assert Strategy(**asdict(strategy)) == strategy
