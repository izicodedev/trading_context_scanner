"""Read-only, subaccount-scoped Hyperliquid runtime state for trading bots."""

from __future__ import annotations

import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.error import URLError


_QUERY_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="hyperliquid-info")
_DEFAULT_CACHE_SECONDS = 8
_SUBACCOUNT_CACHE_SECONDS = 60
_LIFETIME_PNL_CACHE_SECONDS = 60
_HISTORY_WINDOW_MS = 24 * 60 * 60 * 1000
_MAX_HISTORY_RECORDS = 2000
_CACHE_MAX_ENTRIES = 2048
_HEARTBEAT_WARNING_SECONDS = 30
_HEARTBEAT_ERROR_SECONDS = 120


class RuntimeQueryError(Exception):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def _number(value):
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _exchange_time(value):
    timestamp = _number(value)
    if timestamp is None:
        return _iso(value)
    try:
        return datetime.fromtimestamp(timestamp / 1000, timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _market_key(value):
    key = str(value or "").strip().upper().replace("-PERP", "").replace("/PERP", "")
    if key.endswith("USDT"):
        key = key[:-4]
    elif key.endswith("USD"):
        key = key[:-3]
    return key


def _list_payload(value, reason):
    if not isinstance(value, list):
        raise RuntimeQueryError(reason, "Unexpected Hyperliquid response.")
    return value


def _subaccounts_addresses(response):
    if response is None:
        return set()
    if not isinstance(response, list):
        raise RuntimeQueryError("invalid_subaccount_response", "Invalid subaccount response.")
    addresses = set()
    for item in response:
        if not isinstance(item, dict):
            continue
        address = item.get("subAccountUser") or item.get("address")
        if isinstance(address, str):
            addresses.add(address.lower())
    return addresses


def _extract_positions(state):
    rows = state.get("assetPositions")
    if not isinstance(rows, list):
        raise RuntimeQueryError("invalid_account_state", "Positions are missing from the exchange response.")
    positions = []
    for row in rows:
        position = row.get("position") if isinstance(row, dict) else None
        if isinstance(position, dict) and _number(position.get("szi")) not in (None, 0):
            positions.append(position)
    return positions


def _is_trigger_order(order):
    return bool(
        order.get("isTrigger")
        or order.get("triggerPx") is not None
        or "stop" in str(order.get("orderType", "")).lower()
        or "take profit" in str(order.get("orderType", "")).lower()
    )


def _classify_protection(order, side, entry_price):
    order_type = str(order.get("orderType", "")).lower()
    condition = str(order.get("triggerCondition", "")).lower()
    trigger = _number(order.get("triggerPx") or order.get("limitPx"))
    if not order.get("reduceOnly") or not _is_trigger_order(order):
        return None, trigger
    if "take profit" in order_type or "takeprofit" in order_type:
        return "take_profit", trigger
    if "stop" in order_type:
        return "stop", trigger
    if trigger is not None and entry_price is not None:
        is_above = "above" in condition or ">=" in condition
        is_below = "below" in condition or "<=" in condition
        if is_above:
            return ("take_profit" if side == "LONG" else "stop"), trigger
        if is_below:
            return ("stop" if side == "LONG" else "take_profit"), trigger
        if side == "LONG":
            return ("stop" if trigger < entry_price else "take_profit"), trigger
        return ("take_profit" if trigger < entry_price else "stop"), trigger
    return "unknown", trigger


def _position_for_market(positions, market):
    wanted = _market_key(market)
    return next((item for item in positions if _market_key(item.get("coin")) == wanted), None)


def _protection_state(orders, market, position):
    matching = [
        order for order in orders
        if isinstance(order, dict)
        and _market_key(order.get("coin")) == _market_key(market)
    ]
    if position is None:
        return dict(status="not_applicable", stop_price=None, take_profit_price=None, orders=matching)

    signed_size = _number(position.get("szi")) or 0
    side = "LONG" if signed_size > 0 else "SHORT"
    entry_price = _number(position.get("entryPx"))
    stop = None
    target = None
    for order in matching:
        kind, price = _classify_protection(order, side, entry_price)
        if kind == "stop" and stop is None:
            stop = price
        elif kind == "take_profit" and target is None:
            target = price
    return dict(
        status="protected" if stop is not None else "unprotected",
        stop_price=stop,
        take_profit_price=target,
        orders=matching,
    )


def _pnl_24h(fills, funding):
    realized = 0.0
    fees = 0.0
    for fill in fills:
        if not isinstance(fill, dict):
            return dict(realized=None, fees=None, funding=None, net=None)
        closed = _number(fill.get("closedPnl"))
        fee = _number(fill.get("fee"))
        if closed is None or fee is None:
            return dict(realized=None, fees=None, funding=None, net=None)
        realized += closed
        fees += fee

    funding_total = 0.0
    for item in funding:
        if not isinstance(item, dict):
            return dict(realized=None, fees=None, funding=None, net=None)
        delta = item.get("delta")
        amount = _number(delta.get("usdc")) if isinstance(delta, dict) else None
        if amount is None:
            return dict(realized=None, fees=None, funding=None, net=None)
        funding_total += amount
    return dict(
        realized=realized,
        fees=fees,
        funding=funding_total,
        net=realized - fees + funding_total,
    )


class HyperliquidBotService:
    """Caches public exchange reads and never falls back to the master wallet."""

    def __init__(self, info_client=None, cache_seconds=_DEFAULT_CACHE_SECONDS, clock=time.monotonic):
        self._info_client = info_client
        self._cache_seconds = cache_seconds
        self._clock = clock
        self._cache = {}
        self._lock = threading.Lock()

    def _info(self, network, payload):
        if self._info_client is None:
            from .hyperliquid_api import info
            client = info
        else:
            client = self._info_client
        return client(network, payload)

    def _cached(self, key, ttl, load):
        now = self._clock()
        with self._lock:
            item = self._cache.get(key)
            if item and item[0] > now:
                return item[1]
        result = load()
        with self._lock:
            if len(self._cache) >= _CACHE_MAX_ENTRIES:
                expired = [cache_key for cache_key, cached in self._cache.items() if cached[0] <= self._clock()]
                for cache_key in expired:
                    self._cache.pop(cache_key, None)
                if len(self._cache) >= _CACHE_MAX_ENTRIES:
                    self._cache.pop(next(iter(self._cache)))
            self._cache[key] = (self._clock() + ttl, result)
        return result

    @staticmethod
    def _account_address(bot):
        value = bot.get("account_address")
        if not isinstance(value, str) or not value:
            raise RuntimeQueryError("subaccount_unconfigured", "Bot has no configured subaccount.")
        if not re.fullmatch(r"0x[0-9a-fA-F]{40}", value):
            raise RuntimeQueryError("subaccount_invalid", "Bot subaccount address is invalid.")
        if bot.get("master_address") and value.lower() == bot["master_address"].lower():
            raise RuntimeQueryError("subaccount_is_master", "Bot account address is the master wallet, not a subaccount.")
        return value.lower()

    def _verify_subaccount(self, bot, account_address):
        master = bot.get("master_address")
        if not isinstance(master, str) or not re.fullmatch(r"0x[0-9a-fA-F]{40}", master):
            raise RuntimeQueryError("master_wallet_unconfigured", "Bot has no configured master wallet.")
        if bot.get("network") not in {"mainnet", "testnet"}:
            raise RuntimeQueryError("network_invalid", "Bot network is invalid.")

        key = ("subaccounts", bot["network"], master.lower())
        addresses = self._cached(
            key,
            _SUBACCOUNT_CACHE_SECONDS,
            lambda: _subaccounts_addresses(self._info(
                bot["network"], {"type": "subAccounts", "user": master}
            )),
        )
        if account_address not in addresses:
            raise RuntimeQueryError("subaccount_not_found", "Configured account is not a subaccount of this master wallet.")

    def _raw_account(self, network, account_address, synced_at):
        key = ("runtime", network, account_address)

        def load():
            start_ms = int((synced_at - timedelta(hours=24)).timestamp() * 1000)
            end_ms = int(synced_at.timestamp() * 1000)
            payloads = {
                "state": {"type": "clearinghouseState", "user": account_address},
                "orders": {"type": "openOrders", "user": account_address},
                "mode": {"type": "userAbstraction", "user": account_address},
                "fills": {
                    "type": "userFillsByTime", "user": account_address,
                    "startTime": start_ms, "endTime": end_ms,
                },
                "funding": {
                    "type": "userFunding", "user": account_address,
                    "startTime": start_ms, "endTime": end_ms,
                },
            }
            futures = {name: _QUERY_POOL.submit(self._info, network, payload) for name, payload in payloads.items()}
            results = {}
            optional_errors = {}
            for name, future in futures.items():
                try:
                    results[name] = future.result(timeout=12)
                except Exception as exc:
                    if name in {"state", "orders"}:
                        for pending in futures.values():
                            pending.cancel()
                        if isinstance(exc, TimeoutError):
                            raise RuntimeQueryError("exchange_timeout", "Timed out reading the subaccount.") from exc
                        raise RuntimeQueryError("exchange_unavailable", "Could not read the subaccount from Hyperliquid.") from exc
                    optional_errors[name] = "history_unavailable"

            state = results["state"]
            if not isinstance(state, dict) or not isinstance(state.get("marginSummary"), dict):
                raise RuntimeQueryError("invalid_account_state", "Invalid account state from Hyperliquid.")
            orders = _list_payload(results["orders"], "invalid_orders")
            try:
                fills = _list_payload(results.get("fills", []), "invalid_fills") if "fills" in results else []
            except RuntimeQueryError:
                fills = []
                optional_errors["fills"] = "history_unavailable"
            try:
                funding = _list_payload(results.get("funding", []), "invalid_funding") if "funding" in results else []
            except RuntimeQueryError:
                funding = []
                optional_errors["funding"] = "history_unavailable"
            mode = results.get("mode")
            spot = None
            if mode == "unifiedAccount":
                try:
                    spot = self._info(
                        network, {"type": "spotClearinghouseState", "user": account_address}
                    )
                    if not isinstance(spot, dict) or not isinstance(spot.get("balances"), list):
                        raise ValueError("Invalid spot balance response.")
                except Exception:
                    optional_errors["balance"] = "balance_unavailable"
            positions = _extract_positions(state)
            return {
                "state": state,
                "mode": mode,
                "spot": spot,
                "orders": orders,
                "positions": positions,
                "fills": fills,
                "funding": funding,
                "optional_errors": optional_errors,
                "synced_at": synced_at.isoformat(),
            }

        return self._cached(key, self._cache_seconds, load)

    def _realized_pnl_since_creation(self, bot, account_address, now):
        created_at = bot.get("created_at")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise RuntimeQueryError("pnl_history_unavailable", "Bot creation time is invalid.") from exc
        if not isinstance(created_at, datetime):
            raise RuntimeQueryError("pnl_history_unavailable", "Bot creation time is unavailable.")
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        start_ms = int(created_at.timestamp() * 1000)
        end_ms = int(now.timestamp() * 1000)
        if start_ms > end_ms:
            raise RuntimeQueryError("pnl_history_unavailable", "Bot creation time is in the future.")
        key = ("lifetime_pnl", bot["network"], account_address, start_ms)

        def load():
            all_fills = []
            all_funding = []

            def fetch_window(window_start, window_end, depth=0):
                payloads = {
                    "fills": {
                        "type": "userFillsByTime", "user": account_address,
                        "startTime": window_start, "endTime": window_end,
                    },
                    "funding": {
                        "type": "userFunding", "user": account_address,
                        "startTime": window_start, "endTime": window_end,
                    },
                }
                futures = {
                    name: _QUERY_POOL.submit(self._info, bot["network"], payload)
                    for name, payload in payloads.items()
                }
                results = {}
                for name, future in futures.items():
                    try:
                        results[name] = _list_payload(future.result(timeout=12), f"invalid_{name}")
                    except Exception as exc:
                        for pending in futures.values():
                            pending.cancel()
                        raise RuntimeQueryError(
                            "pnl_history_unavailable",
                            "Could not load the bot's realized PnL history from Hyperliquid.",
                        ) from exc

                if any(len(records) >= _MAX_HISTORY_RECORDS for records in results.values()):
                    midpoint = (window_start + window_end) // 2
                    if depth >= 20 or midpoint <= window_start or midpoint >= window_end:
                        raise RuntimeQueryError(
                            "pnl_history_unavailable",
                            "The bot's realized PnL history cannot be safely paginated.",
                        )
                    fetch_window(window_start, midpoint, depth + 1)
                    fetch_window(midpoint + 1, window_end, depth + 1)
                    return

                all_fills.extend(results["fills"])
                all_funding.extend(results["funding"])

            cursor = start_ms
            while cursor <= end_ms:
                window_end = min(cursor + _HISTORY_WINDOW_MS - 1, end_ms)
                fetch_window(cursor, window_end)
                cursor = window_end + 1

            pnl = _pnl_24h(all_fills, all_funding)
            if pnl["net"] is None:
                raise RuntimeQueryError(
                    "pnl_history_unavailable",
                    "Hyperliquid returned incomplete realized PnL history.",
                )
            return pnl

        return self._cached(key, _LIFETIME_PNL_CACHE_SECONDS, load)

    def _realized_net_since_creation(self, bot, account_address, now):
        return self._realized_pnl_since_creation(bot, account_address, now)["net"]

    def runtime_state(self, bot, run=None, now=None):
        now = now or datetime.now(timezone.utc)
        run_state = run.get("state") if run and isinstance(run.get("state"), dict) else {}
        status = bot.get("status") or "stopped"
        active_run = bool(run and run.get("active") and run.get("managing"))
        heartbeat = run.get("heartbeat") if run else None
        heartbeat_dt = heartbeat if isinstance(heartbeat, datetime) else None
        if heartbeat_dt is not None and heartbeat_dt.tzinfo is None:
            heartbeat_dt = heartbeat_dt.replace(tzinfo=timezone.utc)
        worker_age = (now - heartbeat_dt).total_seconds() if heartbeat_dt else None
        market = bot.get("market") or bot.get("coin")
        try:
            account_address = self._account_address(bot)
            self._verify_subaccount(bot, account_address)
            raw = self._raw_account(bot["network"], account_address, now)
        except RuntimeQueryError as exc:
            return self._error_state(bot, run, exc.reason, str(exc), status, worker_age)
        except (URLError, TimeoutError, OSError) as exc:
            timeout_reason = isinstance(exc, TimeoutError) or (
                isinstance(exc, URLError) and isinstance(exc.reason, TimeoutError)
            )
            reason = "exchange_timeout" if timeout_reason else "exchange_unavailable"
            return self._error_state(bot, run, reason, "Could not reach Hyperliquid.", status, worker_age)
        except Exception:
            return self._error_state(
                bot, run, "exchange_unavailable",
                "Could not normalize the Hyperliquid response.", status, worker_age,
            )

        state = raw["state"]
        summary = state["marginSummary"]
        equity = _number(summary.get("accountValue"))
        margin_used = _number(summary.get("totalMarginUsed"))
        balance_source = "perps_clearinghouse_state"
        available = None
        if raw["mode"] is not None:
            try:
                from .account_balance import trading_balance
                equity, available, balance_source = trading_balance(raw["mode"], state, raw["spot"])
            except (KeyError, TypeError, ValueError):
                raw["optional_errors"]["balance"] = "balance_unavailable"
        position_raw = _position_for_market(raw["positions"], market)
        position = self._normalize_position(position_raw) if position_raw else None
        protection = _protection_state(raw["orders"], market, position_raw)
        fills = raw["fills"]
        funding = raw["funding"]
        pnl = _pnl_24h(fills, funding)
        if "fills" in raw["optional_errors"]:
            pnl["realized"] = None
            pnl["fees"] = None
        if "funding" in raw["optional_errors"]:
            pnl["funding"] = None
        if raw["optional_errors"]:
            pnl["net"] = None
        try:
            lifetime_pnl = self._realized_pnl_since_creation(bot, account_address, now)
        except RuntimeQueryError:
            lifetime_pnl = dict(realized=None, fees=None, funding=None, net=None)
            raw["optional_errors"]["pnl_history"] = "history_unavailable"
        last_fill = max(
            (fill for fill in fills if isinstance(fill, dict)),
            key=lambda item: _number(item.get("time")) or 0,
            default=None,
        )
        local_phase = run_state.get("phase")
        last_error = run_state.get("last_error")
        health_status, reason = self._health(
            status, active_run, worker_age, last_error, raw, position, protection,
            local_phase, run_state, market,
        )
        return {
            "account": {
                "master_address": bot.get("master_address"),
                "subaccount_address": account_address,
                "subaccount_name": bot.get("subaccount_name"),
                "network": bot.get("network"),
            },
            "balance": {
                "equity": equity,
                "available": available,
                "margin_used": margin_used,
                "margin_available": available,
                "exposure": _number(summary.get("totalNtlPos")),
                "source": balance_source,
                "synced_at": raw["synced_at"],
            },
            "position": position,
            "orders": {
                "count": sum(1 for order in raw["orders"] if isinstance(order, dict)),
                "items": raw["orders"],
                "protection": protection,
            },
            "pnl": {
                "unrealized": position["unrealized_pnl"] if position else 0.0,
                "realized_24h": pnl["realized"],
                "fees_24h": pnl["fees"],
                "funding_24h": pnl["funding"],
                "net_24h": pnl["net"],
                "run": None,
                "realized_total": lifetime_pnl["realized"],
                "fees_total": lifetime_pnl["fees"],
                "funding_total": lifetime_pnl["funding"],
                "bot_total": lifetime_pnl["net"],
                "basis": "hyperliquid_realized_fills_and_funding_since_bot_creation",
            },
            "activity": {
                "last_fill_at": _exchange_time(last_fill.get("time")) if last_fill else None,
                "last_order_at": _iso(run.get("last_order_at")) if run else None,
                "fills_24h": len(fills) if "fills" not in raw["optional_errors"] else None,
            },
            "strategy_state": {
                "phase": local_phase,
                "message": run_state.get("message"),
                "last_signal": run_state.get("side"),
                "last_candle_at": _exchange_time(
                    run_state.get("last_candle_at") or run_state.get("last_candle") or run_state.get("processed_through")
                ),
            },
            "health": {
                "status": health_status,
                "reason": reason,
                "worker_active": active_run and worker_age is not None and worker_age <= _HEARTBEAT_ERROR_SECONDS,
                "last_worker_at": _iso(heartbeat),
                "last_exchange_sync_at": raw["synced_at"],
                "last_error": last_error,
                "exchange_connected": True,
                "exchange_synced": True,
                "position_protection": protection["status"],
                "partial_data": bool(raw["optional_errors"]),
                "partial_data_reasons": sorted(set(raw["optional_errors"].values())),
            },
            "run": {
                "id": run.get("id") if run else None,
                "phase": local_phase,
                "active": bool(run and run.get("active")),
                "managing": bool(run and run.get("managing")),
                "created_at": _iso(run.get("created_at")) if run else None,
            },
        }

    @staticmethod
    def _normalize_position(position):
        signed_size = _number(position.get("szi"))
        if signed_size is None or signed_size == 0:
            return None
        leverage = position.get("leverage")
        if isinstance(leverage, dict):
            leverage = leverage.get("value")
        entry_price = _number(position.get("entryPx"))
        mark_price = _number(position.get("markPx"))
        return_on_equity = _number(position.get("returnOnEquity"))
        return {
            "side": "LONG" if signed_size > 0 else "SHORT",
            "size": abs(signed_size),
            "entry_price": entry_price,
            "mark_price": mark_price,
            "position_value": _number(position.get("positionValue")),
            "leverage": _number(leverage),
            "margin_used": _number(position.get("marginUsed")),
            "unrealized_pnl": _number(position.get("unrealizedPnl")),
            "return_on_equity_pct": return_on_equity * 100 if return_on_equity is not None else None,
            "liquidation_price": _number(position.get("liquidationPx")) or _number(position.get("liqPx")),
            "coin": position.get("coin"),
        }

    def _error_state(self, bot, run, reason, message, status, worker_age):
        active_run = bool(run and run.get("active") and run.get("managing"))
        run_state = run.get("state") if run and isinstance(run.get("state"), dict) else {}
        configuration_errors = {
            "subaccount_unconfigured", "subaccount_is_master",
            "subaccount_invalid", "subaccount_not_found", "master_wallet_unconfigured",
            "network_invalid",
        }
        health_status = (
            "stopped"
            if status in {"stopped", "paused"} and not active_run and reason not in configuration_errors
            else "error"
        )
        return {
            "account": {
                "master_address": bot.get("master_address"),
                "subaccount_address": bot.get("account_address"),
                "subaccount_name": bot.get("subaccount_name"),
                "network": bot.get("network"),
            },
            "balance": None,
            "position": None,
            "orders": None,
            "pnl": {
                "unrealized": None, "realized_24h": None, "fees_24h": None,
                "funding_24h": None, "net_24h": None, "run": None,
                "realized_total": None, "fees_total": None, "funding_total": None,
                "bot_total": None, "basis": None,
            },
            "activity": {"last_fill_at": None, "last_order_at": None, "fills_24h": None},
            "strategy_state": {
                "phase": run_state.get("phase"),
                "message": message,
                "last_signal": None,
                "last_candle_at": None,
            },
            "health": {
                "status": health_status,
                "reason": reason,
                "worker_active": active_run and worker_age is not None and worker_age <= _HEARTBEAT_ERROR_SECONDS,
                "last_worker_at": _iso(run.get("heartbeat")) if run else None,
                "last_exchange_sync_at": None,
                "last_error": message,
                "exchange_connected": False,
                "exchange_synced": False,
                "position_protection": "unknown",
                "partial_data": False,
                "partial_data_reasons": [],
            },
            "run": {
                "id": run.get("id") if run else None,
                "phase": run_state.get("phase"),
                "active": bool(run and run.get("active")),
                "managing": bool(run and run.get("managing")),
                "created_at": _iso(run.get("created_at")) if run else None,
            },
        }

    @staticmethod
    def _health(status, active_run, worker_age, last_error, raw, position, protection, phase, run_state, market):
        if any(_market_key(item.get("coin")) != _market_key(market) for item in raw["positions"]):
            return "error", "exchange_position_on_unconfigured_market"
        if any(
            isinstance(order, dict) and _market_key(order.get("coin")) != _market_key(market)
            for order in raw["orders"]
        ):
            return "warning", "exchange_orders_on_unconfigured_market"
        if status in {"stopped", "paused"} and not active_run:
            if position:
                return "warning", "position_open_while_stopped"
            if protection["orders"]:
                return "warning", "orders_open_while_stopped"
            return "stopped", "bot_stopped"
        if status == "error" or last_error:
            return "error", "worker_error"
        if not active_run:
            return "error", "active_bot_without_managing_run"
        if worker_age is None:
            return "error", "worker_heartbeat_missing"
        if worker_age > _HEARTBEAT_ERROR_SECONDS:
            return "error", "worker_heartbeat_stale"
        if worker_age > _HEARTBEAT_WARNING_SECONDS:
            return "warning", "worker_heartbeat_delayed"

        local_open = phase in {"open", "protecting", "closing"}
        if local_open and position is None:
            return "error", "local_exchange_position_mismatch"
        if phase == "waiting" and position is not None:
            return "error", "unmanaged_exchange_position"
        if phase == "waiting" and protection["orders"]:
            return "error", "unmanaged_exchange_orders"
        if position and phase in {"open", "protecting", "closing", "halted"}:
            local_side = run_state.get("side")
            if local_side in {"LONG", "SHORT"} and position["side"] != local_side:
                return "error", "local_exchange_position_side_mismatch"
            expected_cloids = run_state.get("protection_cloids")
            if isinstance(expected_cloids, list) and expected_cloids:
                open_cloids = {
                    str(order.get("cloid", "")).lower()
                    for order in protection["orders"]
                    if isinstance(order, dict)
                }
                if any(str(cloid).lower() not in open_cloids for cloid in expected_cloids):
                    return "warning", "local_exchange_order_mismatch"
        if position and isinstance(run_state.get("quantity"), (int, float)):
            expected = run_state["quantity"]
            if abs(position["size"] - expected) > max(1e-8, abs(expected) * 0.01):
                return "error", "local_exchange_position_size_mismatch"
        if position and protection["status"] == "unprotected":
            return "warning", "position_without_stop"
        if raw["optional_errors"]:
            return "warning", "partial_exchange_data"
        return "healthy", None


bot_service = HyperliquidBotService()


def get_bot_runtime_state(bot, run=None, now=None):
    return bot_service.runtime_state(bot, run, now)


def get_bot_realized_lifetime_pnl(bot, now=None):
    now = now or datetime.now(timezone.utc)
    account_address = bot_service._account_address(bot)
    bot_service._verify_subaccount(bot, account_address)
    return bot_service._realized_net_since_creation(bot, account_address, now)
