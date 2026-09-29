"""Causal, deterministic strategy replay on closed candles; no exchange orders."""
from dataclasses import asdict, dataclass
from zoneinfo import ZoneInfo

import pandas as pd

from .indicators import enrich
from .trade_simulator import TradeSpec, resolve_barriers, _validated_candles


@dataclass(frozen=True)
class LabConfig:
    initial_equity: float = 1000.0
    margin_fraction: float = .25
    fee_rate: float = .00045
    slippage_rate: float = .0002
    hourly_funding_rate: float = .0000125
    maintenance_margin_rate: float = .005
    daily_goal_pct: float = 5.0
    warmup: int = 60
    version: str = "4"


@dataclass(frozen=True)
class Strategy:
    key: str
    name: str
    leverage: int
    stop_floor: float
    atr_multiple: float
    reward_risk: float
    max_candles: int
    description: str
    threshold: float = 1.0
    entry_rule: str | None = None
    direction: str = "BOTH"
    ema_filter: bool = True
    volume_min: float = 0.0
    rsi_lower: float = 40.0
    rsi_upper: float = 70.0
    entry_triggers: list[str] | None = None
    trigger_mode: str = "ANY"
    entry_filters: list[str] | None = None


STRATEGIES = (
    Strategy("pullback", "Pullback de tendência", 5, .006, 1.5, 2, 36,
             "EMA21 acima/abaixo da EMA50; toque e recuperação da EMA21; RSI 45–65 / 35–55."),
    Strategy("breakout", "Rompimento com volume", 10, .005, 1.3, 2, 24,
             "Fechamento rompe a máxima/mínima dos 20 candles anteriores; volume ≥ 1,2× a média."),
    Strategy("reversal", "Reversão de excesso", 15, .004, 1.2, 2, 18,
             "RSI anterior ≤ 30 / ≥ 70; candle de recuperação e RSI voltando do extremo."),
)


def decision(strategy: Strategy, previous, current) -> str | None:
    if strategy.entry_rule == "rule_builder":
        for side in ("LONG", "SHORT"):
            if strategy.direction not in ("BOTH", side):
                continue
            trigger_results = [_custom_trigger(code, side, previous, current, strategy)
                               for code in strategy.entry_triggers or []]
            triggered = (all(trigger_results) if strategy.trigger_mode == "ALL" else any(trigger_results))
            if triggered and all(_custom_filter(code, side, current, strategy)
                                 for code in strategy.entry_filters or []):
                return side
        return None
    if strategy.entry_rule:
        long = short = False
        if strategy.entry_rule == "ema_trend":
            long, short = current.close > current.ema21, current.close < current.ema21
        elif strategy.entry_rule == "channel_breakout":
            long, short = current.close > current.hh20, current.close < current.ll20
        elif strategy.entry_rule == "rsi_recovery":
            long = previous.rsi < strategy.rsi_lower <= current.rsi and current.close > current.open
            short = previous.rsi > 100 - strategy.rsi_lower >= current.rsi and current.close < current.open
        else:
            return None
        if strategy.ema_filter:
            long = long and current.ema21 > current.ema50
            short = short and current.ema21 < current.ema50
        long = long and strategy.rsi_lower <= current.rsi <= strategy.rsi_upper
        short = short and 100 - strategy.rsi_upper <= current.rsi <= 100 - strategy.rsi_lower
        if current.vol_ratio < strategy.volume_min:
            return None
        if long and strategy.direction in ("BOTH", "LONG"):
            return "LONG"
        if short and strategy.direction in ("BOTH", "SHORT"):
            return "SHORT"
        return None
    if strategy.key.startswith("trend_carry"):
        if current.ema21 > current.ema50 and current.close > current.ema21 and 50 <= current.rsi <= 70:
            return "LONG"
        if current.ema21 < current.ema50 and current.close < current.ema21 and 30 <= current.rsi <= 50:
            return "SHORT"
    elif strategy.key.startswith("channel_follow"):
        if current.close > current.hh20 and current.ema21 > current.ema50:
            return "LONG"
        if current.close < current.ll20 and current.ema21 < current.ema50:
            return "SHORT"
    elif strategy.key.startswith("deep_recovery"):
        if previous.rsi < 35 <= current.rsi and current.close > current.open:
            return "LONG"
        if previous.rsi > 65 >= current.rsi and current.close < current.open:
            return "SHORT"
    elif strategy.key.startswith("range_reclaim"):
        if current.low < current.ll20 < current.close and current.close > current.open and current.rsi < 50:
            return "LONG"
        if current.high > current.hh20 > current.close and current.close < current.open and current.rsi > 50:
            return "SHORT"
    elif strategy.key.startswith("momentum_reset"):
        if current.ema21 > current.ema50 and previous.rsi < strategy.threshold <= current.rsi and current.close > current.ema21:
            return "LONG"
        if current.ema21 < current.ema50 and previous.rsi > 100 - strategy.threshold >= current.rsi and current.close < current.ema21:
            return "SHORT"
    elif strategy.key.startswith("failed_breakout"):
        if previous.close > previous.hh20 and current.close < previous.hh20 and current.vol_ratio >= strategy.threshold:
            return "SHORT"
        if previous.close < previous.ll20 and current.close > previous.ll20 and current.vol_ratio >= strategy.threshold:
            return "LONG"
    elif strategy.key == "pullback":
        if current.ema21 > current.ema50 and current.low <= current.ema21 < current.close and 45 <= current.rsi <= 65:
            return "LONG"
        if current.ema21 < current.ema50 and current.high >= current.ema21 > current.close and 35 <= current.rsi <= 55:
            return "SHORT"
    elif strategy.key == "breakout" and current.vol_ratio >= 1.2:
        if current.close > current.hh20:
            return "LONG"
        if current.close < current.ll20:
            return "SHORT"
    elif strategy.key == "reversal":
        if previous.rsi <= 30 < current.rsi and current.close > current.open:
            return "LONG"
        if previous.rsi >= 70 > current.rsi and current.close < current.open:
            return "SHORT"
    return None


def _custom_trigger(code: str, side: str, previous, current, strategy: Strategy) -> bool:
    long = side == "LONG"
    if code == "channel_breakout":
        return current.close > current.hh20 if long else current.close < current.ll20
    if code == "rsi_recovery":
        return (previous.rsi < strategy.rsi_lower <= current.rsi if long else
                previous.rsi > 100 - strategy.rsi_lower >= current.rsi)
    if code == "ema_cross":
        return (previous.close <= previous.ema21 and current.close > current.ema21 if long else
                previous.close >= previous.ema21 and current.close < current.ema21)
    if code == "ema_pullback":
        return (current.low <= current.ema21 < current.close if long else
                current.high >= current.ema21 > current.close)
    if code == "liquidity_sweep":
        return (current.low < current.ll20 < current.close if long else
                current.high > current.hh20 > current.close)
    if code == "failed_breakout":
        return (previous.close < previous.ll20 and current.close > previous.ll20 if long else
                previous.close > previous.hh20 and current.close < previous.hh20)
    return False


def _custom_filter(code: str, side: str, current, strategy: Strategy) -> bool:
    long = side == "LONG"
    if code == "ema_alignment":
        return current.ema21 > current.ema50 if long else current.ema21 < current.ema50
    if code == "price_ema21":
        return current.close > current.ema21 if long else current.close < current.ema21
    if code == "rsi_band":
        return (strategy.rsi_lower <= current.rsi <= strategy.rsi_upper if long else
                100 - strategy.rsi_upper <= current.rsi <= 100 - strategy.rsi_lower)
    if code == "volume":
        return current.vol_ratio >= strategy.volume_min
    if code == "candle_color":
        return current.close > current.open if long else current.close < current.open
    return False


def settlement(position: dict, price: float, time: pd.Timestamp, config: LabConfig) -> dict:
    """Costs on notionals; funding at UTC hour boundaries, with side sign."""
    sign = 1 if position["side"] == "LONG" else -1
    quantity = position["quantity"]
    gross = sign * quantity * (price - position["entry_price"])
    entry_notional = quantity * position["entry_price"]
    exit_notional = quantity * price
    entry_time = pd.Timestamp(position["entry_time"])
    hours = max(0, time.value // 3_600_000_000_000 - entry_time.value // 3_600_000_000_000)
    fees = (entry_notional + exit_notional) * config.fee_rate
    slippage = (entry_notional + exit_notional) * config.slippage_rate
    funding = sign * entry_notional * config.hourly_funding_rate * hours
    net = gross - fees - slippage - funding
    return dict(gross_pnl=gross, fees=fees, slippage=slippage, funding=funding,
                net_pnl=net, return_on_margin_pct=net / position["margin"] * 100)


def open_position(strategy: Strategy, side: str, bar, signal, balance: float, config: LabConfig) -> dict:
    price = float(bar.open)
    sign = 1 if side == "LONG" else -1
    distance = max(price * strategy.stop_floor, float(signal.atr) * strategy.atr_multiple)
    margin = balance * config.margin_fraction
    mmr = config.maintenance_margin_rate
    liquidation = price * (1 - sign / strategy.leverage) / (1 - sign * mmr)
    return dict(side=side, entry_price=price, entry_time=bar.open_time.isoformat(),
                stop_price=price - sign * distance, target_price=price + sign * distance * strategy.reward_risk,
                liquidation_price=liquidation, margin=margin,
                quantity=margin * strategy.leverage / price, candles_held=0)


def exit_event(position: dict, strategy: Strategy, bar, config: LabConfig, symbol: str = "BTCUSDT"):
    long = position["side"] == "LONG"
    # Approximate isolated margin liquidation takes precedence when the opening gaps beyond it.
    liquidation_gap = bar.open <= position["liquidation_price"] if long else bar.open >= position["liquidation_price"]
    if liquidation_gap:
        return "LIQUIDATION", float(bar.open), bar.open_time, False
    risk_barrier = max(position["stop_price"], position["liquidation_price"]) if long else min(position["stop_price"], position["liquidation_price"])
    spec = TradeSpec(symbol, "5m", position["side"], position["entry_price"],
                     pd.Timestamp(position["entry_time"]), risk_barrier, position["target_price"])
    event = resolve_barriers(spec, bar)
    if event:
        status, price, time, ambiguous, _ = event
        status = "LIQUIDATION" if status == "STOP" and risk_barrier == position["liquidation_price"] else status
        return status, price, time, ambiguous
    if position["candles_held"] >= strategy.max_candles:
        return "TIMEOUT", float(bar.close), bar.close_time, False
    return None


def summarize(trades: list[dict], curve: list[dict], position: dict | None,
              balance: float, config: LabConfig) -> dict:
    pnls = [trade["net_pnl"] for trade in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    peak = config.initial_equity
    drawdown = 0.0
    streak = max_streak = 0
    for p in pnls:
        streak = streak + 1 if p < 0 else 0
        max_streak = max(max_streak, streak)
    days = {}
    for point in curve:
        peak = max(peak, point["equity"])
        drawdown = max(drawdown, (peak - point["equity"]) / peak * 100)
        day = pd.Timestamp(point["time"]).tz_convert(ZoneInfo("America/Sao_Paulo")).date().isoformat()
        days[day] = point["equity"]
    daily = []
    previous = config.initial_equity
    for index, (day, equity) in enumerate(days.items()):
        daily.append(dict(day=day, return_pct=(equity / previous - 1) * 100 if previous > 0 else None,
                          partial=index == 0 or index == len(days) - 1))
        previous = equity
    equity = curve[-1]["equity"] if curve else balance
    return dict(closed_trades=len(trades), wins=len(wins), losses=len(losses),
                win_rate=len(wins) / len(trades) * 100 if trades else None,
                net_pnl=sum(pnls), equity=equity, balance=balance,
                total_return_pct=(equity / config.initial_equity - 1) * 100,
                expectancy=sum(pnls) / len(pnls) if pnls else None,
                profit_factor=sum(wins) / abs(sum(losses)) if losses else None,
                max_drawdown_pct=drawdown, max_consecutive_losses=max_streak,
                fees=sum(t["fees"] for t in trades), funding=sum(t["funding"] for t in trades),
                slippage=sum(t["slippage"] for t in trades),
                daily=daily, open_position=position, recent_trades=trades[-15:],
                curve=curve[::max(1, len(curve) // 120)][-120:])


def replay(frame: pd.DataFrame, strategy: Strategy, config: LabConfig,
           live_start: pd.Timestamp | None = None, stop: bool = False,
           symbol: str = "BTCUSDT") -> dict:
    """One position per strategy. Decide on bar i-1, enter at bar i open."""
    if not frame.empty:
        _validated_candles(frame, pd.Timestamp(frame.iloc[0].open_time))
    data = enrich(frame.reset_index(drop=True))
    balance = config.initial_equity
    position = None
    trades, curve = [], []
    rows = list(data.itertuples(index=False))
    for index in range(config.warmup, len(rows)):
        bar, signal = rows[index], rows[index - 1]
        if live_start is not None and bar.open_time < live_start:
            continue
        if position is None and balance > 0:
            side = decision(strategy, rows[index - 2], signal)
            if side:
                position = open_position(strategy, side, bar, signal, balance, config)
        if position is not None:
            position["candles_held"] += 1
            event = exit_event(position, strategy, bar, config, symbol)
            if event is None and stop and index == len(rows) - 1:
                event = ("STOPPED" if live_start is not None else "SAMPLE_END", float(bar.close), bar.close_time, False)
            if event:
                status, price, timestamp, ambiguous = event
                costs = settlement(position, price, timestamp, config)
                balance += costs["net_pnl"]
                trades.append(dict(**position, **costs, status=status, exit_price=price,
                                   exit_time=timestamp.isoformat(), ambiguous=ambiguous))
                position = None
        marked = balance
        if position is not None:
            marked += settlement(position, float(bar.close), bar.close_time, config)["net_pnl"]
        curve.append(dict(time=bar.close_time.isoformat(), equity=marked))
    if position is not None:
        position = dict(position, estimated_net_pnl=settlement(position, float(rows[-1].close), rows[-1].close_time, config)["net_pnl"])
    summary = summarize(trades, curve, position, balance, config)
    summary["strategy"] = asdict(strategy)
    return summary


def validate_history(frame: pd.DataFrame):
    if len(frame) < 61:
        raise ValueError("São necessários pelo menos 61 candles fechados de 5m.")
    if not frame.open_time.diff().iloc[1:].map(lambda delta: delta.value == 300_000_000_000).all():
        raise ValueError("Histórico 5m com lacunas. Importe os candles ausentes para continuar.")
