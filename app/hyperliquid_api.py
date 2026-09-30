"""Authenticated, read-only Hyperliquid account connection. No order signing here."""
import json
import re
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError

import psycopg
from flask import Blueprint, jsonify, request, session

from .auth import authenticated_user
from .candle_storage import _connect
from .strategy_research import real_execution_candidates
from dataclasses import asdict
from .account_balance import trading_balance

hyperliquid_api = Blueprint("hyperliquid_api", __name__)
ENDPOINTS = {
    "testnet": "https://api.hyperliquid-testnet.xyz/info",
    "mainnet": "https://api.hyperliquid.xyz/info",
}


@hyperliquid_api.route('/api/hyperliquid/strategy', methods=['GET', 'POST'])
@authenticated_user
def strategy_configuration():
    catalog = {item.key: asdict(item) for item in real_execution_candidates()}
    try:
        with _connect() as conn:
            if request.method == 'POST':
                payload = request.get_json(silent=True)
                if not isinstance(payload, dict) or set(payload) != {'strategy_key'} or not isinstance(payload['strategy_key'], str) or payload['strategy_key'] not in catalog:
                    return jsonify(error='Selecione uma estratégia disponível.'), 400
                row = conn.execute('UPDATE hyperliquid_connections SET strategy_key=%s, updated_at=NOW() WHERE user_id=%s RETURNING strategy_key',
                                   (payload['strategy_key'], session['user_id'])).fetchone()
                if row is None:
                    return jsonify(error='Salve a conexão da conta primeiro.'), 409
            else:
                row = conn.execute('SELECT strategy_key FROM hyperliquid_connections WHERE user_id=%s', (session['user_id'],)).fetchone()
        return jsonify(selected=catalog.get(row['strategy_key']) if row else None,
                       strategies=list(catalog.values()), execution_enabled=False, active_strategy=None,
                       blockers=['Definir capital máximo, alavancagem e perda diária máxima.',
                                 'Configurar e autorizar a carteira de API.',
                                 'Implementar e validar o executor de ordens e as proteções.'])
    except (psycopg.Error, RuntimeError):
        return jsonify(error='Não foi possível carregar a configuração da estratégia.'), 503


@hyperliquid_api.post('/api/hyperliquid/activate')
@authenticated_user
def activate_strategy():
    return jsonify(error='Operação real indisponível: carteira de API, limites e executor ainda pendentes.', execution_enabled=False), 409


@hyperliquid_api.route('/api/hyperliquid/execution', methods=['GET', 'POST'])
@authenticated_user
def execution_control():
    from . import execution_service
    from .execution_engine import ExecutionBlocked
    try:
        if request.method == 'POST':
            if request.headers.get('X-IziCrypto-Setup') != '1' or not request.is_json:
                return jsonify(error='Solicitação inválida.'), 403
            payload = request.get_json(silent=True)
            if isinstance(payload, dict) and payload == {'action': 'close_position'}:
                execution_service.emergency_close(session['user_id'])
            elif isinstance(payload, dict) and set(payload) == {'active'} and type(payload['active']) is bool:
                if payload['active']:
                    execution_service.activate(session['user_id'])
                else:
                    execution_service.stop_entries(session['user_id'])
            else:
                return jsonify(error='Solicitação de execução inválida.'), 400
        return jsonify(execution_service.status(session['user_id']))
    except ExecutionBlocked as exc:
        return jsonify(error=str(exc)), 409
    except psycopg.IntegrityError:
        return jsonify(error='Já existe uma sessão gerenciando esta conta. Pare novas entradas e confira a sessão anterior.'), 409
    except Exception:
        return jsonify(error='Não foi possível verificar ou controlar a execução. Nenhuma ativação foi confirmada.'), 503


def validate_connection(payload):
    if not isinstance(payload, dict) or set(payload) != {"network", "account_address"}:
        raise ValueError("Informe somente rede e endereço público da conta. Não envie chaves privadas.")
    network = payload["network"]
    address = payload["account_address"]
    if not isinstance(network, str) or network not in ENDPOINTS:
        raise ValueError("Rede inválida.")
    if not isinstance(address, str) or not re.fullmatch(r"0x[0-9a-fA-F]{40}", address):
        raise ValueError("Informe um endereço público válido (0x e 40 caracteres hexadecimais).")
    if int(address[2:], 16) == 0:
        raise ValueError("O endereço zero não é uma conta válida.")
    return network, address.lower()


def info(network, payload):
    req = Request(ENDPOINTS[network], data=json.dumps(payload).encode(),
                  headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=10) as response:
        return json.loads(response.read(2_000_000))


def account_snapshot(network, address):
    state = info(network, {"type": "clearinghouseState", "user": address})
    orders = info(network, {"type": "openOrders", "user": address})
    spot = info(network, {"type": "spotClearinghouseState", "user": address})
    mode = info(network, {"type": "userAbstraction", "user": address})
    if not isinstance(spot, dict) or not isinstance(spot.get('balances'), list):
        raise ValueError('Resposta de saldo spot inválida.')
    if not isinstance(state, dict) or not isinstance(state.get("marginSummary"), dict) or not isinstance(orders, list):
        raise ValueError("Resposta inválida da Hyperliquid.")
    try:
        equity, available, source = trading_balance(mode, state, spot)
        operational = dict(equity=equity, available=available, source=source)
    except (ValueError, KeyError, TypeError):
        operational = None
    return dict(margin=state["marginSummary"], withdrawable=state.get("withdrawable"), spot_balances=spot['balances'], account_mode=mode, trading_balance=operational,
                positions=[item["position"] for item in state.get("assetPositions", [])],
                open_orders=orders, checked_at=datetime.now(timezone.utc).isoformat())


@hyperliquid_api.route("/api/hyperliquid/connection", methods=["GET", "POST"])
@authenticated_user
def connection():
    try:
        with _connect() as conn:
            if request.method == "POST":
                network, address = validate_connection(request.get_json(silent=True))
                conn.execute("""INSERT INTO hyperliquid_connections(user_id, network, account_address)
                    VALUES (%s,%s,%s) ON CONFLICT(user_id) DO UPDATE SET
                    agent_address=CASE WHEN hyperliquid_connections.network=EXCLUDED.network AND hyperliquid_connections.account_address=EXCLUDED.account_address THEN hyperliquid_connections.agent_address ELSE NULL END,
                    encrypted_key=CASE WHEN hyperliquid_connections.network=EXCLUDED.network AND hyperliquid_connections.account_address=EXCLUDED.account_address THEN hyperliquid_connections.encrypted_key ELSE NULL END,
                    agent_valid_until=CASE WHEN hyperliquid_connections.network=EXCLUDED.network AND hyperliquid_connections.account_address=EXCLUDED.account_address THEN hyperliquid_connections.agent_valid_until ELSE NULL END,
                    risk_limits=CASE WHEN hyperliquid_connections.network=EXCLUDED.network AND hyperliquid_connections.account_address=EXCLUDED.account_address THEN hyperliquid_connections.risk_limits ELSE NULL END,
                    network=EXCLUDED.network, account_address=EXCLUDED.account_address,
                    updated_at=NOW()""", (session["user_id"], network, address))
            row = conn.execute("SELECT network, account_address FROM hyperliquid_connections WHERE user_id=%s",
                               (session["user_id"],)).fetchone()
        return jsonify(connection=row, execution_enabled=False, mode="read_only")
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except (psycopg.Error, RuntimeError):
        return jsonify(error="Conexão indisponível. Verifique o banco e as migrations."), 503


@hyperliquid_api.get("/api/hyperliquid/account")
@authenticated_user
def account():
    try:
        with _connect() as conn:
            row = conn.execute("SELECT network, account_address FROM hyperliquid_connections WHERE user_id=%s",
                               (session["user_id"],)).fetchone()
        if row is None:
            return jsonify(error="Cadastre o endereço público da conta primeiro."), 409
        snapshot = account_snapshot(row["network"], row["account_address"])
        return jsonify(**snapshot, **row, execution_enabled=False)
    except (psycopg.Error, RuntimeError):
        return jsonify(error="Não foi possível carregar a conexão."), 503
    except URLError as exc:
        if getattr(exc.reason, "winerror", None) == 10013:
            return jsonify(error="O backend está sem permissão de acesso à rede. Reinicie o serviço com acesso à Hyperliquid autorizado."), 502
        return jsonify(error="Não foi possível conectar à Hyperliquid. Verifique a rede do servidor e tente novamente."), 502
    except (TimeoutError, ValueError, KeyError, TypeError):
        return jsonify(error="Não foi possível consultar a Hyperliquid. Tente novamente."), 502
