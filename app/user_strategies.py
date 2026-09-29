"""User-owned, declarative strategies for paper simulation only."""
from dataclasses import asdict
import math
from uuid import uuid4

from psycopg.types.json import Jsonb

from .candle_storage import _connect
from .strategy_lab import Strategy
from .strategy_research import candidates

RULES = {
    "ema_trend": "Preço em relação à EMA21",
    "channel_breakout": "Rompimento do canal de 20 candles",
    "rsi_recovery": "RSI volta da região extrema",
}
TRIGGERS = {
    "channel_breakout": "Rompimento do canal (20 candles)",
    "rsi_recovery": "RSI cruza o limite de recuperação",
    "ema_cross": "Preço cruza a EMA21",
    "ema_pullback": "Toque e retorno pela EMA21",
    "liquidity_sweep": "Varredura e retorno ao canal",
    "failed_breakout": "Rompimento anterior falha",
}
FILTERS = {
    "ema_alignment": "EMA21 alinhada à EMA50",
    "price_ema21": "Preço do lado da EMA21",
    "rsi_band": "RSI dentro da faixa",
    "volume": "Volume acima do mínimo",
    "candle_color": "Candle na direção da entrada",
}
MAX_SELECTED = 12


def _number(data, key, minimum, maximum):
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"Informe {key} como número.")
    value = float(value)
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{key} deve ficar entre {minimum} e {maximum}.")
    return value


def validate_definition(data):
    legacy_fields = {"name", "entry_rule", "direction", "ema_filter", "volume_min",
              "rsi_lower", "rsi_upper", "leverage", "stop_pct", "atr_multiple",
              "reward_risk", "max_candles"}
    builder_fields = {"name", "entry_rule", "direction", "entry_triggers", "trigger_mode",
                      "entry_filters", "volume_min", "rsi_lower", "rsi_upper", "leverage",
                      "stop_pct", "atr_multiple", "reward_risk", "max_candles"}
    if not isinstance(data, dict) or set(data) not in (legacy_fields, builder_fields):
        raise ValueError("Preencha todos os campos da estratégia.")
    name = data["name"]
    if not isinstance(name, str) or not 3 <= len(name.strip()) <= 60:
        raise ValueError("O nome deve ter de 3 a 60 caracteres.")
    name = name.strip()
    rule = data["entry_rule"]
    direction = data["direction"]
    builder = set(data) == builder_fields
    if not isinstance(rule, str) or rule not in (("rule_builder",) if builder else RULES) or direction not in ("BOTH", "LONG", "SHORT"):
        raise ValueError("Regra ou direção inválida.")
    if not builder and type(data["ema_filter"]) is not bool:
        raise ValueError("Filtro de tendência inválido.")
    if builder:
        triggers = data["entry_triggers"]
        filters = data["entry_filters"]
        if (not isinstance(triggers, list) or not 1 <= len(triggers) <= 6
                or any(type(code) is not str or code not in TRIGGERS for code in triggers)
                or len(triggers) != len(set(triggers))):
            raise ValueError("Escolha de 1 a 6 gatilhos distintos.")
        if (not isinstance(filters, list) or len(filters) > 5
                or any(type(code) is not str or code not in FILTERS for code in filters)
                or len(filters) != len(set(filters))):
            raise ValueError("Filtros inválidos ou repetidos.")
        if data["trigger_mode"] not in ("ANY", "ALL"):
            raise ValueError("Combinação de gatilhos inválida.")
    volume = _number(data, "volume_min", 0, 5)
    lower = _number(data, "rsi_lower", 1, 79)
    upper = _number(data, "rsi_upper", 21, 99)
    if builder and "rsi_recovery" in triggers and lower > 49:
        raise ValueError("O limite de recuperação do RSI na compra deve ficar até 49.")
    if (not builder or "rsi_band" in filters) and lower >= upper:
        raise ValueError("O RSI mínimo deve ser menor que o máximo.")
    if builder and "volume" in filters and volume == 0:
        raise ValueError("Informe volume mínimo maior que zero para usar esse filtro.")
    leverage = _number(data, "leverage", 1, 20)
    horizon = _number(data, "max_candles", 1, 288)
    if not leverage.is_integer() or not horizon.is_integer():
        raise ValueError("Alavancagem e duração devem ser números inteiros.")
    stop_pct = _number(data, "stop_pct", .1, 10)
    atr = _number(data, "atr_multiple", .1, 5)
    reward = _number(data, "reward_risk", .5, 10)
    if builder:
        joiner = " E " if data["trigger_mode"] == "ALL" else " OU "
        description = f"Gatilhos: {joiner.join(TRIGGERS[code] for code in triggers)}. "
        description += "Filtros: " + (", ".join(FILTERS[code] for code in filters) if filters else "nenhum")
        if "rsi_band" in filters:
            description += f" (LONG {lower:g}–{upper:g}; SHORT {100-upper:g}–{100-lower:g})"
        if "rsi_recovery" in triggers:
            description += f"; recuperação RSI {lower:g} / {100-lower:g}"
        if "volume" in filters:
            description += f"; volume ≥ {volume:g}×"
        description += f". Direção {direction}."
    else:
        description = (f"{RULES[rule]}; {'EMAs alinhadas' if data['ema_filter'] else 'sem filtro de tendência'}; "
                       f"RSI LONG {lower:g}–{upper:g} / SHORT {100-upper:g}–{100-lower:g}; "
                       f"volume mínimo {volume:g}×; direção {direction}.")
    return Strategy(key="custom_" + uuid4().hex, name=name, leverage=int(leverage),
                    stop_floor=stop_pct / 100, atr_multiple=atr,
                    reward_risk=reward, max_candles=int(horizon), description=description,
                    entry_rule=rule, direction=direction, ema_filter=data.get("ema_filter", False),
                    volume_min=volume, rsi_lower=lower, rsi_upper=upper,
                    entry_triggers=triggers if builder else None,
                    trigger_mode=data["trigger_mode"] if builder else "ANY",
                    entry_filters=filters if builder else None)


def catalog(user_id, symbol="BTCUSDT"):
    with _connect() as conn:
        custom = conn.execute("SELECT definition FROM user_simulation_strategies WHERE user_id=%s ORDER BY created_at, strategy_key", (user_id,)).fetchall()
        selection = conn.execute("SELECT strategy_keys FROM user_simulation_selection WHERE user_id=%s AND symbol=%s", (user_id, symbol)).fetchone()
    return dict(strategies=[asdict(s) for s in candidates()] + [row["definition"] for row in custom],
                selected_keys=selection["strategy_keys"] if selection else [])


def create(user_id, data):
    strategy = validate_definition(data)
    with _connect() as conn:
        conn.execute("SELECT id FROM users WHERE id=%s FOR UPDATE", (user_id,))
        count = conn.execute("SELECT count(*) FROM user_simulation_strategies WHERE user_id=%s", (user_id,)).fetchone()[0]
        if count >= 30:
            raise ValueError("Limite de 30 estratégias próprias por usuário.")
        conn.execute("INSERT INTO user_simulation_strategies(strategy_key,user_id,definition) VALUES(%s,%s,%s)",
                     (strategy.key, user_id, Jsonb(asdict(strategy))))
    return asdict(strategy)


def choose(user_id, keys, symbol="BTCUSDT"):
    if not isinstance(keys, list) or len(keys) > MAX_SELECTED or any(not isinstance(k, str) for k in keys) or len(set(keys)) != len(keys):
        raise ValueError(f"Selecione até {MAX_SELECTED} estratégias distintas.")
    with _connect() as conn:
        conn.execute("SELECT id FROM users WHERE id=%s FOR UPDATE", (user_id,))
        custom = conn.execute("SELECT strategy_key FROM user_simulation_strategies WHERE user_id=%s", (user_id,)).fetchall()
        allowed = {s.key for s in candidates()} | {row["strategy_key"] for row in custom}
        if any(key not in allowed for key in keys):
            raise ValueError("A seleção contém uma estratégia desconhecida.")
        conn.execute("""INSERT INTO user_simulation_selection(user_id,symbol,strategy_keys)
            VALUES(%s,%s,%s) ON CONFLICT(user_id,symbol) DO UPDATE SET
            strategy_keys=EXCLUDED.strategy_keys,updated_at=NOW()""", (user_id, symbol, Jsonb(keys)))
    return keys


def selected_for_session(conn, user_id, symbol="BTCUSDT"):
    selection = conn.execute("SELECT strategy_keys FROM user_simulation_selection WHERE user_id=%s AND symbol=%s", (user_id, symbol)).fetchone()
    keys = selection["strategy_keys"] if selection else []
    if not keys:
        return []
    custom = conn.execute("SELECT definition FROM user_simulation_strategies WHERE user_id=%s", (user_id,)).fetchall()
    catalog = {s.key: s for s in candidates()}
    catalog.update({row["definition"]["key"]: Strategy(**row["definition"]) for row in custom})
    if any(key not in catalog for key in keys):
        raise ValueError("Uma estratégia selecionada não está mais disponível.")
    return [catalog[key] for key in keys]
