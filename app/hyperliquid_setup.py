"""Credential enrollment only; never submits exchange actions."""
import json
import os
import re
import time
from decimal import Decimal, InvalidOperation
from urllib.error import URLError

from cryptography.fernet import Fernet
from eth_account import Account
from flask import Blueprint, current_app, jsonify, request, session
from psycopg import Error
from psycopg.types.json import Jsonb

from .auth import authenticated_user
from .candle_storage import _connect
from .hyperliquid_api import info

setup_api = Blueprint('hyperliquid_setup', __name__)


def cipher():
    try:
        return Fernet(os.environ['HYPERLIQUID_ENCRYPTION_KEY'].encode())
    except (KeyError, ValueError):
        raise RuntimeError('Proteção de credenciais não configurada no servidor.') from None


def validate_limits(data):
    fields = {'capital_usdc', 'margin_per_trade_usdc', 'max_leverage', 'daily_loss_usdc', 'sizing_mode'}
    if not isinstance(data, dict) or set(data) != fields:
        raise ValueError('Preencha o modo de exposição e os limites de operação.')
    mode = data['sizing_mode']
    if mode not in ('fixed', 'available_balance'):
        raise ValueError('Modo de exposição inválido.')
    numeric_fields = {'max_leverage', 'daily_loss_usdc'}
    if mode == 'fixed':
        numeric_fields |= {'capital_usdc', 'margin_per_trade_usdc'}
    try:
        values = {key: Decimal(str(data[key])) for key in numeric_fields}
    except InvalidOperation:
        raise ValueError('Os limites precisam ser números positivos.') from None
    if any(not value.is_finite() or value <= 0 or value > 1_000_000_000 for value in values.values()):
        raise ValueError('Limites inválidos: informe números positivos finitos.')
    if values['max_leverage'] != values['max_leverage'].to_integral_value() or values['max_leverage'] > 40:
        raise ValueError('Alavancagem deve ser inteira entre 1 e 40; o limite do mercado será verificado pelo executor.')
    if mode == 'fixed' and max(values['margin_per_trade_usdc'], values['daily_loss_usdc']) > values['capital_usdc']:
        raise ValueError('Margem por entrada e perda diária não podem superar o capital máximo.')
    return dict(capital_usdc=None, margin_per_trade_usdc=None,
                **{key: str(value) for key, value in values.items() if key not in {'capital_usdc', 'margin_per_trade_usdc'}},
                sizing_mode=mode) | {key: str(values[key]) for key in ('capital_usdc', 'margin_per_trade_usdc') if key in values}


def enroll_key(key, owner, network, user_id):
    if not isinstance(key, str) or not re.fullmatch(r'(0x)?[0-9a-fA-F]{64}', key):
        raise ValueError('Informe a chave privada da carteira de API (64 caracteres hexadecimais).')
    try:
        agent = Account.from_key(key).address.lower()
    except Exception:
        raise ValueError('Chave de API inválida.') from None
    if agent == owner.lower():
        raise ValueError('Não use a chave da conta principal. Use uma carteira de API dedicada.')
    protector = cipher()
    agents = info(network, {'type': 'extraAgents', 'user': owner})
    now = int(time.time() * 1000)
    approved = next((item for item in agents if isinstance(item, dict) and
                     str(item.get('address', '')).lower() == agent and
                     isinstance(item.get('validUntil'), int) and item['validUntil'] > now), None) if isinstance(agents, list) else None
    if approved is None:
        raise ValueError('Esta carteira de API não está autorizada ou está expirada para a conta e rede salvas. Para subcontas, cadastre primeiro a conta principal que autorizou o agente.')
    token = protector.encrypt(json.dumps(dict(key=key, user_id=user_id, network=network, owner=owner)).encode()).decode()
    return agent, token, approved['validUntil']


@setup_api.route('/api/hyperliquid/setup', methods=['GET', 'POST'])
@authenticated_user
def setup():
    if request.method == 'POST':
        # Custom header forces cross-origin clients through preflight (not allowed by CORS).
        if request.headers.get('X-IziCrypto-Setup') != '1' or not request.is_json:
            return jsonify(error='Solicitação de configuração inválida.'), 403
        local_development = current_app.config.get('APP_ENV') != 'production' and request.host.split(':')[0] in {'127.0.0.1', 'localhost'}
        if not request.is_secure and not local_development:
            return jsonify(error='Use HTTPS para cadastrar credenciais.'), 403
        if request.content_length is None or request.content_length > 4096:
            return jsonify(error='Configuração excede o tamanho permitido.'), 413
    try:
        with _connect() as conn:
            row = conn.execute('SELECT network, account_address, agent_address, agent_valid_until, risk_limits FROM hyperliquid_connections WHERE user_id=%s FOR UPDATE', (session['user_id'],)).fetchone()
            if row is None:
                return jsonify(error='Salve a conexão da conta primeiro.'), 409
            if request.method == 'POST':
                payload = request.get_json(silent=True)
                if not isinstance(payload, dict) or set(payload) - {'private_key', 'limits'} or 'limits' not in payload:
                    raise ValueError('Informe os limites e, opcionalmente, uma chave de API.')
                limits = validate_limits(payload['limits'])
                key = payload.get('private_key')
                if key:
                    agent, token, expires = enroll_key(key, row['account_address'], row['network'], session['user_id'])
                    conn.execute('UPDATE hyperliquid_connections SET agent_address=%s, encrypted_key=%s, agent_valid_until=%s WHERE user_id=%s', (agent, token, expires, session['user_id']))
                    row.update(agent_address=agent, agent_valid_until=expires)
                conn.execute('UPDATE hyperliquid_connections SET risk_limits=%s, updated_at=NOW() WHERE user_id=%s', (Jsonb(limits), session['user_id']))
                row['risk_limits'] = limits
        # No ciphertext or private key ever leaves the backend.
        return jsonify(**row, execution_enabled=False, authorization_checked_at_enrollment_only=True)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except RuntimeError:
        return jsonify(error='Proteção de credenciais não configurada no servidor.'), 503
    except (URLError, TimeoutError):
        return jsonify(error='Não foi possível verificar a autorização na Hyperliquid. Nada foi salvo.'), 502
    except Error:
        return jsonify(error='Não foi possível salvar a configuração.'), 503


@setup_api.after_request
def no_cache(response):
    response.headers['Cache-Control'] = 'no-store'
    return response
