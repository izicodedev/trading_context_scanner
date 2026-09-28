import json
import time
import pytest
from cryptography.fernet import Fernet
from eth_account import Account
from app import hyperliquid_setup as setup
from test_hyperliquid_api import client, fake_database, ADDRESS


def limits(mode='fixed'):
    return dict(sizing_mode=mode, capital_usdc='100', margin_per_trade_usdc='20', max_leverage='2', daily_loss_usdc='5')


def test_dynamic_mode_removes_fixed_caps():
    data = limits('available_balance')
    data.update(capital_usdc='', margin_per_trade_usdc='')
    result = setup.validate_limits(data)
    assert result['capital_usdc'] is None and result['margin_per_trade_usdc'] is None
    assert result['daily_loss_usdc'] == '5'


@pytest.mark.parametrize('field,value', [('capital_usdc', 'NaN'), ('max_leverage', 'Infinity'), ('max_leverage', '1.5'), ('max_leverage', 41), ('margin_per_trade_usdc', 101), ('daily_loss_usdc', -1), ('daily_loss_usdc', True)])
def test_bad_limits(field, value):
    data = limits(); data[field] = value
    with pytest.raises(ValueError): setup.validate_limits(data)


def test_key_is_bound_to_account_user_and_network_and_encrypted(monkeypatch):
    agent = Account.create()
    monkeypatch.setenv('HYPERLIQUID_ENCRYPTION_KEY', Fernet.generate_key().decode())
    expiry = int(time.time() * 1000) + 100000
    monkeypatch.setattr(setup, 'info', lambda network, body: [{'address': agent.address, 'validUntil': expiry}])
    address, token, valid = setup.enroll_key(agent.key.hex(), ADDRESS, 'mainnet', 7)
    assert agent.key.hex() not in token
    value = json.loads(setup.cipher().decrypt(token.encode()))
    assert value['owner'] == ADDRESS and value['user_id'] == 7 and value['network'] == 'mainnet'
    assert address == agent.address.lower() and valid == expiry


def test_main_key_and_unapproved_agent_rejected(monkeypatch):
    agent = Account.create()
    monkeypatch.setenv('HYPERLIQUID_ENCRYPTION_KEY', Fernet.generate_key().decode())
    monkeypatch.setattr(setup, 'info', lambda *args: [])
    with pytest.raises(ValueError, match='principal'): setup.enroll_key(agent.key.hex(), agent.address, 'mainnet', 1)
    with pytest.raises(ValueError, match='autorizada'): setup.enroll_key(agent.key.hex(), ADDRESS, 'mainnet', 1)


def test_setup_requires_custom_header(client):
    assert client.post('/api/hyperliquid/setup', json={'limits': limits()}).status_code == 403


def test_production_rejects_plain_http_even_with_localhost_host(client, monkeypatch):
    from app.web import app
    monkeypatch.setitem(app.config,'APP_ENV','production')
    response=client.post('/api/hyperliquid/setup',json={'limits':limits()},headers={'X-IziCrypto-Setup':'1'})
    assert response.status_code==403 and 'HTTPS' in response.json['error']


def test_limits_only_save_never_returns_secret(client, monkeypatch):
    from contextlib import contextmanager
    class Connection:
        def execute(self, sql, params):
            assert params[-1] == 7
            return self
        def fetchone(self):
            return dict(network='mainnet', account_address=ADDRESS, agent_address=None, agent_valid_until=None, risk_limits=None)
    @contextmanager
    def connect(): yield Connection()
    monkeypatch.setattr(setup, '_connect', connect)
    response = client.post('/api/hyperliquid/setup', json={'limits': limits('available_balance')}, headers={'X-IziCrypto-Setup':'1'})
    assert response.status_code == 200
    assert response.json['risk_limits']['sizing_mode'] == 'available_balance'
    assert 'encrypted_key' not in response.json and 'private_key' not in response.json
    assert response.headers['Cache-Control'] == 'no-store'
