"""Hyperliquid SDK adapter. Constructing it does not send orders."""
import json
import time
from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.utils.types import Cloid
from .hyperliquid_setup import cipher
from .execution_engine import ExecutionBlocked
from .account_balance import trading_balance


def parse_order(result):
    if not isinstance(result, dict) or result.get('status') != 'ok':
        raise ExecutionBlocked('A corretora não confirmou a solicitação.')
    statuses = result.get('response', {}).get('data', {}).get('statuses', [])
    if len(statuses) != 1:
        raise ExecutionBlocked('Resposta de ordem ambígua.')
    status = statuses[0]
    if not isinstance(status, dict):
        raise ExecutionBlocked('Estado de ordem não confirmado.')
    if 'filled' in status:
        fill = status['filled']
        return dict(filled=float(fill['totalSz']), price=float(fill['avgPx']), resting=False)
    if 'resting' in status:
        return dict(filled=0, resting=True)
    if 'error' in status:
        return dict(filled=0, resting=False, rejected=True)
    raise ExecutionBlocked('Resposta de ordem desconhecida.')


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
        self.exchange = Exchange(wallet, url, account_address=self.owner, timeout=10)
        self.info = self.exchange.info

    def authorized(self):
        now = time.time() * 1000
        if not any(a['address'].lower() == self.agent and a['validUntil'] > now for a in self.info.extra_agents(self.owner)):
            raise ExecutionBlocked('Carteira de API expirada ou revogada.')

    def account(self):
        state = self.info.user_state(self.owner)
        positions = [p['position'] for p in state['assetPositions'] if float(p['position']['szi']) != 0]
        mode = self.info.query_user_abstraction_state(self.owner)
        spot = self.info.spot_user_state(self.owner) if mode == 'unifiedAccount' else None
        try:
            equity, available, source = trading_balance(mode, state, spot)
        except (ValueError, KeyError, TypeError) as exc:
            raise ExecutionBlocked('Não foi possível confirmar o saldo operacional para o modo desta conta.') from exc
        self.balance_source = source
        return positions, self.info.frontend_open_orders(self.owner), equity, available

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

    def entry(self, cloid, quantity, buy):
        self.exchange.set_expires_after(int(time.time() * 1000) + 15000)
        return parse_order(self.exchange.market_open('BTC', buy, quantity, slippage=.001, cloid=Cloid.from_str(cloid)))

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
