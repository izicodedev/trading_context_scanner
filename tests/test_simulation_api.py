import pytest
import pandas as pd
import psycopg

import app.auth as auth
import app.simulation_api as simulation_api
from app.web import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(app.config, "SECRET_KEY", "simulator-test-secret")
    monkeypatch.setitem(app.config, "SESSION_COOKIE_SECURE", False)
    monkeypatch.setattr(auth, "get_database_url", lambda: "postgresql://test")
    monkeypatch.setattr(auth, "get_active_user_by_id", lambda user_id: {"id": user_id})
    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = 1
    return client


def payload():
    return {
        "data_source": "manual",
        "trade": {"symbol": "BTCUSDT", "timeframe": "15m", "side": "LONG",
                  "entry_price": 84000, "entry_time": "2026-01-01T00:00:00Z",
                  "stop_price": 83160, "target_price": 86520},
        "config": {"max_candles": 1, "ambiguity_policy": "conservative"},
        "candles": [{"open_time": "2026-01-01T00:00:00Z", "close_time": "2026-01-01T00:14:59.999Z",
                     "open": 84000, "high": 87000, "low": 83500, "close": 86000}],
    }


def test_requires_session(client):
    with client.session_transaction() as session:
        session.clear()
    assert client.post("/api/simulator", json=payload()).status_code == 401
    assert client.get("/api/simulator/strategies").status_code == 401
    assert client.post("/api/simulator/selection", json={"strategy_keys": []}).status_code == 401


def test_custom_strategy_endpoints_are_user_scoped(client, monkeypatch):
    seen = []
    monkeypatch.setattr(simulation_api.user_strategies, "catalog", lambda user_id, symbol: {"strategies": [], "selected_keys": []})
    def create(user_id, definition):
        seen.append((user_id, definition["name"]))
        return {"key": "custom_123", "name": definition["name"]}
    def choose(user_id, keys, symbol):
        seen.append((user_id, keys, symbol))
        return keys
    monkeypatch.setattr(simulation_api.user_strategies, "create", create)
    monkeypatch.setattr(simulation_api.user_strategies, "choose", choose)
    assert client.get("/api/simulator/strategies").get_json()["selected_keys"] == []
    assert client.post("/api/simulator/strategies", json={"name": "Minha regra"}).status_code == 201
    assert client.post("/api/simulator/selection", json={"strategy_keys": ["custom_123"]}).get_json()["selected_keys"] == ["custom_123"]
    assert seen == [(1, "Minha regra"), (1, ["custom_123"], "BTCUSDT")]
    assert client.post("/api/simulator/selection", json={"bad": 1}).status_code == 400


def test_simulation_serializes_result(client):
    response = client.post("/api/simulator", json=payload())
    assert response.status_code == 200
    result = response.get_json()
    assert result["status"] == "TARGET"
    assert result["price_return_pct"] == pytest.approx(3)
    assert result["duration_seconds"] == pytest.approx(899.999)
    assert result["entry_time"].endswith("+00:00")


def test_ambiguity_policy_reaches_engine(client):
    data = payload()
    data["candles"][0]["low"] = 83000
    data["config"]["ambiguity_policy"] = "unresolved"
    result = client.post("/api/simulator", json=data).get_json()
    assert result["status"] == "AMBIGUOUS" and result["ambiguous"]
    assert result["exit_price"] is None


@pytest.mark.parametrize("data", [None, [], {}, {"candles": [1]}, {"candles": [{}], "trade": []}])
def test_invalid_requests(client, data):
    response = client.post("/api/simulator", json=data)
    assert response.status_code == 400 and "error" in response.get_json()


def test_limits_and_bad_prices(client):
    data = payload()
    data["config"]["max_candles"] = 5001
    assert client.post("/api/simulator", json=data).status_code == 400
    data = payload()
    data["trade"]["stop_price"] = 85000
    assert client.post("/api/simulator", json=data).status_code == 400
    assert client.post("/api/simulator", data=" " * 2_000_001,
                       content_type="application/json").status_code == 413


def test_database_is_default_and_manual_candles_are_not_used(client, monkeypatch):
    data = payload()
    del data["data_source"]
    stored = pd.DataFrame(data["candles"])
    data["candles"] = []
    calls = []
    def load(*args):
        calls.append(args)
        return stored
    monkeypatch.setattr(simulation_api, "load_candles", load)
    response = client.post("/api/simulator", json=data)
    assert response.status_code == 200
    result = response.get_json()
    assert result["data_source"] == "database" and result["status"] == "TARGET"
    assert calls == [("BTCUSDT", "15m", "2026-01-01T00:00:00Z", 1, "binance_spot")]


def test_missing_history_is_explicit(client, monkeypatch):
    def missing(*args):
        raise ValueError("Não há candles fechados no banco")
    monkeypatch.setattr(simulation_api, "load_candles", missing)
    data = payload()
    data["data_source"] = "database"
    response = client.post("/api/simulator", json=data)
    assert response.status_code == 400 and "Não há candles" in response.get_json()["error"]


def test_datasets_are_serialized_and_require_auth(client, monkeypatch):
    monkeypatch.setattr(simulation_api, "available_datasets", lambda: [{
        "source": "binance_spot", "symbol": "BTCUSDT", "timeframe": "15m", "candles": 2,
        "start_time": pd.Timestamp("2026-01-01T00:00:00Z"),
        "end_time": pd.Timestamp("2026-01-01T00:29:59Z"), "first_open": 84000,
    }])
    response = client.get("/api/simulator/datasets")
    assert response.status_code == 200
    assert response.get_json()[0]["start_time"].endswith("+00:00")
    with client.session_transaction() as session:
        session.clear()
    assert client.get("/api/simulator/datasets").status_code == 401


def test_database_errors_do_not_expose_connection_details(client, monkeypatch):
    def unavailable():
        raise psycopg.OperationalError("private connection details")
    monkeypatch.setattr(simulation_api, "available_datasets", unavailable)
    response = client.get("/api/simulator/datasets")
    assert response.status_code == 503
    assert "private" not in response.get_data(as_text=True)


def test_live_control_is_user_scoped_and_requires_boolean(client, monkeypatch):
    calls = []
    monkeypatch.setattr(simulation_api.lab_service, "start", lambda user, symbol: calls.append(("start", user, symbol)))
    monkeypatch.setattr(simulation_api.lab_service, "advance", lambda user, stopping, symbol: calls.append(("stop", user, symbol)))
    monkeypatch.setattr(simulation_api.lab_service, "status", lambda user, symbol: {"active": True, "symbol": symbol})
    assert client.post("/api/simulator/live", json={"active": "true"}).status_code == 400
    assert client.post("/api/simulator/live", json={"active": True, "user_id": 999}).status_code == 200
    assert client.post("/api/simulator/live", json={"active": False}).status_code == 200
    assert calls == [("start", 1, "BTCUSDT"), ("stop", 1, "BTCUSDT")]
    assert client.post("/api/simulator/live", json={"active": True, "symbol": "ETHUSDT"}).get_json()["symbol"] == "ETHUSDT"
    assert calls[-1] == ("start", 1, "ETHUSDT")
    with client.session_transaction() as session:
        session.clear()
    assert client.get("/api/simulator/live").status_code == 401
    assert client.post("/api/simulator/live", json={"active": True}).status_code == 401
