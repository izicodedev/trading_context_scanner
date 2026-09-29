import asyncio

import pandas as pd
import pytest

from app import main, web
from app.symbols import SYMBOLS, validate_symbol


def test_symbol_validation_is_an_allowlist():
    assert SYMBOLS == ("BTCUSDT", "ETHUSDT")
    assert validate_symbol("ETHUSDT") == "ETHUSDT"
    for value in ("ETH", "ethusdt", "BTCUSDT;DROP TABLE signals", None):
        with pytest.raises(ValueError):
            validate_symbol(value)


def test_scanner_attempts_both_symbols_even_if_one_fails(monkeypatch):
    calls = []

    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): pass

    class Done(Exception): pass

    async def scan(_client, symbol):
        calls.append(symbol)
        if symbol == "BTCUSDT":
            raise RuntimeError("temporary market error")

    async def stop(_seconds):
        raise Done

    monkeypatch.setattr(main, "BinanceClient", lambda *_: Client())
    monkeypatch.setattr(main, "scan", scan)
    monkeypatch.setattr(main.asyncio, "sleep", stop)
    with pytest.raises(Done):
        asyncio.run(main.main())
    assert calls == ["BTCUSDT", "ETHUSDT"]


def test_catch_up_fills_closed_candles_from_last_saved(monkeypatch):
    end = pd.Timestamp.now(tz="UTC").floor("5min")
    last = end - pd.Timedelta(minutes=15)
    requested = []
    saved = []

    class Client:
        async def klines(self, symbol, timeframe, limit, start, stop):
            requested.append((symbol, timeframe, start, stop))
            opens = pd.date_range(last + pd.Timedelta(minutes=5), periods=2, freq="5min")
            return pd.DataFrame({"open_time": opens, "close_time": opens + pd.Timedelta(minutes=5) - pd.Timedelta(milliseconds=1)})

    monkeypatch.setattr(main, "latest_open_time", lambda symbol, timeframe: last)
    monkeypatch.setattr(main, "save_candles", lambda symbol, timeframe, frame: saved.append((symbol, timeframe, len(frame))))
    asyncio.run(main.catch_up_candles(Client(), "ETHUSDT", "5m"))
    assert requested and requested[0][:2] == ("ETHUSDT", "5m")
    assert saved == [("ETHUSDT", "5m", 2)]


def test_dashboard_payload_uses_selected_symbol(monkeypatch):
    seen = []
    monkeypatch.setattr(web, "load_signal_rows", lambda symbol: seen.append(symbol) or [])
    monkeypatch.setattr(web, "_latest_file_mtime", lambda path: None)
    assert web.build_status_payload("ETHUSDT")["market"] == "ETHUSDT"
    assert seen == ["ETHUSDT"]
