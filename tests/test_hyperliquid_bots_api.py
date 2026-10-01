from contextlib import contextmanager
from types import SimpleNamespace

import pytest
import app.auth as auth
import app.hyperliquid_bot_service as bot_service
import app.hyperliquid_api as hl
from app.web import app


MASTER = "0x" + "a" * 40


def bot_row(bot_id, subaccount, market="BTC"):
    return {
        "id": bot_id,
        "user_id": 7,
        "name": f"Bot {bot_id}",
        "market": market,
        "coin": market,
        "network": "mainnet",
        "master_address": MASTER,
        "wallet_address": MASTER,
        "account_address": subaccount,
        "subaccount_name": f"Conta {bot_id}",
        "strategy_key": "strategy",
        "strategy_name": "Estratégia",
        "strategy_config": {},
        "capital_reserved": 500,
        "max_utilization_pct": 70,
        "leverage": 3,
        "sizing_mode": "fixed",
        "risk_limits": {"margin_per_trade_usdc": "125", "daily_loss_usdc": "250"},
        "status": "running",
        "created_at": None,
        "updated_at": None,
        "run_id": bot_id + 100,
        "run_active": True,
        "run_managing": True,
        "run_state": {"phase": "waiting"},
        "run_heartbeat": None,
        "run_created_at": None,
        "last_order_at": None,
    }


def runtime(status, reason=None):
    return {
        "account": {},
        "balance": {
            "equity": 500, "available": 400, "margin_used": 100,
            "margin_available": 400, "exposure": 15000, "synced_at": "sync",
        },
        "position": None,
        "orders": {
            "count": 0,
            "items": [],
            "protection": {
                "status": "not_applicable", "stop_price": None,
                "take_profit_price": None, "orders": [],
            },
        },
        "pnl": {
            "unrealized": 0, "realized_24h": None, "fees_24h": None,
            "funding_24h": None, "net_24h": None, "run": None,
            "realized_total": None, "fees_total": None, "funding_total": None,
            "bot_total": None, "basis": None,
        },
        "activity": {"last_fill_at": None, "last_order_at": None, "fills_24h": None},
        "strategy_state": {"phase": "waiting", "message": None, "last_signal": None, "last_candle_at": None},
        "health": {
            "status": status, "reason": reason, "worker_active": status == "healthy",
            "last_worker_at": None, "last_exchange_sync_at": "sync", "last_error": None,
            "exchange_connected": True, "exchange_synced": True,
            "position_protection": "not_applicable", "partial_data": False,
            "partial_data_reasons": [],
        },
        "run": {"id": None, "phase": "waiting", "active": True, "managing": True, "created_at": None},
    }


@pytest.fixture
def client(monkeypatch):
    app.secret_key = "hyperliquid-bot-test-secret"
    app.config["SESSION_COOKIE_SECURE"] = False
    monkeypatch.setattr(auth, "get_database_url", lambda: "postgresql://test")
    monkeypatch.setattr(auth, "get_active_user_by_id", lambda user_id: {"id": user_id})
    test_client = app.test_client()
    with test_client.session_transaction() as session:
        session["user_id"] = 7
    return test_client


def test_bots_endpoint_keeps_partial_exchange_failures_isolated(client, monkeypatch):
    rows = [bot_row(1, "0x" + "b" * 40), bot_row(2, "0x" + "c" * 40)]

    class Connection:
        def execute(self, _sql, _params):
            return self

        def fetchall(self):
            return rows

    @contextmanager
    def connect():
        yield Connection()

    def get_runtime(row, run):
        if row["id"] == 1:
            return runtime("healthy")
        failed = runtime("error", "exchange_timeout")
        failed["balance"] = None
        failed["position"] = None
        failed["orders"] = None
        return failed

    monkeypatch.setattr(hl, "_connect", connect)
    monkeypatch.setattr(bot_service, "get_bot_runtime_state", get_runtime)

    response = client.get("/api/hyperliquid/bots")

    assert response.status_code == 200
    bots = response.json["bots"]
    assert len(bots) == 2
    assert bots[0]["account_address"] == rows[0]["account_address"]
    assert bots[0]["health"]["status"] == "healthy"
    assert bots[1]["account_address"] == rows[1]["account_address"]
    assert bots[1]["health"]["status"] == "error"
    assert bots[1]["health"]["reason"] == "exchange_timeout"
    assert bots[1]["capital"]["balance"] is None
    assert bots[1]["pnl"]["net_24h"] is None
    assert "encrypted_key" not in bots[0]
    assert bots[0]["api_credential"] == {"configured": False, "valid_until": None}


def test_create_bot_uses_selected_strategy_name_when_name_is_omitted(client, monkeypatch):
    from app.strategy_research import real_execution_candidates

    strategy = real_execution_candidates()[0]
    subaccount = "0x" + "b" * 40
    saved_connection = {
        "network": "mainnet",
        "account_address": MASTER,
        "strategy_key": strategy.key,
        "risk_limits": {},
    }

    class Connection:
        def __init__(self):
            self.result = None
            self.insert_params = None

        def execute(self, sql, params=None):
            normalized = " ".join(sql.split())
            if "FROM hyperliquid_connections" in normalized:
                self.result = saved_connection
            elif "INSERT INTO hyperliquid_bots" in normalized:
                self.insert_params = params
                self.result = {"id": 22, "name": strategy.name}
            else:
                raise AssertionError(f"Unexpected query: {normalized}")
            return self

        def fetchone(self):
            return self.result

    connection = Connection()

    @contextmanager
    def connect():
        yield connection

    monkeypatch.setattr(hl, "_connect", connect)
    monkeypatch.setattr(hl, "_validate_bot_market", lambda *_args: None)
    monkeypatch.setattr(hl, "_validate_bot_configuration", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(hl, "_build_bot_payload", lambda row: row)

    response = client.post(
        "/api/hyperliquid/bots",
        json={"account_address": subaccount},
    )

    assert response.status_code == 201
    assert connection.insert_params[1] == strategy.name
    assert response.json["name"] == strategy.name


def test_bot_credential_is_encrypted_and_response_never_contains_secret(client, monkeypatch):
    bot = {
        "id": 8,
        "user_id": 7,
        "master_address": MASTER,
        "network": "mainnet",
    }
    updated = {}

    class Connection:
        def __init__(self):
            self.result = None

        def execute(self, sql, params=None):
            normalized = " ".join(sql.split())
            if normalized.startswith("SELECT * FROM hyperliquid_bots"):
                self.result = bot
            elif normalized.startswith("SELECT account_address, network FROM hyperliquid_connections"):
                self.result = {"account_address": MASTER, "network": "mainnet"}
            elif normalized.startswith("SELECT 1 FROM hyperliquid_runs"):
                self.result = None
            elif normalized.startswith("UPDATE hyperliquid_bots"):
                updated["params"] = params
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

    def enroll(key, owner, network, user_id):
        assert key == "private-user-key"
        assert (owner, network, user_id) == (MASTER, "mainnet", 7)
        return "0x" + "d" * 40, "ciphertext-only", 123456789

    monkeypatch.setattr(hl, "_connect", connect)
    monkeypatch.setattr("app.hyperliquid_setup.enroll_key", enroll)

    response = client.post(
        "/api/hyperliquid/bots/8/credential",
        json={"private_key": "private-user-key"},
        headers={"X-IziCrypto-Setup": "1"},
    )

    assert response.status_code == 200
    assert response.json == {
        "api_credential": {"configured": True, "valid_until": 123456789},
    }
    assert "private-user-key" not in response.get_data(as_text=True)
    assert "ciphertext-only" not in response.get_data(as_text=True)
    assert updated["params"] == ("0x" + "d" * 40, "ciphertext-only", 123456789, 8, 7)


def test_start_bot_requires_explicit_action_header(client, monkeypatch):
    import app.execution_service as execution_service

    calls = []
    monkeypatch.setattr(execution_service, "activate_bot", lambda user_id, bot_id: calls.append((user_id, bot_id)) or 91)

    rejected = client.post("/api/hyperliquid/bots/8/start", json={})
    assert rejected.status_code == 403
    assert calls == []

    response = client.post(
        "/api/hyperliquid/bots/8/start",
        json={},
        headers={"X-IziCrypto-Setup": "1"},
    )
    assert response.status_code == 201
    assert response.json["run_id"] == 91
    assert calls == [(7, 8)]


def test_update_bot_saves_operation_limits_and_daily_loss(client, monkeypatch):
    row = {
        "id": 8,
        "user_id": 7,
        "name": "Bot 8",
        "market": "BTC",
        "master_address": MASTER,
        "account_address": "0x" + "b" * 40,
        "strategy_key": "strategy",
        "strategy_config": {},
        "capital_reserved": 100,
        "max_utilization_pct": 100,
        "leverage": 2,
        "sizing_mode": "fixed",
        "risk_limits": {"margin_per_trade_usdc": 10, "daily_loss_usdc": 20},
        "metadata": {},
    }
    saved = {}

    class Connection:
        def __init__(self):
            self.result = None

        def execute(self, sql, params=None):
            normalized = " ".join(sql.split())
            if normalized.startswith("SELECT * FROM hyperliquid_bots WHERE user_id"):
                self.result = row
            elif normalized.startswith("SELECT 1 FROM hyperliquid_runs"):
                self.result = None
            elif normalized.startswith("SELECT account_address FROM hyperliquid_connections"):
                self.result = {"account_address": MASTER}
            elif normalized.startswith("UPDATE hyperliquid_bots SET"):
                saved["sql"] = normalized
                saved["params"] = params
                self.result = None
            elif normalized.startswith("SELECT * FROM hyperliquid_bots WHERE id"):
                self.result = row
            else:
                raise AssertionError(f"Unexpected query: {normalized}")
            return self

        def fetchone(self):
            return self.result

    connection = Connection()

    @contextmanager
    def connect():
        yield connection

    monkeypatch.setattr(hl, "_connect", connect)
    monkeypatch.setattr(hl, "_build_bot_payload", lambda value: value)

    response = client.patch(
        "/api/hyperliquid/bots/8",
        json={
            "capital_reserved": 300,
            "sizing_mode": "available_balance",
            "leverage": 8,
            "risk_limits": {
                "margin_per_trade_usdc": 0,
                "daily_loss_usdc": 35,
                "max_leverage": 8,
            },
        },
    )

    assert response.status_code == 200
    assert "capital_reserved=%s" in saved["sql"]
    assert "sizing_mode=%s" in saved["sql"]
    assert "leverage=%s" in saved["sql"]
    assert "risk_limits=%s" in saved["sql"]
    assert saved["params"][0] == 300
    assert saved["params"][1] == 8
    assert saved["params"][2] == "available_balance"
    assert saved["params"][3].obj["daily_loss_usdc"] == 35


def test_bot_market_catalog_comes_from_live_hyperliquid_meta(client, monkeypatch):
    class Connection:
        def execute(self, _sql, _params):
            return self

        def fetchone(self):
            return {"network": "mainnet"}

    @contextmanager
    def connect():
        yield Connection()

    monkeypatch.setattr(hl, "_connect", connect)
    monkeypatch.setattr(hl, "info", lambda network, _payload: {
        "universe": [
            {"name": "BTC"},
            {"name": "ETH"},
            {"name": "SOL"},
            {"name": "DOGE", "isDelisted": True},
        ]
    })

    response = client.get("/api/hyperliquid/bots/markets")

    assert response.status_code == 200
    assert response.json["markets"] == [
        {"symbol": "BTC", "label": "BTC / USDC"},
        {"symbol": "ETH", "label": "ETH / USDC"},
    ]


def test_bot_market_validation_rejects_unlisted_or_delisted_assets(monkeypatch):
    monkeypatch.setattr(hl, "info", lambda _network, _payload: {
        "universe": [
            {"name": "BTC"},
            {"name": "ETH", "isDelisted": True},
        ]
    })

    hl._validate_bot_market("mainnet", "BTC")
    with pytest.raises(ValueError, match="não está disponível"):
        hl._validate_bot_market("mainnet", "ETH")
    with pytest.raises(ValueError, match="BTC ou ETH"):
        hl._validate_bot_market("mainnet", "SOL")


def test_import_legacy_configuration_creates_a_stopped_bot(client, monkeypatch):
    from app.strategy_research import real_execution_candidates

    strategy = real_execution_candidates()[0]
    subaccount = "0x" + "b" * 40
    legacy_connection = {
        "network": "mainnet",
        "account_address": MASTER,
        "strategy_key": strategy.key,
        "risk_limits": {"capital_usdc": "250", "sizing_mode": "fixed", "max_leverage": "3"},
        "legacy_subaccount_address": None,
    }

    class Connection:
        def __init__(self):
            self.result = None
            self.insert_params = None
            self.updated_subaccount = None

        def execute(self, sql, params=None):
            normalized = " ".join(sql.split())
            if "FROM hyperliquid_connections" in normalized and "FOR UPDATE" in normalized:
                self.result = legacy_connection
            elif "SELECT id, user_id, status FROM hyperliquid_bots" in normalized:
                self.result = None
            elif "INSERT INTO hyperliquid_bots" in normalized:
                self.insert_params = params
                self.result = {"id": 41, "status": "stopped"}
            elif "UPDATE hyperliquid_connections" in normalized:
                self.updated_subaccount = params[0]
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

    monkeypatch.setattr(hl, "_connect", connect)
    monkeypatch.setattr(hl, "_validate_bot_configuration", lambda *_args, **_kwargs: None)

    response = client.post(
        "/api/hyperliquid/bots/import-legacy",
        json={"subaccount_address": subaccount},
    )

    assert response.status_code == 201
    assert response.json == {"status": "imported", "bot": {"id": 41, "status": "stopped"}}
    assert connection.insert_params[5] == subaccount
    assert connection.insert_params[6] == subaccount
    assert connection.insert_params[10] == 250.0
    assert connection.insert_params[11] == 3
    assert connection.updated_subaccount == subaccount


def test_import_legacy_configuration_is_idempotent_for_saved_subaccount(client, monkeypatch):
    subaccount = "0x" + "b" * 40
    legacy_connection = {
        "network": "mainnet",
        "account_address": MASTER,
        "strategy_key": "unused",
        "risk_limits": {},
        "legacy_subaccount_address": subaccount,
    }

    class Connection:
        def __init__(self):
            self.result = None

        def execute(self, sql, _params=None):
            normalized = " ".join(sql.split())
            if "FROM hyperliquid_connections" in normalized and "FOR UPDATE" in normalized:
                self.result = legacy_connection
            elif "SELECT id, user_id, status FROM hyperliquid_bots" in normalized:
                self.result = {"id": 41, "user_id": 7, "status": "stopped"}
            elif "UPDATE hyperliquid_connections" in normalized:
                self.result = None
            else:
                raise AssertionError(f"Unexpected query: {normalized}")
            return self

        def fetchone(self):
            return self.result

    @contextmanager
    def connect():
        yield Connection()

    monkeypatch.setattr(hl, "_connect", connect)

    response = client.post("/api/hyperliquid/bots/import-legacy", json={})

    assert response.status_code == 200
    assert response.json == {"status": "already_imported", "bot": {"id": 41, "status": "stopped"}}


def test_bot_payload_does_not_expose_wallet_balance_as_subaccount_balance(monkeypatch):
    row = bot_row(3, "0x" + "d" * 40)
    runtime_data = runtime("error", "subaccount_not_found")
    runtime_data["balance"] = None
    runtime_data["position"] = None
    runtime_data["orders"] = None
    monkeypatch.setattr(bot_service, "get_bot_runtime_state", lambda _row, _run: runtime_data)

    result = hl._build_bot_payload(row)

    assert result["wallet"] == MASTER
    assert result["subaccount"] == row["account_address"]
    assert result["capital"]["balance"] is None
    assert result["position"] is None
    assert result["health"]["reason"] == "subaccount_not_found"
    assert result["sizing_mode"] == "fixed"
    assert result["risk_limits"]["margin_per_trade_usdc"] == "125"


def test_start_blocker_explains_subaccount_not_linked_to_master(monkeypatch):
    row = bot_row(3, "0x" + "d" * 40)
    row.update(
        status="stopped",
        run_id=None,
        run_active=False,
        run_managing=False,
        agent_address="0x" + "e" * 40,
        encrypted_key="encrypted",
    )
    runtime_data = runtime("error", "subaccount_not_found")
    runtime_data["balance"] = None
    runtime_data["pnl"]["bot_total"] = None
    monkeypatch.setattr(bot_service, "get_bot_runtime_state", lambda _row, _run: runtime_data)
    monkeypatch.setattr("app.execution_service.enabled", lambda _network: True)
    monkeypatch.setattr(hl, "real_execution_candidates", lambda: [SimpleNamespace(key="strategy")])

    result = hl._build_bot_payload(row)

    assert result["can_start"] is False
    assert result["start_blocker"] == (
        "A subconta cadastrada não foi encontrada nesta wallet principal. "
        "Confirme a wallet principal ou selecione uma subconta criada por ela."
    )


def test_bot_configuration_accepts_initial_bankroll_and_fixed_entry_amount():
    payload = {
        "master_address": MASTER,
        "account_address": "0x" + "b" * 40,
        "network": "mainnet",
        "max_utilization_pct": 100,
        "capital_reserved": 500,
        "leverage": 3,
        "sizing_mode": "fixed",
        "risk_limits": {"margin_per_trade_usdc": "125"},
    }

    hl._validate_bot_configuration(payload)


def test_available_balance_sizing_does_not_require_a_fixed_entry_amount():
    payload = {
        "master_address": MASTER,
        "account_address": "0x" + "b" * 40,
        "network": "mainnet",
        "max_utilization_pct": 100,
        "capital_reserved": 500,
        "leverage": 3,
        "sizing_mode": "available_balance",
        "risk_limits": {},
    }

    hl._validate_bot_configuration(payload)


def test_bot_payload_calculates_current_bankroll_from_realized_lifetime_pnl(monkeypatch):
    row = bot_row(3, "0x" + "d" * 40)
    runtime_data = runtime("stopped")
    runtime_data["pnl"]["bot_total"] = 6.3
    runtime_data["pnl"]["realized_total"] = 7
    runtime_data["pnl"]["fees_total"] = 0.5
    runtime_data["pnl"]["funding_total"] = -0.2
    monkeypatch.setattr(bot_service, "get_bot_runtime_state", lambda _row, _run: runtime_data)

    result = hl._build_bot_payload(row)

    assert result["capital"]["initial_bankroll"] == 500
    assert result["capital"]["current_bankroll"] == pytest.approx(506.3)
    assert result["pnl"]["realized_total"] == 7
    assert result["pnl"]["fees_total"] == 0.5
    assert result["pnl"]["funding_total"] == -0.2
    assert result["pnl"]["bot_total"] == pytest.approx(6.3)


def test_bot_payload_leaves_current_bankroll_unavailable_when_history_is_unavailable(monkeypatch):
    row = bot_row(3, "0x" + "d" * 40)
    runtime_data = runtime("warning", "partial_exchange_data")
    monkeypatch.setattr(bot_service, "get_bot_runtime_state", lambda _row, _run: runtime_data)

    result = hl._build_bot_payload(row)

    assert result["capital"]["initial_bankroll"] == 500
    assert result["capital"]["current_bankroll"] is None
