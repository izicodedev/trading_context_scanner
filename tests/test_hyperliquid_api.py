from contextlib import contextmanager
from urllib.error import URLError

import pytest
import app.auth as auth
import app.hyperliquid_api as hl
from app.web import app

ADDRESS = '0x' + 'a' * 40


@pytest.mark.parametrize('payload', [None, [], {}, {'network': 'bad', 'account_address': ADDRESS},
    {'network': 'mainnet', 'account_address': 'private-key'},
    {'network': 'mainnet', 'account_address': '0x' + '0' * 40},
    {'network': 'mainnet', 'account_address': ADDRESS, 'private_key': 'secret'},
    {'network': [], 'account_address': ADDRESS}])
def test_rejects_invalid_connection_and_secret_fields(payload):
    with pytest.raises(ValueError):
        hl.validate_connection(payload)


def test_connection_normalizes_public_address():
    assert hl.validate_connection({'network': 'mainnet', 'account_address': '0x' + 'A' * 40}) == ('mainnet', ADDRESS)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(app.config, 'SECRET_KEY', 'hyperliquid-test-secret')
    monkeypatch.setitem(app.config, 'SESSION_COOKIE_SECURE', False)
    monkeypatch.setattr(auth, 'get_database_url', lambda: 'postgresql://test')
    monkeypatch.setattr(auth, 'get_active_user_by_id', lambda uid: {'id': uid})
    client = app.test_client()
    with client.session_transaction() as session:
        session['user_id'] = 7
    return client


def fake_database(monkeypatch, row):
    calls = []
    class Connection:
        def execute(self, sql, params):
            calls.append((sql, params))
            return self
        def fetchone(self):
            return row
    @contextmanager
    def connect():
        yield Connection()
    monkeypatch.setattr(hl, '_connect', connect)
    return calls


def test_requires_authentication(client):
    with client.session_transaction() as session:
        session.clear()
    assert client.get('/api/hyperliquid/account').status_code == 401
    assert client.post('/api/hyperliquid/connection', json={}).status_code == 401


def test_connection_is_scoped_to_session_and_never_enables_execution(client, monkeypatch):
    row = {'network': 'mainnet', 'account_address': ADDRESS}
    calls = fake_database(monkeypatch, row)
    result = client.post('/api/hyperliquid/connection', json=row)
    assert result.status_code == 200
    assert result.json['execution_enabled'] is False
    assert calls[0][1] == (7, 'mainnet', ADDRESS)
    assert calls[1][1] == (7,)
    result = client.post('/api/hyperliquid/connection', json={**row, 'user_id': 8})
    assert result.status_code == 400
    assert len(calls) == 2


def test_account_uses_saved_owner_address_and_info_only(client, monkeypatch):
    fake_database(monkeypatch, {'network': 'mainnet', 'account_address': ADDRESS})
    queries = []
    def info(network, payload):
        queries.append((network, payload))
        if payload['type'] == 'userAbstraction':
            return 'unifiedAccount'
        if payload['type'] == 'spotClearinghouseState':
            return {'balances': [{'coin': 'USDC', 'token': 0, 'total': '58.914823', 'hold': '0'}], 'tokenToAvailableAfterMaintenance': [[0, '58.914823']]}
        return {'marginSummary': {'accountValue': '20'}, 'assetPositions': []} if payload['type'] == 'clearinghouseState' else []
    monkeypatch.setattr(hl, 'info', info)
    response = client.get('/api/hyperliquid/account')
    assert response.status_code == 200
    assert response.json['execution_enabled'] is False
    assert response.json['spot_balances'][0]['total'] == '58.914823'
    assert response.json['margin']['accountValue'] == '20'
    assert response.json['trading_balance']['available'] == 58.914823
    assert queries == [('mainnet', {'type': name, 'user': ADDRESS}) for name in ['clearinghouseState', 'openOrders', 'spotClearinghouseState', 'userAbstraction']]


def test_account_unconfigured_and_upstream_failure(client, monkeypatch):
    fake_database(monkeypatch, None)
    assert client.get('/api/hyperliquid/account').status_code == 409
    fake_database(monkeypatch, {'network': 'mainnet', 'account_address': ADDRESS})
    def fail(*args):
        raise URLError('internal transport detail')
    monkeypatch.setattr(hl, 'info', fail)
    response = client.get('/api/hyperliquid/account')
    assert response.status_code == 502
    assert 'internal transport' not in response.text


def test_no_execution_route(client):
    assert client.post('/api/hyperliquid/orders', json={}).status_code in (404, 405)


def test_strategy_selection_persists_for_current_user_without_activation(client, monkeypatch):
    calls = fake_database(monkeypatch, {'strategy_key': 'channel_follow_15'})
    response = client.post('/api/hyperliquid/strategy', json={'strategy_key': 'channel_follow_15'})
    assert response.status_code == 200
    assert response.json['selected']['key'] == 'channel_follow_15'
    assert response.json['active_strategy'] is None
    assert response.json['execution_enabled'] is False
    assert calls[0][1] == ('channel_follow_15', 7)
    assert client.post('/api/hyperliquid/activate').status_code == 409


def test_strategy_selection_requires_connection_and_valid_key(client, monkeypatch):
    fake_database(monkeypatch, None)
    assert client.post('/api/hyperliquid/strategy', json={'strategy_key': 'channel_follow_15'}).status_code == 409
    assert client.post('/api/hyperliquid/strategy', json={'strategy_key': 'invented'}).status_code == 400
    assert client.post('/api/hyperliquid/strategy', json={'strategy_key': []}).status_code == 400


def test_network_permission_failure_is_actionable(client, monkeypatch):
    fake_database(monkeypatch, {'network': 'mainnet', 'account_address': ADDRESS})
    reason = OSError('socket denied')
    reason.winerror = 10013
    def fail(*args):
        raise URLError(reason)
    monkeypatch.setattr(hl, 'info', fail)
    response = client.get('/api/hyperliquid/account')
    assert response.status_code == 502
    assert 'permissão de acesso à rede' in response.json['error']


def test_emergency_close_requires_header_and_scopes_to_authenticated_user(client, monkeypatch):
    from app import execution_service
    calls = []
    monkeypatch.setattr(execution_service, 'emergency_close', lambda uid: calls.append(uid))
    monkeypatch.setattr(execution_service, 'status', lambda uid: {'run': None})
    url = '/api/hyperliquid/execution'
    assert client.post(url, json={'action': 'close_position'}).status_code == 403
    assert client.post(url, json={'action': 'close_position', 'user_id': 8},
                       headers={'X-IziCrypto-Setup': '1'}).status_code == 400
    assert calls == []
    response = client.post(url, json={'action': 'close_position'}, headers={'X-IziCrypto-Setup': '1'})
    assert response.status_code == 200
    assert calls == [7]
