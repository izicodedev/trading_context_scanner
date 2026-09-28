from datetime import datetime, timezone

import pandas as pd
import pytest

from app import candle_storage as storage


class Connection:
    def __init__(self, rows):
        self.rows = rows
        self.parameters = None
        self.records = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, parameters=None):
        self.sql, self.parameters = sql, parameters
        return self

    def fetchall(self):
        return self.rows

    def cursor(self):
        return self

    def executemany(self, sql, records):
        self.sql, self.records = sql, records


def row(minute=0, year=2020):
    return dict(open_time=datetime(year, 1, 1, 0, minute, tzinfo=timezone.utc),
                close_time=datetime(year, 1, 1, 0, minute + 14, 59, 999000, tzinfo=timezone.utc),
                open=100, high=102, low=99, close=101, volume=5)


def test_query_filters_source_market_time_and_closed_candles(monkeypatch):
    conn = Connection([row(), row(15)])
    monkeypatch.setattr(storage, "_connect", lambda: conn)
    result = storage.load_candles("BTCUSDT", "15m", "2020-01-01T00:00:00Z", 2)
    assert len(result) == 2
    assert conn.parameters == ("binance_spot", "BTCUSDT", "15m", row()["open_time"], 2)
    assert "close_time < NOW()" in conn.sql
    assert "ORDER BY open_time LIMIT %s" in conn.sql


@pytest.mark.parametrize("rows", [[], [row(15)], [row(), row(30)]])
def test_missing_initial_or_internal_history_is_rejected(monkeypatch, rows):
    monkeypatch.setattr(storage, "_connect", lambda: Connection(rows))
    with pytest.raises(ValueError):
        storage.load_candles("BTCUSDT", "15m", "2020-01-01T00:00:00Z", 3)


def test_available_tail_remains_available_for_insufficient_data_result(monkeypatch):
    monkeypatch.setattr(storage, "_connect", lambda: Connection([row()]))
    assert len(storage.load_candles("BTCUSDT", "15m", "2020-01-01T00:00:00Z", 3)) == 1


def test_save_excludes_unclosed_candles_and_uses_upsert(monkeypatch):
    conn = Connection([])
    monkeypatch.setattr(storage, "_connect", lambda: conn)
    frame = pd.DataFrame([row(), row(year=2099)])
    assert storage.save_candles("BTCUSDT", "15m", frame) == 1
    assert conn.records[0][:3] == ("binance_spot", "BTCUSDT", "15m")
    assert conn.records[0][3].year == 2020
    assert "ON CONFLICT (source, symbol, timeframe, open_time)" in conn.sql
