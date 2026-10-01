from contextlib import contextmanager
from datetime import datetime, timezone

import app.execution_service as execution_service
import app.hyperliquid_bot_service as bot_service
from app.strategy_research import real_execution_candidates


MASTER = "0x" + "a" * 40
SUBACCOUNT = "0x" + "b" * 40
AGENT = "0x" + "c" * 40


def test_activate_bot_builds_isolated_run_and_uses_live_bankroll(monkeypatch):
    strategy = real_execution_candidates()[0]
    bot = {
        "id": 12,
        "user_id": 7,
        "network": "mainnet",
        "master_address": MASTER,
        "connection_master": MASTER,
        "connection_network": "mainnet",
        "account_address": SUBACCOUNT,
        "agent_address": AGENT,
        "encrypted_key": "encrypted-agent",
        "market": "BTC",
        "strategy_key": strategy.key,
        "capital_reserved": 500,
        "sizing_mode": "available_balance",
        "risk_limits": {"daily_loss_usdc": "40", "max_leverage": "5"},
        "leverage": 5,
        "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
    }

    class Connection:
        def __init__(self):
            self.run_configuration = None
            self.result = None

        def execute(self, sql, params=None):
            normalized = " ".join(sql.split())
            if "FROM hyperliquid_bots b" in normalized and "FOR UPDATE OF b" in normalized:
                self.result = bot
            elif "FROM hyperliquid_runs" in normalized and "FOR UPDATE" in normalized:
                self.result = None
            elif normalized.startswith("INSERT INTO hyperliquid_runs"):
                self.run_configuration = params
                self.result = {"id": 91}
            elif normalized.startswith("UPDATE hyperliquid_bots"):
                self.result = None
            else:
                raise AssertionError(f"Unexpected query: {normalized}")
            return self

        def fetchone(self):
            return self.result

    connection = Connection()

    @contextmanager
    def connect():
        yield connection

    class Broker:
        def __init__(self, config):
            self.config = config
            self.authorized_called = False

        def authorized(self):
            self.authorized_called = True

        def account(self):
            return [], [], 500, 400

    monkeypatch.setattr(execution_service, "_connect", connect)
    monkeypatch.setattr(execution_service, "enabled", lambda _network: True)
    monkeypatch.setattr("app.execution_broker.Broker", Broker)
    monkeypatch.setattr(bot_service, "get_bot_realized_lifetime_pnl", lambda _bot: 25)
    monkeypatch.setattr(bot_service.bot_service, "_verify_subaccount", lambda *_args: None)

    run_id = execution_service.activate_bot(7, 12)

    assert run_id == 91
    _, network, account_address, bot_id, configuration_json, _ = connection.run_configuration
    configuration = configuration_json.obj
    assert (network, account_address, bot_id) == ("mainnet", SUBACCOUNT, 12)
    assert configuration["master_address"] == MASTER
    assert configuration["account_address"] == SUBACCOUNT
    assert configuration["agent_address"] == AGENT
    assert configuration["strategy"]["key"] == strategy.key
    assert configuration["capital_reserved"] == 500
    assert configuration["limits"]["capital_usdc"] == "525.0"
