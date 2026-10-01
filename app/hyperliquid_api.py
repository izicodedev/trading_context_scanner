"""Authenticated, read-only Hyperliquid account connection. No order signing here."""
import json
import math
import re
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError

import psycopg
from psycopg.types.json import Jsonb
from flask import Blueprint, current_app, jsonify, request, session

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
SUPPORTED_BOT_MARKETS = ("BTC", "ETH")


def _bot_market_catalog(network):
    if network not in ENDPOINTS:
        raise ValueError("Rede inválida para consultar os mercados.")
    market_meta = info(network, {"type": "meta"})
    universe = market_meta.get("universe") if isinstance(market_meta, dict) else None
    if not isinstance(universe, list):
        raise ValueError("A Hyperliquid retornou uma lista de mercados inválida.")
    available = {
        item.get("name")
        for item in universe
        if isinstance(item, dict) and not item.get("isDelisted")
    }
    return [
        {"symbol": symbol, "label": f"{symbol} / USDC"}
        for symbol in SUPPORTED_BOT_MARKETS
        if symbol in available
    ]


def _validate_bot_market(network, market):
    if not isinstance(market, str) or market not in SUPPORTED_BOT_MARKETS:
        raise ValueError("Selecione BTC ou ETH para o mercado do robô.")
    available_markets = {item["symbol"] for item in _bot_market_catalog(network)}
    if market not in available_markets:
        raise ValueError(f"O mercado {market} não está disponível para operação nesta rede.")


@hyperliquid_api.after_request
def prevent_sensitive_response_caching(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


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


def _strategy_name(strategy_key):
    if not strategy_key:
        return "Estratégia não definida"
    item = next((entry for entry in real_execution_candidates() if entry.key == strategy_key), None)
    return getattr(item, "name", strategy_key) if item else strategy_key


def _positive_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def _bot_run_payload(row):
    if not row.get("run_id"):
        return None
    return {
        "id": row.get("run_id"),
        "active": row.get("run_active"),
        "managing": row.get("run_managing"),
        "state": row.get("run_state") or {},
        "heartbeat": row.get("run_heartbeat"),
        "created_at": row.get("run_created_at"),
        "last_order_at": row.get("last_order_at"),
    }


def _build_bot_payload(row):
    from .hyperliquid_bot_service import get_bot_runtime_state
    from .execution_service import enabled

    run = _bot_run_payload(row)
    runtime = get_bot_runtime_state(row, run)
    run_is_active = bool(run and run.get("active") and run.get("managing"))
    status = row.get("status") or "stopped"
    if run_is_active:
        status = "running"
    elif status == "running":
        status = "error"

    position = runtime["position"]
    pnl = runtime["pnl"]
    balance = runtime["balance"]
    initial_bankroll = row.get("capital_reserved")
    current_bankroll = (
        max(0.0, float(initial_bankroll) + float(pnl["bot_total"]))
        if initial_bankroll is not None and pnl["bot_total"] is not None
        else None
    )
    risk_limits = row.get("risk_limits") or {}
    can_resume = bool(run and run.get("managing") and status == "paused")
    start_blocker = None
    if not enabled(row.get("network")):
        start_blocker = 'Execução nesta rede ainda não foi liberada no servidor.'
    elif not row.get("agent_address") or not row.get("encrypted_key"):
        start_blocker = 'Cadastre a chave privada da API deste robô.'
    elif run and run.get("managing") and not can_resume:
        start_blocker = 'A sessão anterior ainda está gerenciando uma posição.'
    elif not can_resume and not any(item.key == row.get("strategy_key") for item in real_execution_candidates()):
        start_blocker = 'Selecione uma estratégia disponível.'
    elif runtime["health"]["reason"] == "subaccount_not_found":
        start_blocker = (
            'A subconta cadastrada não foi encontrada nesta wallet principal. '
            'Confirme a wallet principal ou selecione uma subconta criada por ela.'
        )
    elif not can_resume and (
        initial_bankroll is None or initial_bankroll <= 0
        or current_bankroll is None or current_bankroll <= 0
    ):
        start_blocker = 'Banca ou histórico de PnL indisponível.'
    elif not can_resume and not _positive_number(risk_limits.get('daily_loss_usdc')):
        start_blocker = 'Configure um limite de perda diária maior que zero.'
    elif not can_resume and row.get('sizing_mode') == 'fixed' and (
        not _positive_number(risk_limits.get('margin_per_trade_usdc'))
    ):
        start_blocker = 'Configure o valor fixo por entrada.'
    return {
        "id": row["id"],
        "name": row["name"],
        "market": row.get("market") or row.get("coin"),
        "wallet": row.get("master_address"),
        "subaccount": row.get("account_address"),
        "subaccount_name": row.get("subaccount_name"),
        "account_address": row.get("account_address"),
        "network": row.get("network"),
        "strategy": {
            "key": row.get("strategy_key"),
            "name": row.get("strategy_name") or _strategy_name(row.get("strategy_key")),
            "config": row.get("strategy_config") or {},
        },
        "sizing_mode": row.get("sizing_mode"),
        "risk_limits": row.get("risk_limits") or {},
        "api_credential": {
            "configured": bool(row.get("agent_address") and row.get("encrypted_key")),
            "valid_until": row.get("agent_valid_until"),
        },
        "can_start": start_blocker is None,
        "start_blocker": start_blocker,
        "status": status,
        "capital": {
            "reserved": row.get("capital_reserved"),
            "initial_bankroll": initial_bankroll,
            "current_bankroll": current_bankroll,
            "balance": balance.get("equity") if balance else None,
            "margin_used": balance.get("margin_used") if balance else None,
            "margin_available": balance.get("margin_available") if balance else None,
            "exposure": balance.get("exposure") if balance else None,
            "max_utilization_pct": row.get("max_utilization_pct"),
            "configured_leverage": row.get("leverage"),
            "synced_at": balance.get("synced_at") if balance else None,
            "source": balance.get("source") if balance else None,
        },
        "pnl": {
            "current": pnl["unrealized"],
            "percent": position.get("return_on_equity_pct") if position else None,
            "realized_24h": pnl["realized_24h"],
            "fees_24h": pnl["fees_24h"],
            "funding_24h": pnl["funding_24h"],
            "net_24h": pnl["net_24h"],
            "run": pnl["run"],
            "realized_total": pnl["realized_total"],
            "fees_total": pnl["fees_total"],
            "funding_total": pnl["funding_total"],
            "bot_total": pnl["bot_total"],
            "basis": pnl["basis"],
        },
        "position": position,
        "orders": runtime["orders"],
        "protection": runtime["orders"]["protection"] if runtime["orders"] else None,
        "activity": runtime["activity"],
        "strategy_state": runtime["strategy_state"],
        "health": runtime["health"],
        "run": runtime["run"],
        "created_at": row.get("created_at").isoformat() if row.get("created_at") else None,
        "updated_at": row.get("updated_at").isoformat() if row.get("updated_at") else None,
    }


def _validate_bot_configuration(payload):
    from decimal import Decimal, InvalidOperation

    master_address = payload.get("master_address")
    account_address = payload.get("account_address")
    if not isinstance(master_address, str) or not re.fullmatch(r"0x[0-9a-fA-F]{40}", master_address):
        raise ValueError("Informe o endereço público da wallet principal.")
    if not isinstance(account_address, str) or not re.fullmatch(r"0x[0-9a-fA-F]{40}", account_address):
        raise ValueError("Informe o endereço público da subconta do bot.")
    if master_address.lower() == account_address.lower():
        raise ValueError("A subconta do bot deve ser diferente da wallet principal.")
    mode = payload.get("sizing_mode", "fixed")
    if mode not in {"fixed", "available_balance"}:
        raise ValueError("Modo de alocação inválido.")
    try:
        utilization = Decimal(str(payload.get("max_utilization_pct", 70)))
        reserved = Decimal(str(payload.get("capital_reserved", 0)))
        leverage = Decimal(str(payload.get("leverage", 1)))
        margin_per_trade = Decimal(str((payload.get("risk_limits") or {}).get("margin_per_trade_usdc", 0)))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Capital, utilização e alavancagem precisam ser valores válidos.") from None
    if not utilization.is_finite() or utilization <= 0 or utilization > 100:
        raise ValueError("O limite de utilização deve ser maior que 0% e no máximo 100%.")
    if not reserved.is_finite() or reserved < 0 or reserved > Decimal("1000000000"):
        raise ValueError("A banca inicial deve estar entre zero e 1.000.000.000 USDC.")
    if not margin_per_trade.is_finite() or margin_per_trade < 0 or margin_per_trade > Decimal("1000000000"):
        raise ValueError("O valor fixo por entrada deve estar entre zero e 1.000.000.000 USDC.")
    if not leverage.is_finite() or leverage != leverage.to_integral_value() or leverage < 1 or leverage > 40:
        raise ValueError("A alavancagem deve ser inteira entre 1 e 40.")

def _list_user_bots(user_id):
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT b.*,
                   r.id AS run_id,
                   r.active AS run_active,
                   r.managing AS run_managing,
                   r.state AS run_state,
                   r.heartbeat AS run_heartbeat,
                   r.created_at AS run_created_at,
                   (SELECT max(a.created_at)
                    FROM hyperliquid_actions a WHERE a.run_id = r.id) AS last_order_at
            FROM hyperliquid_bots b
            LEFT JOIN LATERAL (
                SELECT id, active, managing, state, heartbeat, created_at
                FROM hyperliquid_runs
                WHERE user_id = b.user_id AND bot_id = b.id
                ORDER BY created_at DESC, id DESC
                LIMIT 1
            ) r ON TRUE
            WHERE b.user_id = %s
            ORDER BY b.id
            """,
            (user_id,),
        ).fetchall()

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=min(8, max(1, len(rows)))) as pool:
        return list(pool.map(_build_bot_payload, rows))


@hyperliquid_api.get('/api/hyperliquid/bots')
@authenticated_user
def list_bots():
    try:
        return jsonify({'bots': _list_user_bots(session['user_id'])})
    except psycopg.Error:
        return jsonify(error="Não foi possível carregar os robôs. Verifique as migrations do banco."), 503


@hyperliquid_api.get('/api/hyperliquid/bots/markets')
@authenticated_user
def list_bot_markets():
    try:
        with _connect() as conn:
            connection = conn.execute(
                'SELECT network FROM hyperliquid_connections WHERE user_id=%s',
                (session['user_id'],),
            ).fetchone()
        if connection is None:
            return jsonify(error='Cadastre a wallet principal para consultar os mercados.'), 409
        return jsonify(markets=_bot_market_catalog(connection['network']))
    except ValueError as exc:
        return jsonify(error=str(exc)), 502
    except (URLError, TimeoutError):
        return jsonify(error='Não foi possível consultar os mercados na Hyperliquid.'), 502
    except psycopg.Error:
        return jsonify(error='Não foi possível carregar a rede da conta principal.'), 503


@hyperliquid_api.get('/api/hyperliquid/bots/<int:bot_id>')
@authenticated_user
def get_bot(bot_id):
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT b.*,
                   r.id AS run_id,
                   r.active AS run_active,
                   r.managing AS run_managing,
                   r.state AS run_state,
                   r.heartbeat AS run_heartbeat,
                   r.created_at AS run_created_at,
                   (SELECT max(a.created_at)
                    FROM hyperliquid_actions a WHERE a.run_id = r.id) AS last_order_at
            FROM hyperliquid_bots b
            LEFT JOIN LATERAL (
                SELECT id, active, managing, state, heartbeat, created_at
                FROM hyperliquid_runs
                WHERE user_id = b.user_id AND bot_id = b.id
                ORDER BY created_at DESC, id DESC
                LIMIT 1
            ) r ON TRUE
            WHERE b.user_id=%s AND b.id=%s
            """,
            (session['user_id'], bot_id),
        ).fetchone()
        if row is None:
            return jsonify(error='Bot não encontrado.'), 404
    return jsonify(_build_bot_payload(row))


@hyperliquid_api.post('/api/hyperliquid/bots/<int:bot_id>/credential')
@authenticated_user
def save_bot_credential(bot_id):
    if request.headers.get('X-IziCrypto-Setup') != '1' or not request.is_json:
        return jsonify(error='Solicitação de configuração inválida.'), 403
    local_development = (
        current_app.config.get('APP_ENV') != 'production'
        and request.host.split(':')[0] in {'127.0.0.1', 'localhost'}
    )
    if not request.is_secure and not local_development:
        return jsonify(error='Use HTTPS para cadastrar credenciais.'), 403
    if request.content_length is None or request.content_length > 4096:
        return jsonify(error='Configuração excede o tamanho permitido.'), 413

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {'private_key'}:
        return jsonify(error='Informe somente a chave privada da API.'), 400
    try:
        with _connect() as conn:
            bot = conn.execute(
                'SELECT * FROM hyperliquid_bots WHERE user_id=%s AND id=%s FOR UPDATE',
                (session['user_id'], bot_id),
            ).fetchone()
            if bot is None:
                return jsonify(error='Robô não encontrado.'), 404
            connection = conn.execute(
                'SELECT account_address, network FROM hyperliquid_connections WHERE user_id=%s',
                (session['user_id'],),
            ).fetchone()
            if (
                connection is None
                or not isinstance(bot['master_address'], str)
                or not isinstance(connection['account_address'], str)
                or bot['master_address'].lower() != connection['account_address'].lower()
                or bot['network'] != connection['network']
            ):
                return jsonify(error='A wallet principal e a rede do robô devem corresponder à conexão salva.'), 409
            managing = conn.execute(
                'SELECT 1 FROM hyperliquid_runs WHERE user_id=%s AND bot_id=%s AND managing LIMIT 1',
                (session['user_id'], bot_id),
            ).fetchone()
            if managing:
                return jsonify(error='Pare o robô antes de substituir a credencial da API.'), 409
            from .hyperliquid_setup import enroll_key
            agent, encrypted_key, valid_until = enroll_key(
                payload['private_key'], bot['master_address'], bot['network'], session['user_id'],
            )
            conn.execute(
                """
                UPDATE hyperliquid_bots
                SET agent_address=%s, encrypted_key=%s, agent_valid_until=%s, updated_at=NOW()
                WHERE id=%s AND user_id=%s
                """,
                (agent, encrypted_key, valid_until, bot_id, session['user_id']),
            )
        response = jsonify(
            api_credential={'configured': True, 'valid_until': valid_until},
        )
        response.headers['Cache-Control'] = 'no-store'
        return response
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except RuntimeError:
        return jsonify(error='Proteção de credenciais não configurada no servidor.'), 503
    except (URLError, TimeoutError):
        return jsonify(error='Não foi possível verificar a autorização na Hyperliquid. Nada foi salvo.'), 502
    except psycopg.Error:
        return jsonify(error='Não foi possível salvar a credencial do robô.'), 503


@hyperliquid_api.post('/api/hyperliquid/bots')
@authenticated_user
def create_bot():
    payload = request.get_json(silent=True)
    allowed = {
        "name", "market", "master_address", "account_address", "subaccount_name",
        "strategy_key", "strategy_config", "capital_reserved", "max_utilization_pct",
        "leverage", "sizing_mode", "risk_limits", "metadata",
    }
    if not isinstance(payload, dict) or set(payload) - allowed:
        return jsonify(error='Payload inválido.'), 400
    try:
        with _connect() as conn:
            connection = conn.execute(
                "SELECT network, account_address, strategy_key, risk_limits, "
                "agent_address, encrypted_key, agent_valid_until "
                "FROM hyperliquid_connections WHERE user_id=%s",
                (session["user_id"],),
            ).fetchone()
            if connection is None:
                return jsonify(error="Cadastre a wallet principal antes de associar uma subconta."), 409
            payload = dict(payload)
            payload.setdefault("master_address", connection["account_address"])
            payload.setdefault("strategy_key", connection["strategy_key"])
            payload.setdefault("risk_limits", connection["risk_limits"] or {})
            if "name" not in payload:
                selected_strategy = next(
                    (
                        item for item in real_execution_candidates()
                        if item.key == payload.get("strategy_key")
                    ),
                    None,
                )
                if selected_strategy is None:
                    return jsonify(error="Selecione uma estratégia para usar como nome do robô."), 400
                payload["name"] = selected_strategy.name
            payload.setdefault("market", "BTC")
            payload.setdefault("capital_reserved", 0)
            payload.setdefault("max_utilization_pct", 70)
            payload.setdefault("leverage", 1)
            payload.setdefault("sizing_mode", "fixed")
            payload["risk_limits"] = dict(payload["risk_limits"])
            payload["risk_limits"]["sizing_mode"] = payload["sizing_mode"]
            if not isinstance(payload["master_address"], str) or payload["master_address"].lower() != connection["account_address"].lower():
                return jsonify(error="A wallet principal do bot deve corresponder à conexão salva."), 400
            if not isinstance(payload["name"], str) or not 3 <= len(payload["name"].strip()) <= 60:
                return jsonify(error="O nome do bot deve ter entre 3 e 60 caracteres."), 400
            if not isinstance(payload["market"], str) or not re.fullmatch(r"[A-Za-z0-9:-]{1,32}", payload["market"]):
                return jsonify(error="Informe um mercado válido."), 400
            if payload.get("strategy_config") is not None and not isinstance(payload["strategy_config"], dict):
                return jsonify(error="A configuração da estratégia deve ser um objeto."), 400
            if not isinstance(payload["risk_limits"], dict):
                return jsonify(error="Os limites de risco devem ser um objeto."), 400
            if payload.get("metadata") is not None and not isinstance(payload["metadata"], dict):
                return jsonify(error="Os metadados devem ser um objeto."), 400
            if payload.get("subaccount_name") is not None and (
                not isinstance(payload["subaccount_name"], str) or len(payload["subaccount_name"]) > 80
            ):
                return jsonify(error="O nome da subconta deve ter no máximo 80 caracteres."), 400
            if payload.get("strategy_key") is not None and not isinstance(payload["strategy_key"], str):
                return jsonify(error="A chave da estratégia deve ser um texto."), 400
            payload["network"] = connection["network"]
            payload["master_address"] = payload["master_address"].lower()
            payload["account_address"] = str(payload.get("account_address") or "").lower()
            _validate_bot_market(payload["network"], payload["market"])
            _validate_bot_configuration(payload)
            row = conn.execute(
                """
                INSERT INTO hyperliquid_bots(
                    user_id, name, market, coin, network, master_address, wallet_address,
                    account_address, subaccount, subaccount_name, strategy_key, strategy_name,
                    strategy_config, capital_reserved, max_utilization_pct, leverage,
                    sizing_mode, status, is_active, risk_limits, metadata,
                    agent_address, encrypted_key, agent_valid_until
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'stopped',FALSE,%s,%s,%s,%s,%s)
                RETURNING *
                """,
                (
                    session["user_id"], payload["name"].strip(), payload["market"].upper(),
                    payload["market"].upper(), connection["network"], payload["master_address"],
                    payload["master_address"], payload["account_address"],
                    payload["account_address"], payload.get("subaccount_name"),
                    payload.get("strategy_key"), _strategy_name(payload.get("strategy_key")),
                    Jsonb(payload.get("strategy_config") or {}),
                    float(payload["capital_reserved"]), float(payload["max_utilization_pct"]),
                    int(payload["leverage"]), payload["sizing_mode"],
                    Jsonb(payload["risk_limits"]), Jsonb(payload.get("metadata") or {}),
                    connection.get("agent_address"), connection.get("encrypted_key"), connection.get("agent_valid_until"),
                ),
            ).fetchone()
        return jsonify(_build_bot_payload(row)), 201
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except (URLError, TimeoutError):
        return jsonify(error='Não foi possível verificar o mercado na Hyperliquid. Nenhum robô foi salvo.'), 502
    except psycopg.IntegrityError:
        return jsonify(error="Essa subconta já está associada a um robô nesta rede."), 409
    except psycopg.Error:
        return jsonify(error="Não foi possível salvar o robô. Verifique se as migrations foram aplicadas."), 503


@hyperliquid_api.post('/api/hyperliquid/bots/import-legacy')
@authenticated_user
def import_legacy_bot():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) - {"subaccount_address"}:
        return jsonify(error="Payload inválido."), 400
    supplied_address = payload.get("subaccount_address")
    if supplied_address is not None and (
        not isinstance(supplied_address, str)
        or not re.fullmatch(r"0x[0-9a-fA-F]{40}", supplied_address)
    ):
        return jsonify(error="Informe um endereço público de subconta válido."), 400

    try:
        with _connect() as conn:
            connection = conn.execute(
                """
                SELECT network, account_address, strategy_key, risk_limits,
                       legacy_subaccount_address, agent_address, encrypted_key, agent_valid_until
                FROM hyperliquid_connections
                WHERE user_id=%s
                FOR UPDATE
                """,
                (session["user_id"],),
            ).fetchone()
            if connection is None:
                return jsonify(error="Não existe uma configuração antiga para importar."), 409

            saved_subaccount = connection["legacy_subaccount_address"]
            if (
                supplied_address is not None
                and saved_subaccount is not None
                and supplied_address.lower() != saved_subaccount.lower()
            ):
                return jsonify(error="A configuração antiga já está vinculada a outra subconta."), 409
            subaccount_address = (supplied_address or connection["legacy_subaccount_address"] or "").lower()
            if not subaccount_address:
                return jsonify(error="Informe a subconta usada pela configuração antiga."), 400
            master_address = connection["account_address"].lower()
            if subaccount_address == master_address:
                return jsonify(error="A subconta deve ser diferente da conta principal."), 400

            existing = conn.execute(
                """
                SELECT id, user_id, status
                FROM hyperliquid_bots
                WHERE network=%s AND account_address=%s
                """,
                (connection["network"], subaccount_address),
            ).fetchone()
            if existing is not None:
                if existing["user_id"] != session["user_id"]:
                    return jsonify(error="Essa subconta já está associada a outra configuração."), 409
                conn.execute(
                    """
                    UPDATE hyperliquid_connections
                    SET legacy_subaccount_address=%s, updated_at=NOW()
                    WHERE user_id=%s
                    """,
                    (subaccount_address, session["user_id"]),
                )
                return jsonify(
                    status="already_imported",
                    bot={"id": existing["id"], "status": existing["status"]},
                )

            strategy = next(
                (
                    item for item in real_execution_candidates()
                    if item.key == connection["strategy_key"]
                ),
                None,
            )
            if strategy is None:
                return jsonify(error="Selecione uma estratégia disponível antes de importar o robô."), 409

            risk_limits = connection["risk_limits"] or {}
            if not isinstance(risk_limits, dict):
                return jsonify(error="Os limites salvos não são válidos para importar o robô."), 409
            strategy_config = asdict(strategy)
            sizing_mode = risk_limits.get("sizing_mode", "fixed")
            bot_payload = {
                "network": connection["network"],
                "master_address": master_address,
                "account_address": subaccount_address,
                "capital_reserved": risk_limits.get("capital_usdc", 0) or 0,
                "max_utilization_pct": 70,
                "leverage": risk_limits.get("max_leverage", strategy_config["leverage"]),
                "sizing_mode": sizing_mode,
            }
            _validate_bot_configuration(bot_payload)
            row = conn.execute(
                """
                INSERT INTO hyperliquid_bots(
                    user_id, name, market, coin, network, master_address, wallet_address,
                    account_address, subaccount, subaccount_name, strategy_key, strategy_name,
                    strategy_config, capital_reserved, max_utilization_pct, leverage,
                    sizing_mode, status, is_active, risk_limits, metadata,
                    agent_address, encrypted_key, agent_valid_until
                )
                VALUES (%s,%s,'BTC','BTC',%s,%s,%s,%s,%s,'Subconta importada',%s,%s,%s,%s,70,%s,%s,'stopped',FALSE,%s,%s,%s,%s,%s)
                RETURNING id, status
                """,
                (
                    session["user_id"], strategy.name, connection["network"], master_address, master_address,
                    subaccount_address, subaccount_address, strategy.key, strategy.name,
                    Jsonb(strategy_config), float(bot_payload["capital_reserved"]),
                    int(bot_payload["leverage"]), sizing_mode, Jsonb(risk_limits),
                    Jsonb({"source": "legacy_connection"}),
                    connection.get("agent_address"), connection.get("encrypted_key"), connection.get("agent_valid_until"),
                ),
            ).fetchone()
            conn.execute(
                """
                UPDATE hyperliquid_connections
                SET legacy_subaccount_address=%s, updated_at=NOW()
                WHERE user_id=%s
                """,
                (subaccount_address, session["user_id"]),
            )
        return jsonify(status="imported", bot={"id": row["id"], "status": row["status"]}), 201
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except psycopg.IntegrityError:
        return jsonify(error="Essa subconta já está associada a um robô nesta rede."), 409
    except psycopg.Error:
        return jsonify(error="Não foi possível importar a configuração antiga. Verifique as migrations."), 503


@hyperliquid_api.patch('/api/hyperliquid/bots/<int:bot_id>')
@authenticated_user
def update_bot(bot_id):
    payload = request.get_json(silent=True)
    allowed = {
        "name", "market", "master_address", "account_address", "subaccount_name",
        "strategy_key", "strategy_config", "capital_reserved", "max_utilization_pct",
        "leverage", "sizing_mode", "risk_limits", "metadata",
    }
    if not isinstance(payload, dict) or set(payload) - allowed:
        return jsonify(error='Payload inválido.'), 400
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM hyperliquid_bots WHERE user_id=%s AND id=%s FOR UPDATE",
                (session["user_id"], bot_id),
            ).fetchone()
            if row is None:
                return jsonify(error="Bot não encontrado."), 404
            if conn.execute(
                "SELECT 1 FROM hyperliquid_runs WHERE user_id=%s AND bot_id=%s AND managing LIMIT 1",
                (session["user_id"], bot_id),
            ).fetchone():
                return jsonify(error="Pause ou pare o robô e aguarde a posição ser gerenciada antes de editar a configuração."), 409
            if "risk_limits" in payload and not isinstance(payload["risk_limits"], dict):
                return jsonify(error="Os limites de risco devem ser um objeto."), 400
            if "risk_limits" in payload and "daily_loss_usdc" in payload["risk_limits"] and not _positive_number(
                payload["risk_limits"]["daily_loss_usdc"]
            ):
                return jsonify(error="O limite de perda diária deve ser maior que zero."), 400
            merged = dict(row)
            merged.update(payload)
            merged_risk_limits = dict(merged.get("risk_limits") or {})
            merged_risk_limits["sizing_mode"] = merged.get("sizing_mode", "fixed")
            merged["risk_limits"] = merged_risk_limits
            if "sizing_mode" in payload and "risk_limits" not in payload:
                payload = dict(payload)
                payload["risk_limits"] = merged_risk_limits
            merged["master_address"] = str(merged.get("master_address") or "").lower()
            merged["account_address"] = str(merged.get("account_address") or "").lower()
            connection = conn.execute(
                "SELECT account_address FROM hyperliquid_connections WHERE user_id=%s",
                (session["user_id"],),
            ).fetchone()
            if connection is None or merged["master_address"] != connection["account_address"].lower():
                return jsonify(error="A wallet principal do bot deve corresponder à conexão salva."), 400
            if "name" in payload and (
                not isinstance(payload["name"], str) or not 3 <= len(payload["name"].strip()) <= 60
            ):
                return jsonify(error="O nome do bot deve ter entre 3 e 60 caracteres."), 400
            if "market" in payload and (
                not isinstance(payload["market"], str)
                or not re.fullmatch(r"[A-Za-z0-9:-]{1,32}", payload["market"])
            ):
                return jsonify(error="Informe um mercado válido."), 400
            if "market" in payload:
                _validate_bot_market(merged["network"], payload["market"].upper())
            if "subaccount_name" in payload and payload["subaccount_name"] is not None and (
                not isinstance(payload["subaccount_name"], str) or len(payload["subaccount_name"]) > 80
            ):
                return jsonify(error="O nome da subconta deve ter no máximo 80 caracteres."), 400
            if "strategy_key" in payload and payload["strategy_key"] is not None and not isinstance(payload["strategy_key"], str):
                return jsonify(error="A chave da estratégia deve ser um texto."), 400
            if "strategy_config" in payload and not isinstance(payload["strategy_config"], dict):
                return jsonify(error="A configuração da estratégia deve ser um objeto."), 400
            if "risk_limits" in payload and not isinstance(payload["risk_limits"], dict):
                return jsonify(error="Os limites de risco devem ser um objeto."), 400
            if "metadata" in payload and not isinstance(payload["metadata"], dict):
                return jsonify(error="Os metadados devem ser um objeto."), 400
            _validate_bot_configuration(merged)
            columns = {
                "name": "name", "market": "market", "master_address": "master_address",
                "account_address": "account_address", "subaccount_name": "subaccount_name",
                "strategy_key": "strategy_key", "strategy_config": "strategy_config",
                "capital_reserved": "capital_reserved", "max_utilization_pct": "max_utilization_pct",
                "leverage": "leverage", "sizing_mode": "sizing_mode",
                "risk_limits": "risk_limits", "metadata": "metadata",
            }
            assignments = []
            values = []
            for key, column in columns.items():
                if key not in payload:
                    continue
                value = payload[key]
                if key in {"strategy_config", "risk_limits", "metadata"}:
                    if not isinstance(value, dict):
                        return jsonify(error=f"{key} deve ser um objeto."), 400
                    value = Jsonb(value)
                if key in {"market", "name"} and not isinstance(value, str):
                    return jsonify(error=f"{key} precisa ser texto."), 400
                if key == "market":
                    value = value.upper()
                if key == "name":
                    value = value.strip()
                assignments.append(f"{column}=%s")
                values.append(value)
            if "market" in payload:
                assignments.append("coin=%s")
                values.append(payload["market"].upper())
            if "master_address" in payload:
                assignments.append("wallet_address=%s")
                values.append(payload["master_address"].lower())
            if "account_address" in payload:
                assignments.append("subaccount=%s")
                values.append(payload["account_address"].lower())
            if "strategy_key" in payload:
                assignments.append("strategy_name=%s")
                values.append(_strategy_name(payload["strategy_key"]))
            if not assignments:
                refreshed = dict(row)
            else:
                assignments.append("updated_at=NOW()")
                values.extend((bot_id, session["user_id"]))
                conn.execute(
                    f"UPDATE hyperliquid_bots SET {', '.join(assignments)} WHERE id=%s AND user_id=%s",
                    tuple(values),
                )
                refreshed = conn.execute(
                    "SELECT * FROM hyperliquid_bots WHERE id=%s AND user_id=%s",
                    (bot_id, session["user_id"]),
                ).fetchone()
        return jsonify(_build_bot_payload(refreshed))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except (URLError, TimeoutError):
        return jsonify(error='Não foi possível verificar o mercado na Hyperliquid. Nenhuma alteração foi salva.'), 502
    except psycopg.IntegrityError:
        return jsonify(error="Essa subconta já está associada a outro robô."), 409
    except psycopg.Error:
        return jsonify(error="Não foi possível atualizar o robô."), 503


@hyperliquid_api.post('/api/hyperliquid/bots/<int:bot_id>/start')
@authenticated_user
def start_bot(bot_id):
    if request.headers.get('X-IziCrypto-Setup') != '1' or not request.is_json:
        return jsonify(error='Solicitação de execução inválida.'), 403
    from .execution_engine import ExecutionBlocked
    from . import execution_service
    try:
        run_id = execution_service.activate_bot(session['user_id'], bot_id)
        return jsonify(status='running', run_id=run_id, bot={'id': bot_id, 'status': 'running'}), 201
    except ExecutionBlocked as exc:
        return jsonify(error=str(exc)), 409
    except psycopg.IntegrityError:
        return jsonify(error='Este robô já possui uma sessão em gerenciamento. Pare novas entradas e confira a sessão existente.'), 409
    except (psycopg.Error, RuntimeError):
        return jsonify(error='Não foi possível iniciar o robô. Nenhuma ativação foi confirmada.'), 503
    except Exception:
        return jsonify(error='Falha no preflight de execução. Nenhuma ativação foi confirmada; confira a subconta antes de tentar novamente.'), 503


@hyperliquid_api.post('/api/hyperliquid/bots/<int:bot_id>/pause')
@authenticated_user
def pause_bot(bot_id):
    if request.headers.get('X-IziCrypto-Setup') != '1' or not request.is_json:
        return jsonify(error='Solicitação de execução inválida.'), 403
    with _connect() as conn:
        row = conn.execute('SELECT * FROM hyperliquid_bots WHERE user_id=%s AND id=%s', (session['user_id'], bot_id)).fetchone()
        if row is None:
            return jsonify(error='Bot não encontrado.'), 404
        conn.execute('UPDATE hyperliquid_bots SET status=%s, is_active=FALSE, updated_at=NOW() WHERE id=%s AND user_id=%s', ('paused', bot_id, session['user_id']))
        conn.execute('UPDATE hyperliquid_runs SET active=FALSE WHERE user_id=%s AND bot_id=%s AND managing', (session['user_id'], bot_id))
        refreshed = conn.execute('SELECT * FROM hyperliquid_bots WHERE id=%s AND user_id=%s', (bot_id, session['user_id'])).fetchone()
        return jsonify({'status': 'paused', 'bot': {'id': refreshed['id'], 'status': 'paused'}})


@hyperliquid_api.post('/api/hyperliquid/bots/<int:bot_id>/stop')
@authenticated_user
def stop_bot(bot_id):
    if request.headers.get('X-IziCrypto-Setup') != '1' or not request.is_json:
        return jsonify(error='Solicitação de execução inválida.'), 403
    with _connect() as conn:
        row = conn.execute('SELECT * FROM hyperliquid_bots WHERE user_id=%s AND id=%s', (session['user_id'], bot_id)).fetchone()
        if row is None:
            return jsonify(error='Bot não encontrado.'), 404
        conn.execute('UPDATE hyperliquid_bots SET status=%s, is_active=FALSE, updated_at=NOW() WHERE id=%s AND user_id=%s', ('stopped', bot_id, session['user_id']))
        conn.execute('UPDATE hyperliquid_runs SET active=FALSE WHERE user_id=%s AND bot_id=%s AND managing', (session['user_id'], bot_id))
        refreshed = conn.execute('SELECT * FROM hyperliquid_bots WHERE id=%s AND user_id=%s', (bot_id, session['user_id'])).fetchone()
        return jsonify({'status': 'stopped', 'bot': {'id': refreshed['id'], 'status': 'stopped'}})


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
                    legacy_subaccount_address=CASE WHEN hyperliquid_connections.network=EXCLUDED.network AND hyperliquid_connections.account_address=EXCLUDED.account_address THEN hyperliquid_connections.legacy_subaccount_address ELSE NULL END,
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
