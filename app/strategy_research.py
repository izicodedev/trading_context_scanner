"""Screen predefined strategies on two historical periods before paper trading."""
from dataclasses import asdict
from hashlib import sha256

from .strategy_lab import LabConfig, Strategy, replay


def candidates():
    families = [
        ("range_reclaim", "Retomada da faixa", "Varredura do extremo de 20 candles e fechamento de volta na faixa, com candle de reversão e RSI do lado oposto a 50.", [1., 1., 1.]),
        ("momentum_reset", "Retomada de momentum", "Cruzamento do RSI na direção das EMAs 21/50, com preço além da EMA21.", [50., 55., 60.]),
        ("failed_breakout", "Falha de rompimento", "Rompimento no candle anterior, retorno para dentro da faixa e confirmação de volume.", [.8, 1., 1.2]),
    ]
    output = []
    for family, name, description, thresholds in families:
        for i, (stop, rr, horizon) in enumerate(((.004, 1.5, 24), (.006, 2., 48), (.008, 2.5, 72))):
            output.append(Strategy(f"{family}_{i}", name, 5, stop, 1.5, rr, horizon,
                                   description, thresholds[i]))
    for family, name, description in (
        ("trend_carry", "Continuidade de tendência", "EMAs alinhadas, preço além da EMA21 e RSI entre 50–70 para LONG / 30–50 para SHORT."),
        ("channel_follow", "Canal direcional", "Rompimento do canal de 20 candles alinhado às EMAs 21/50."),
        ("deep_recovery", "Recuperação de extremo", "RSI cruza de volta 35 ou 65, com candle confirmando a recuperação."),
    ):
        i = 0
        for stop in (.006, .01, .015):
            for rr in (1.5, 2., 3.):
                for horizon in (72, 144):
                    output.append(Strategy(f"{family}_{i}", name, 5, stop, 1.5, rr, horizon, description))
                    i += 1
    return output


def select_strategies(frame, config: LabConfig, symbol: str = "BTCUSDT"):
    # Recent four days were already explored in earlier iterations; keep them out
    # of this expanded retrospective experiment when a month of data is available.
    excluded_recent = 1152 if len(frame) >= 6000 else 0
    if excluded_recent:
        frame = frame.iloc[:-excluded_recent]
    split = int(len(frame) * .7)
    if split <= config.warmup or len(frame) - split < 60:
        raise ValueError("Histórico insuficiente para separar descoberta e validação.")
    discovery = frame.iloc[:split]
    # Include the original warmup history, but no validation entries before the boundary.
    validation_start = frame.iloc[split].open_time
    scores = []
    for strategy in candidates():
        train = replay(discovery, strategy, config, stop=True, symbol=symbol)
        test = replay(frame, strategy, config, live_start=validation_start, stop=True, symbol=symbol)
        enough = train["closed_trades"] >= 5 and test["closed_trades"] >= 15
        qualified = (enough and train["net_pnl"] > 0 and test["net_pnl"] > 0
                     and (train["profit_factor"] or 0) > 1 and (test["profit_factor"] or 0) > 1)
        scores.append((strategy, train, test, qualified))
    # Validation is used as a selection filter, so its result is a historical
    # screen, not an untouched estimate of future performance. The forward
    # paper session is the independent observation.
    eligible = [item for item in scores if item[3]]
    eligible.sort(key=lambda item: (item[2]["win_rate"] or 0,
                                   item[2]["total_return_pct"], item[2]["closed_trades"]), reverse=True)
    chosen = eligible[:3]
    selected = [item[0] for item in chosen]
    training = [item[1] for item in chosen]
    validation = [item[2] for item in chosen]
    assessments = [dict(key=strategy.key, status="promising",
                        discovery_trades=train["closed_trades"], validation_trades=test["closed_trades"])
                   for strategy, train, test, _ in chosen]
    fingerprint = sha256(frame.to_csv(index=False).encode()).hexdigest()
    report = dict(method="70% descoberta / 30% triagem temporal; selecionar até três estratégias lucrativas nos dois períodos, ordenadas pelo acerto no segundo. O segundo período participa da seleção e não é prova independente.",
                  candidates_tested=len(scores), data_sha256=fingerprint,
                  eligible_count=len(eligible),
                  selection_message=(None if selected else
                      "Nenhuma estratégia do catálogo teve lucro líquido e amostra suficiente nos dois períodos desta moeda. A coleta continua; escolha manualmente uma hipótese experimental ou reavalie com novos dados."),
                  excluded_recent_candles=excluded_recent,
                  discovery_start=frame.iloc[0].open_time.isoformat(),
                  discovery_end=frame.iloc[split - 1].close_time.isoformat(),
                  validation_start=validation_start.isoformat(), validation_end=frame.iloc[-1].close_time.isoformat(),
                  training=training, validation=validation, assessments=assessments,
                  trials=[dict(strategy=asdict(s), discovery_return=train["total_return_pct"],
                               discovery_drawdown=train["max_drawdown_pct"],
                               win_rate=train["win_rate"], trades=train["closed_trades"],
                               validation_return=test["total_return_pct"],
                               validation_win_rate=test["win_rate"],
                               validation_trades=test["closed_trades"], qualified=qualified)
                          for s, train, test, qualified in scores])
    return selected, report
