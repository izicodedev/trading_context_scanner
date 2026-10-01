import json

import app.execution_broker as execution_broker


MASTER = "0x" + "a" * 40
SUBACCOUNT = "0x" + "b" * 40
AGENT = "0x" + "c" * 40


def test_bot_broker_uses_master_for_agent_and_subaccount_as_vault(monkeypatch):
    now = 1_800_000_000_000

    class Cipher:
        def decrypt(self, _token):
            return json.dumps({
                "owner": MASTER,
                "network": "mainnet",
                "user_id": 7,
                "key": "test-key",
            }).encode()

    class Wallet:
        address = AGENT

    class Info:
        def extra_agents(self, address):
            assert address == MASTER
            return [{"address": AGENT, "validUntil": now + 10_000}]

    exchange_arguments = {}

    class Exchange:
        def __init__(self, wallet, url, **kwargs):
            exchange_arguments.update(wallet=wallet, url=url, **kwargs)
            self.info = Info()

    monkeypatch.setattr(execution_broker, "cipher", lambda: Cipher())
    monkeypatch.setattr(execution_broker.Account, "from_key", lambda _key: Wallet())
    monkeypatch.setattr(execution_broker, "Exchange", Exchange)
    monkeypatch.setattr(execution_broker.time, "time", lambda: now / 1000)

    broker = execution_broker.Broker({
        "user_id": 7,
        "bot_id": 12,
        "network": "mainnet",
        "master_address": MASTER,
        "account_address": SUBACCOUNT,
        "agent_address": AGENT,
        "encrypted_key": "encrypted",
        "market": "BTC",
    })
    broker.authorized()

    assert broker.owner == SUBACCOUNT
    assert broker.credential_owner == MASTER
    assert exchange_arguments["account_address"] == MASTER
    assert exchange_arguments["vault_address"] == SUBACCOUNT
