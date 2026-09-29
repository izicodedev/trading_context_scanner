"""Authenticated HTTP adapter for the price simulator."""
from dataclasses import asdict

import pandas as pd
import psycopg
from flask import Blueprint, jsonify, request, session

from .auth import authenticated_user
from .trade_simulator import SimulationConfig, TradeSimulator, TradeSpec, _validate_spec
from .candle_storage import available_datasets, load_candles, MARKET_SOURCE
from . import lab_service
from . import user_strategies
from .symbols import DEFAULT_SYMBOL, validate_symbol

simulation_api = Blueprint("simulation_api", __name__)


@simulation_api.get("/api/simulator/strategies")
@authenticated_user
def strategy_catalog():
    try:
        symbol = validate_symbol(request.args.get("symbol", DEFAULT_SYMBOL))
        return jsonify(user_strategies.catalog(session["user_id"], symbol))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except (psycopg.Error, RuntimeError):
        return jsonify(error="Catálogo indisponível. Verifique o banco e as migrations."), 503


@simulation_api.post("/api/simulator/strategies")
@authenticated_user
def create_strategy():
    if request.content_length is not None and request.content_length > 4096:
        return jsonify(error="A estratégia excede o limite de 4 KB."), 413
    try:
        strategy = user_strategies.create(session["user_id"], request.get_json(silent=True))
        return jsonify(strategy), 201
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except (psycopg.Error, RuntimeError):
        return jsonify(error="Não foi possível salvar a estratégia."), 503


@simulation_api.post("/api/simulator/selection")
@authenticated_user
def select_simulation_strategies():
    payload = request.get_json(silent=True)
    try:
        if not isinstance(payload, dict) or not set(payload).issubset({"strategy_keys", "symbol"}) or "strategy_keys" not in payload:
            raise ValueError("Envie a lista de estratégias selecionadas.")
        symbol = validate_symbol(payload.get("symbol", DEFAULT_SYMBOL))
        keys = user_strategies.choose(session["user_id"], payload["strategy_keys"], symbol)
        return jsonify(selected_keys=keys)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except (psycopg.Error, RuntimeError):
        return jsonify(error="Não foi possível salvar a seleção."), 503


@simulation_api.get("/api/simulator/live")
@authenticated_user
def live_status():
    try:
        symbol = validate_symbol(request.args.get("symbol", DEFAULT_SYMBOL))
        return jsonify(lab_service.status(session["user_id"], symbol))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except (psycopg.Error, RuntimeError):
        return jsonify(error="Simulação indisponível. Verifique o banco e as migrations."), 503


@simulation_api.post("/api/simulator/live")
@authenticated_user
def live_control():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or type(payload.get("active")) is not bool:
        return jsonify(error="Informe active como true ou false."), 400
    try:
        symbol = validate_symbol(payload.get("symbol", DEFAULT_SYMBOL))
        if payload["active"]:
            lab_service.start(session["user_id"], symbol)
        else:
            lab_service.advance(session["user_id"], stopping=True, symbol=symbol)
        return jsonify(lab_service.status(session["user_id"], symbol))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except (psycopg.Error, RuntimeError):
        return jsonify(error="Não foi possível atualizar a simulação. Verifique o banco."), 503


@simulation_api.get("/api/simulator/datasets")
@authenticated_user
def datasets():
    try:
        rows = available_datasets()
        for row in rows:
            for field in ("start_time", "end_time"):
                row[field] = row[field].isoformat()
        return jsonify(rows)
    except (psycopg.Error, RuntimeError):
        return jsonify(error="Histórico indisponível. Verifique o banco e aplique as migrations."), 503


@simulation_api.post("/api/simulator")
@authenticated_user
def simulate():
    if request.content_length is not None and request.content_length > 2_000_000:
        return jsonify(error="O limite é 2 MB por simulação."), 413
    payload = request.get_json(silent=True)
    try:
        if not isinstance(payload, dict):
            raise ValueError("Envie um objeto JSON.")
        trade = payload["trade"]
        if not isinstance(trade, dict):
            raise ValueError("Informe os parâmetros da operação.")
        spec = TradeSpec(**trade)
        config = SimulationConfig(**payload.get("config", {}))
        _validate_spec(spec, config)
        if config.max_candles > 5000:
            raise ValueError("O horizonte máximo é 5.000 candles.")
        data_source = payload.get("data_source", "database")
        if data_source == "database":
            frame = load_candles(spec.symbol, spec.timeframe, spec.entry_time,
                                 config.max_candles, payload.get("market_source", MARKET_SOURCE))
        elif data_source == "manual":
            rows = payload.get("candles")
            if not isinstance(rows, list) or not 1 <= len(rows) <= 5000:
                raise ValueError("Informe de 1 a 5.000 candles.")
            if not all(isinstance(row, dict) for row in rows):
                raise ValueError("Cada candle deve ser um objeto.")
            frame = pd.DataFrame(rows)
        else:
            raise ValueError("Fonte de dados inválida.")
        result = TradeSimulator().simulate(spec, frame, config)
    except (ValueError, TypeError, KeyError, OverflowError, NotImplementedError) as exc:
        return jsonify(error=f"Dados inválidos: {exc}"), 400
    except (psycopg.Error, RuntimeError):
        return jsonify(error="Histórico indisponível. Verifique o banco e aplique as migrations."), 503
    response = asdict(result)
    response["entry_time"] = result.entry_time.isoformat()
    response["exit_time"] = result.exit_time.isoformat() if result.exit_time is not None else None
    response["duration_seconds"] = result.duration.total_seconds() if result.duration is not None else None
    del response["duration"]
    response["data_source"] = data_source
    response["candles_loaded"] = len(frame)
    return jsonify(response)
