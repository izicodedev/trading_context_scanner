"""Small predefined search: select on discovery only, then report held-out results."""
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


def select_strategies(frame, config: LabConfig):
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
        result = replay(discovery, strategy, config, stop=True)
        rank = (result["closed_trades"] >= 5,
                result["total_return_pct"] - .5 * result["max_drawdown_pct"],
                result["closed_trades"])
        scores.append((strategy, result, rank))
    selected, training, validation, assessments = [], [], [], []
    families = sorted({item[0].key.rsplit("_", 1)[0] for item in scores})
    family_winners = [max((item for item in scores if item[0].key.rsplit("_", 1)[0] == family), key=lambda item: item[2]) for family in families]
    for strategy, train, _ in sorted(family_winners, key=lambda item: item[2], reverse=True)[:3]:
        selected.append(strategy)
        test = replay(frame, strategy, config, live_start=validation_start, stop=True)
        training.append(train)
        validation.append(test)
        enough = train["closed_trades"] >= 5 and test["closed_trades"] >= 15
        positive = test["net_pnl"] > 0 and (test["profit_factor"] or 0) > 1
        assessments.append(dict(key=strategy.key,
                                status="insufficient_sample" if not enough else "promising" if positive else "not_confirmed",
                                discovery_trades=train["closed_trades"], validation_trades=test["closed_trades"]))
    fingerprint = sha256(frame.to_csv(index=False).encode()).hexdigest()
    report = dict(method="70% descoberta / 30% validação temporal, seleção apenas na descoberta",
                  candidates_tested=len(scores), data_sha256=fingerprint,
                  excluded_recent_candles=excluded_recent,
                  discovery_start=frame.iloc[0].open_time.isoformat(),
                  discovery_end=frame.iloc[split - 1].close_time.isoformat(),
                  validation_start=validation_start.isoformat(), validation_end=frame.iloc[-1].close_time.isoformat(),
                  training=training, validation=validation, assessments=assessments,
                  trials=[dict(strategy=asdict(s), discovery_return=r["total_return_pct"],
                               discovery_drawdown=r["max_drawdown_pct"], trades=r["closed_trades"]) for s, r, _ in scores])
    return selected, report
