"""Read-only audit of strategy candidates across discovery, screen and recent holdout."""
from argparse import ArgumentParser
from dataclasses import replace
from datetime import timedelta

import pandas as pd

from .candle_storage import _connect
from .lab_service import _history
from .strategy_lab import LabConfig, replay
from .strategy_research import candidates
from .symbols import validate_symbol


def audit(symbol: str, family: str = "", direction: str = "BOTH", days: int = 30,
          leverage: int | None = None, margin_fraction: float = .25) -> list[dict]:
    validate_symbol(symbol)
    if direction not in ("BOTH", "LONG", "SHORT"):
        raise ValueError("Direção inválida.")
    if days not in (30, 90):
        raise ValueError("Escolha 30 ou 90 dias.")
    if leverage is not None and leverage not in (5, 10, 20, 40):
        raise ValueError("Escolha alavancagem 5, 10, 20 ou 40.")
    if margin_fraction not in (.25, 1.):
        raise ValueError("Escolha fração da margem 0,25 ou 1.")
    with _connect() as conn:
        if days == 30:
            frame = _history(conn, symbol=symbol)
        else:
            start = pd.Timestamp.now(tz="UTC").floor("5min") - timedelta(days=90)
            frame = _history(conn, start=start, symbol=symbol)
    if days == 30:
        if len(frame) < 6000:
            raise ValueError("A auditoria exige pelo menos 6.000 candles contínuos de 5 minutos.")
        historical = frame.iloc[:-1152]
        split = int(len(historical) * .7)
        discovery = historical.iloc[:split]
        screen_frame = historical
        screen_start = historical.iloc[split].open_time
        holdout_frame = frame
        holdout_start = frame.iloc[-1152].open_time
    else:
        if len(frame) < 25000:
            raise ValueError("A auditoria de 90 dias exige histórico contínuo completo.")
        split = len(frame) // 3
        discovery = frame.iloc[:split]
        # Keep 1,000 prior bars for EMA200/ATR warm-up, with no entries before the boundary.
        screen_frame = frame.iloc[split - 1000:split * 2]
        screen_start = frame.iloc[split].open_time
        holdout_frame = frame.iloc[split * 2 - 1000:]
        holdout_start = frame.iloc[split * 2].open_time
    config = replace(LabConfig(), margin_fraction=margin_fraction)
    # The final block is diagnostic only. Once inspected, it is no longer a
    # fresh holdout for later design iterations.
    results = []
    for strategy in candidates():
        if family and not strategy.key.startswith(family):
            continue
        strategy = replace(strategy, direction=direction,
                           leverage=leverage if leverage is not None else strategy.leverage)
        train = replay(discovery, strategy, config, stop=True, symbol=symbol)
        screen = replay(screen_frame, strategy, config, live_start=screen_start, stop=True, symbol=symbol)
        holdout = replay(holdout_frame, strategy, config, live_start=holdout_start, stop=True, symbol=symbol)
        higher_cost = replay(holdout_frame, strategy, replace(config, slippage_rate=.0005),
                             live_start=holdout_start, stop=True, symbol=symbol)
        qualified = (train["closed_trades"] >= 5 and screen["closed_trades"] >= 15
                     and train["net_pnl"] > 0 and screen["net_pnl"] > 0
                     and (train["profit_factor"] or 0) > 1
                     and (screen["profit_factor"] or 0) > 1)
        results.append(dict(key=strategy.key, qualified=qualified,
                            discovery=(round(train["total_return_pct"], 2), train["closed_trades"]),
                            screen=(round(screen["total_return_pct"], 2), screen["closed_trades"]),
                            holdout=(round(holdout["total_return_pct"], 2), holdout["closed_trades"]),
                            holdout_drawdown=round(holdout["max_drawdown_pct"], 2),
                            holdout_more_slippage=round(higher_cost["total_return_pct"], 2)))
    return results


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", choices=("BTCUSDT", "ETHUSDT"), required=True)
    parser.add_argument("--family", default="", help="Optional strategy-key prefix")
    parser.add_argument("--direction", choices=("BOTH", "LONG", "SHORT"), default="BOTH")
    parser.add_argument("--days", type=int, choices=(30, 90), default=30)
    parser.add_argument("--leverage", type=int, choices=(5, 10, 20, 40))
    parser.add_argument("--margin-fraction", type=float, choices=(.25, 1.), default=.25)
    args = parser.parse_args()
    rows = audit(args.symbol, args.family, args.direction, args.days,
                 args.leverage, args.margin_fraction)
    for row in sorted(rows, key=lambda item: item["screen"][0], reverse=True):
        print(f"{row['key']:26} approved={str(row['qualified']):5} "
              f"discovery={row['discovery']} screen={row['screen']} "
              f"holdout={row['holdout']} holdout_drawdown={row['holdout_drawdown']}% "
              f"holdout_more_slippage={row['holdout_more_slippage']}")


if __name__ == "__main__":
    main()
