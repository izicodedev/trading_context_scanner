"""Hyperliquid SDK adapter. Constructing it does not send orders."""
import json
import re
import time
from datetime import timezone
from email.utils import parsedate_to_datetime
from urllib.request import Request, urlopen
from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.utils.types import Cloid
from .hyperliquid_setup import cipher
from .execution_engine import ExecutionBlocked
from .account_balance import trading_balance


class OrderResponseError(ExecutionBlocked):
    """An exchange response with no usable one-order acknowledgement."""

    def __init__(self, code, detail=None):
        super().__init__('Resposta da ordem não confirmada; reconciliação necessária.')
        self.code = code
        # Exchange errors can include public addresses. Never persist raw SDK payloads.
        if isinstance(detail, str):
            detail = re.sub(r'0x[0-9a-fA-F]{16,}', '[endereço]', detail)
            detail = re.sub(r'[^\x20-\x7EÀ-ÿ]', ' ', detail).strip()
            self.detail = detail[:180] or None
        else:
            self.detail = None


def parse_order(result):
    if not isinstance(result, dict):
        raise OrderResponseError('invalid_payload')
    if result.get('status') != 'ok':
        detail = result.get('response') or result.get('error')
        if isinstance(detail, str) and detail.strip() == 'Action already expired':
            # The exchange explicitly rejected this signed action before acceptance.
            return dict(filled=0, resting=False, rejected=True, reason='action_expired')
        raise OrderResponseError('exchange_error', detail)
    response = result.get('response')
    data = response.get('data') if isinstance(response, dict) else None
    statuses = data.get('statuses') if isinstance(data, dict) else None
    if not isinstance(statuses, list) or len(statuses) != 1:
        raise OrderResponseError('status_count')
    status = statuses[0]
    if not isinstance(status, dict):
        raise OrderResponseError('invalid_status')
    if 'filled' in status:
        fill = status['filled']
        try:
            return dict(filled=float(fill['totalSz']), price=float(fill['avgPx']), resting=False)
        except (TypeError, ValueError, KeyError):
            raise OrderResponseError('invalid_fill') from None
    if 'resting' in status:
        return dict(filled=0, resting=True)
    if 'error' in status:
        return dict(filled=0, resting=False, rejected=True)
    raise OrderResponseError('unknown_status')


class Broker:
    def __init__(self, config):
        secret = json.loads(cipher().decrypt(config['encrypted_key'].encode()))
        if any(secret[key] != config[field] for key, field in [('owner', 'account_address'), ('network', 'network'), ('user_id', 'user_id')]):
            raise ExecutionBlocked('Credencial não corresponde à configuração da sessão.')
        wallet = Account.from_key(secret['key'])
        if wallet.address.lower() != config['agent_address']:
            raise ExecutionBlocked('Carteira de API divergente.')
        self.owner = config['account_address']
        self.agent = config['agent_address']
        url = 'https://api.hyperliquid.xyz' if config['network'] == 'mainnet' else 'https://api.hyperliquid-testnet.xyz'
        self.url = url
        self.exchange = Exchange(wallet, url, account_address=self.owner, timeout=10)
        self.info = self.exchange.info

    def check_clock(self):
        """Refuse signed actions when the VPS clock differs from the exchange API."""
        request = Request(self.url + '/info', data=b'{"type":"meta"}',
                          headers={'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=5) as response:
                date_header = response.headers.get('Date')
            server_time = parsedate_to_datetime(date_header)
            if server_time.tzinfo is None:
                server_time = server_time.replace(tzinfo=timezone.utc)
        except (OSError, TypeError, ValueError) as exc:
            raise ExecutionBlocked('Não foi possível verificar o relógio da VPS com a Hyperliquid; nenhuma ordem enviada.') from exc
        if abs(time.time() - server_time.timestamp()) > 5:
            raise ExecutionBlocked('Relógio da VPS fora de sincronia com a Hyperliquid; nenhuma ordem enviada.')

    def authorized(self):
        now = time.time() * 1000
        if not any(a['address'].lower() == self.agent and a['validUntil'] > now for a in self.info.extra_agents(self.owner)):
            raise ExecutionBlocked('Carteira de API expirada ou revogada.')

    def get_positions(self):
        state = self.info.user_state(self.owner)
        return [p['position'] for p in state['assetPositions'] if float(p['position']['szi']) != 0]

    def account(self, management=False):
        state = self.info.user_state(self.owner)
        positions = [p['position'] for p in state['assetPositions'] if float(p['position']['szi']) != 0]
        orders = self.info.frontend_open_orders(self.owner)
        if management:
            # Closing exposure must not depend on spot balance or account-mode APIs.
            return positions, orders, 0, 0
        mode = self.info.query_user_abstraction_state(self.owner)
        spot = self.info.spot_user_state(self.owner) if mode == 'unifiedAccount' else None
        try:
            equity, available, source = trading_balance(mode, state, spot)
        except (ValueError, KeyError, TypeError) as exc:
            raise ExecutionBlocked('Não foi possível confirmar o saldo operacional para o modo desta conta.') from exc
        self.balance_source = source
        return positions, orders, equity, available

    def daily(self, since):
        return self.info.user_fills_by_time(self.owner, since), self.info.user_funding_history(self.owner, since)

    def candles(self, now):
        return self.info.candles_snapshot('BTC', '5m', now - 301 * 300_000, now)

    def market(self):
        asset = next(a for a in self.info.meta()['universe'] if a['name'] == 'BTC')
        if asset.get('isDelisted'):
            raise ExecutionBlocked('Mercado BTC indisponível.')
        return float(self.info.all_mids()['BTC']), asset['szDecimals'], asset['maxLeverage']

    def leverage(self, value):
        if self.exchange.update_leverage(value, 'BTC', is_cross=False).get('status') != 'ok':
            raise ExecutionBlocked('Não foi possível configurar margem isolada.')

    def entry(self, cloid, quantity, buy, limit_price):
        self.exchange.set_expires_after(int(time.time() * 1000) + 15000)
        # The caller calculates the IOC limit from the already checked market price.
        # Do not make another /info request after the entry intent is journaled.
        return parse_order(self.exchange.order('BTC', buy, quantity, limit_price,
            {'limit': {'tif': 'Ioc'}}, cloid=Cloid.from_str(cloid)))

    def close(self, cloid, quantity, buy):
        # reduce_only is explicit; never opens or reverses exposure.
        self.exchange.set_expires_after(int(time.time() * 1000) + 15000)
        px, decimals, _ = self.market()
        from .execution_engine import price_round
        price = price_round(px * (1.003 if buy else .997), decimals)
        return parse_order(self.exchange.order('BTC', buy, quantity, price, {'limit': {'tif': 'Ioc'}}, reduce_only=True, cloid=Cloid.from_str(cloid)))

    def protect(self, cloid, quantity, buy, trigger, kind):
        self.exchange.set_expires_after(int(time.time() * 1000) + 15000)
        return parse_order(self.exchange.order('BTC', buy, quantity, trigger,
            {'trigger': {'triggerPx': trigger, 'isMarket': True, 'tpsl': kind}}, reduce_only=True, cloid=Cloid.from_str(cloid)))

    def cancel(self, cloid):
        self.exchange.set_expires_after(int(time.time() * 1000) + 15000)
        result = self.exchange.cancel_by_cloid('BTC', Cloid.from_str(cloid))
        if result.get('status') != 'ok':
            raise ExecutionBlocked('Não foi possível cancelar a proteção remanescente.')
        # Verify absence rather than trusting a top-level OK containing an error.
        if any(o.get('cloid') == cloid for o in self.info.frontend_open_orders(self.owner)):
            raise ExecutionBlocked('Proteção remanescente ainda aberta.')

    def lookup(self, cloid):
        return self.info.query_order_by_cloid(self.owner, Cloid.from_str(cloid))

    def entry_evidence(self, cloid, since):
        """Only fills tied to the known order establish ownership after a timeout."""
        result = self.lookup(cloid)
        if result.get('status') != 'order':
            return None
        record = result['order']
        order = record['order']
        if order.get('coin') != 'BTC' or order.get('cloid') != cloid:
            raise ExecutionBlocked('Identidade da ordem divergente na reconciliação.')
        from .execution_engine import terminal_status
        if not terminal_status(record.get('status')):
            return None
        fills = self.info.user_fills_by_time(self.owner, since)
        if len(fills) >= 2000:
            raise ExecutionBlocked('Histórico truncado; não foi possível confirmar a entrada.')
        matched = {f['tid']: f for f in fills if f['oid'] == order['oid'] and f['coin'] == 'BTC'}
        qty = sum(float(f['sz']) for f in matched.values())
        if record['status'] == 'filled' and qty == 0:
            return None  # Order and fills endpoints can become consistent at different times.
        return dict(quantity=qty, side='LONG' if order['side'] == 'B' else 'SHORT')
