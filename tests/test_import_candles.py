import asyncio

import pandas as pd
import pytest

from app import import_candles


END = pd.Timestamp("2026-09-01T00:00:00Z")
STEP_MS = 300_000


class FakeBinance:
    def __init__(self, base_url):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def klines(self, symbol, timeframe, limit, start_ms, end_ms):
        self.calls.append((symbol, timeframe, limit, start_ms, end_ms))
        first = pd.Timestamp(start_ms, unit="ms", tz="UTC")
        last = pd.Timestamp(end_ms, unit="ms", tz="UTC").floor("5min")
        opens = pd.date_range(first, last, freq="5min")[:limit]
        return pd.DataFrame({"open_time": opens, "close_time": opens + pd.Timedelta(minutes=5) - pd.Timedelta(milliseconds=1)})


def test_thirty_day_import_paginates_full_candles(monkeypatch):
    client = FakeBinance("unused")
    saved = []
    monkeypatch.setattr(import_candles, "BinanceClient", lambda _: client)
    monkeypatch.setattr(import_candles, "save_candles", lambda symbol, timeframe, frame: saved.append(len(frame)) or len(frame))
    total = asyncio.run(import_candles.import_period("ETHUSDT", 30, end=END))
    assert total == 8640
    assert saved == [1000] * 8 + [640]
    assert len(client.calls) == 9
    assert client.calls[0][3] == int((END - pd.Timedelta(days=30)).timestamp() * 1000)
    assert client.calls[1][3] == client.calls[0][3] + 1000 * STEP_MS
    assert client.calls[-1][4] == int(END.timestamp() * 1000) - 1


def test_import_rejects_missing_candle_in_page(monkeypatch):
    class Gapped(FakeBinance):
        async def klines(self, *args):
            frame = await super().klines(*args)
            return frame.drop(index=1).reset_index(drop=True)
    monkeypatch.setattr(import_candles, "BinanceClient", Gapped)
    monkeypatch.setattr(import_candles, "save_candles", lambda *args: pytest.fail("Não deve gravar página incompleta"))
    with pytest.raises(ValueError, match="lacunas"):
        asyncio.run(import_candles.import_period("ETHUSDT", 1, end=END))


def test_import_rejects_empty_page_instead_of_silent_partial_success(monkeypatch):
    class Empty(FakeBinance):
        async def klines(self, *args):
            return pd.DataFrame(columns=["open_time", "close_time"])
    monkeypatch.setattr(import_candles, "BinanceClient", Empty)
    with pytest.raises(ValueError, match="não retornou candles"):
        asyncio.run(import_candles.import_period("ETHUSDT", 1, end=END))
