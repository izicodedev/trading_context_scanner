from datetime import datetime, timedelta, timezone

import pytest

from app.hyperliquid_bot_service import HyperliquidBotService


MASTER = "0x" + "a" * 40
SUB_A = "0x" + "b" * 40
SUB_B = "0x" + "c" * 40
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)


def bot(account_address, market="BTC", status="running"):
    return {
        "id": 1,
        "network": "mainnet",
        "master_address": MASTER,
        "account_address": account_address,
        "subaccount_name": account_address[-4:],
        "market": market,
        "status": status,
        "created_at": NOW - timedelta(minutes=20),
    }


def open_run(now=NOW, phase="open", side="LONG", quantity=0.25):
    return {
        "id": 42,
        "active": True,
        "managing": True,
        "heartbeat": now - timedelta(seconds=5),
        "created_at": now - timedelta(minutes=20),
        "state": {"phase": phase, "side": side, "quantity": quantity},
    }


def state(position=None, equity="527.35", margin="84.20", withdrawable="443.15"):
    return {
        "marginSummary": {
            "accountValue": equity,
            "totalMarginUsed": margin,
            "totalNtlPos": "21000" if position else "0",
        },
        "withdrawable": withdrawable,
        "assetPositions": [{"position": position}] if position else [],
    }


def position(side=1, coin="BTC", pnl="12", size="0.25"):
    return {
        "coin": coin,
        "szi": str(side * float(size)),
        "entryPx": "84000",
        "markPx": "84048",
        "positionValue": "21012",
        "leverage": {"value": 5},
        "marginUsed": "84.20",
        "unrealizedPnl": pnl,
        "returnOnEquity": "0.1425",
        "liquidationPx": "68000",
    }


def stop_and_target():
    return [
        {
            "coin": "BTC", "side": "A", "sz": "0.25", "limitPx": "80000",
            "triggerPx": "80000", "isTrigger": True, "reduceOnly": True,
            "triggerCondition": "Price below 80000", "orderType": "Stop Market", "oid": 10,
        },
        {
            "coin": "BTC", "side": "A", "sz": "0.25", "limitPx": "90000",
            "triggerPx": "90000", "isTrigger": True, "reduceOnly": True,
            "triggerCondition": "Price above 90000", "orderType": "Take Profit Market", "oid": 11,
        },
    ]


def mock_info(accounts, *, failure_addresses=()):
    calls = []

    def info(network, payload):
        calls.append((network, payload))
        address = payload.get("user")
        kind = payload["type"]
        if kind == "subAccounts":
            return [{"subAccountUser": account} for account in accounts]
        if address in failure_addresses:
            raise TimeoutError("upstream timeout")
        snapshot = accounts[address]
        if kind == "clearinghouseState":
            return snapshot["state"]
        if kind == "openOrders":
            return snapshot.get("orders", [])
        if kind == "userAbstraction":
            return snapshot.get("mode", "default")
        if kind == "spotClearinghouseState":
            return snapshot["spot"]
        if kind == "userFillsByTime":
            result = snapshot.get("fills", [])
            if result is None:
                raise TimeoutError("history timeout")
            return result
        if kind == "userFunding":
            result = snapshot.get("funding", [])
            if result is None:
                raise TimeoutError("history timeout")
            return result
        raise AssertionError(kind)

    return info, calls


def test_same_market_positions_are_isolated_by_subaccount():
    position_a = position(side=1, pnl="12")
    position_b = position(side=-1, pnl="-7")
    info, calls = mock_info({
        MASTER: {},
        SUB_A: {"state": state(position_a), "orders": stop_and_target()},
        SUB_B: {"state": state(position_b), "orders": []},
    })
    service = HyperliquidBotService(info_client=info)

    result_a = service.runtime_state(bot(SUB_A), open_run(), NOW)
    result_b = service.runtime_state(bot(SUB_B), open_run(side="SHORT"), NOW)

    assert result_a["position"]["side"] == "LONG"
    assert result_a["position"]["unrealized_pnl"] == 12
    assert result_a["orders"]["protection"]["status"] == "protected"
    assert result_b["position"]["side"] == "SHORT"
    assert result_b["position"]["unrealized_pnl"] == -7
    assert result_b["orders"]["protection"]["status"] == "unprotected"
    assert {payload["user"] for _, payload in calls if payload["type"] == "clearinghouseState"} == {SUB_A, SUB_B}


def test_subaccount_balance_and_position_fields_are_exchange_values():
    info, _ = mock_info({
        MASTER: {},
        SUB_A: {"state": state(position()), "orders": stop_and_target()},
    })
    runtime = HyperliquidBotService(info_client=info).runtime_state(bot(SUB_A), open_run(), NOW)

    assert runtime["balance"] == {
        "equity": 527.35,
        "available": 443.15,
        "margin_used": 84.2,
        "margin_available": 443.15,
        "exposure": 21000,
        "source": "perps_usdc",
        "synced_at": NOW.isoformat(),
    }
    assert runtime["position"]["entry_price"] == 84000
    assert runtime["position"]["mark_price"] == 84048
    assert runtime["position"]["position_value"] == 21012
    assert runtime["position"]["leverage"] == 5
    assert runtime["position"]["return_on_equity_pct"] == pytest.approx(14.25)
    assert runtime["position"]["liquidation_price"] == 68000


def test_unified_subaccount_balance_uses_spot_maintenance_availability():
    info, calls = mock_info({
        MASTER: {},
        SUB_A: {
            "state": state(position(), equity="20", margin="2", withdrawable="1"),
            "orders": stop_and_target(),
            "mode": "unifiedAccount",
            "spot": {
                "balances": [{"coin": "USDC", "token": 0, "total": "527.35", "hold": "1"}],
                "tokenToAvailableAfterMaintenance": [[0, "443.15"]],
            },
        },
    })
    runtime = HyperliquidBotService(info_client=info).runtime_state(bot(SUB_A), open_run(), NOW)

    assert runtime["balance"]["equity"] == 527.35
    assert runtime["balance"]["available"] == 443.15
    assert runtime["balance"]["margin_used"] == 2
    assert runtime["balance"]["source"] == "unified_usdc"
    assert any(payload["type"] == "spotClearinghouseState" and payload["user"] == SUB_A for _, payload in calls)


def test_subaccount_must_belong_to_master_and_never_falls_back():
    info, calls = mock_info({MASTER: {}, SUB_A: {"state": state(), "orders": []}})
    service = HyperliquidBotService(info_client=info)

    missing = service.runtime_state(bot(SUB_B), open_run(), NOW)
    master = service.runtime_state(bot(MASTER), open_run(), NOW)

    assert missing["health"]["reason"] == "subaccount_not_found"
    assert master["health"]["reason"] == "subaccount_is_master"
    assert not any(payload["type"] == "clearinghouseState" for _, payload in calls)


def test_null_subaccounts_response_means_configured_address_is_not_a_child_account():
    info, calls = mock_info({MASTER: {}, SUB_A: {"state": state(), "orders": []}})

    def info_without_subaccounts(network, payload):
        if payload["type"] == "subAccounts":
            calls.append((network, payload))
            return None
        return info(network, payload)

    result = HyperliquidBotService(info_client=info_without_subaccounts).runtime_state(
        bot(SUB_A), open_run(), NOW,
    )

    assert result["health"]["reason"] == "subaccount_not_found"
    assert not any(payload["type"] == "clearinghouseState" for _, payload in calls)


def test_empty_position_is_null_and_unavailable_history_is_null():
    info, _ = mock_info({
        MASTER: {},
        SUB_A: {"state": state(), "orders": [], "fills": None},
    })
    runtime = HyperliquidBotService(info_client=info).runtime_state(
        bot(SUB_A), open_run(phase="waiting"), NOW,
    )
    assert runtime["position"] is None
    assert runtime["pnl"]["unrealized"] == 0
    assert runtime["pnl"]["realized_24h"] is None
    assert runtime["health"]["status"] == "warning"


def test_malformed_optional_history_does_not_discard_exchange_snapshot():
    info, _ = mock_info({
        MASTER: {},
        SUB_A: {"state": state(), "orders": []},
    })

    def malformed_history(network, payload):
        if payload["type"] in {"userFillsByTime", "userFunding"}:
            return {"unexpected": "shape"}
        return info(network, payload)

    runtime = HyperliquidBotService(info_client=malformed_history).runtime_state(
        bot(SUB_A), open_run(phase="waiting"), NOW,
    )

    assert runtime["balance"]["equity"] == 527.35
    assert runtime["pnl"]["realized_24h"] is None
    assert runtime["pnl"]["funding_24h"] is None
    assert runtime["pnl"]["net_24h"] is None
    assert runtime["health"]["partial_data"] is True


def test_bot_pnl_totals_include_gross_fees_and_funding_since_creation():
    info, _ = mock_info({
        MASTER: {},
        SUB_A: {
            "state": state(position(pnl="-2.5")),
            "orders": stop_and_target(),
            "fills": [
                {"closedPnl": "10", "fee": "0.4", "time": NOW_MS - 1000},
                {"closedPnl": "-3", "fee": "0.1", "time": NOW_MS - 500},
            ],
            "funding": [{"delta": {"usdc": "-0.2"}, "time": NOW_MS - 200}],
        },
    })
    runtime = HyperliquidBotService(info_client=info).runtime_state(bot(SUB_A), open_run(), NOW)

    assert runtime["pnl"]["unrealized"] == -2.5
    assert runtime["pnl"]["realized_24h"] == 7
    assert runtime["pnl"]["fees_24h"] == 0.5
    assert runtime["pnl"]["funding_24h"] == -0.2
    assert runtime["pnl"]["net_24h"] == 6.3
    assert runtime["pnl"]["realized_total"] == pytest.approx(7)
    assert runtime["pnl"]["fees_total"] == pytest.approx(0.5)
    assert runtime["pnl"]["funding_total"] == pytest.approx(-0.2)
    assert runtime["pnl"]["bot_total"] == pytest.approx(6.3)
    assert runtime["pnl"]["basis"] == "hyperliquid_realized_fills_and_funding_since_bot_creation"
    assert runtime["activity"]["last_fill_at"] == datetime.fromtimestamp((NOW_MS - 500) / 1000, timezone.utc).isoformat()


def test_health_reports_worker_lag_exchange_timeout_divergence_and_unprotected_position():
    healthy_info, _ = mock_info({
        MASTER: {},
        SUB_A: {"state": state(position()), "orders": stop_and_target()},
    })
    healthy = HyperliquidBotService(info_client=healthy_info).runtime_state(bot(SUB_A), open_run(), NOW)
    assert healthy["health"]["status"] == "healthy"

    delayed = HyperliquidBotService(info_client=healthy_info).runtime_state(
        bot(SUB_A), open_run(now=NOW - timedelta(seconds=40)), NOW,
    )
    assert delayed["health"]["status"] == "warning"
    assert delayed["health"]["reason"] == "worker_heartbeat_delayed"

    stale = HyperliquidBotService(info_client=healthy_info).runtime_state(
        bot(SUB_A), open_run(now=NOW - timedelta(seconds=130)), NOW,
    )
    assert stale["health"]["status"] == "error"
    assert stale["health"]["reason"] == "worker_heartbeat_stale"

    timeout_info, _ = mock_info({MASTER: {}, SUB_A: {}}, failure_addresses=(SUB_A,))
    timeout = HyperliquidBotService(info_client=timeout_info).runtime_state(bot(SUB_A), open_run(), NOW)
    assert timeout["health"]["status"] == "error"
    assert timeout["health"]["reason"] == "exchange_timeout"

    mismatch = HyperliquidBotService(info_client=healthy_info).runtime_state(
        bot(SUB_A), open_run(phase="waiting"), NOW,
    )
    assert mismatch["health"]["status"] == "error"
    assert mismatch["health"]["reason"] == "unmanaged_exchange_position"

    side_mismatch = HyperliquidBotService(info_client=healthy_info).runtime_state(
        bot(SUB_A), open_run(side="SHORT"), NOW,
    )
    assert side_mismatch["health"]["status"] == "error"
    assert side_mismatch["health"]["reason"] == "local_exchange_position_side_mismatch"

    unprotected_info, _ = mock_info({
        MASTER: {},
        SUB_A: {"state": state(position()), "orders": []},
    })
    unprotected = HyperliquidBotService(info_client=unprotected_info).runtime_state(bot(SUB_A), open_run(), NOW)
    assert unprotected["health"]["status"] == "warning"
    assert unprotected["health"]["reason"] == "position_without_stop"

    other_market_state = state(position())
    other_market_state["assetPositions"].append({"position": position(coin="ETH")})
    other_market_info, _ = mock_info({
        MASTER: {},
        SUB_A: {"state": other_market_state, "orders": stop_and_target()},
    })
    other_market = HyperliquidBotService(info_client=other_market_info).runtime_state(
        bot(SUB_A), open_run(), NOW,
    )
    assert other_market["health"]["status"] == "error"
    assert other_market["health"]["reason"] == "exchange_position_on_unconfigured_market"


def test_subaccount_and_runtime_snapshots_are_cached_briefly():
    info, calls = mock_info({
        MASTER: {},
        SUB_A: {"state": state(), "orders": []},
    })
    service = HyperliquidBotService(info_client=info)
    service.runtime_state(bot(SUB_A, status="stopped"), None, NOW)
    first_count = len(calls)
    service.runtime_state(bot(SUB_A, status="stopped"), None, NOW)
    assert len(calls) == first_count
