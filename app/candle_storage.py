"""Closed OHLCV persistence and bounded historical queries."""
from __future__ import annotations

from math import isfinite

import pandas as pd
import psycopg
from psycopg.rows import dict_row

from .db import get_database_url
from .trade_simulator import _utc, _validated_candles

MARKET_SOURCE = "binance_spot"
TIMEFRAME_MINUTES = {"5m": 5, "15m": 15, "1h": 60}
CANDLE_COLUMNS = ["open_time", "close_time", "open", "high", "low", "close", "volume"]


def _connect():
    url = get_database_url()
    if not url:
        raise RuntimeError("Banco não configurado para consultar candles.")
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=5)


def save_candles(symbol: str, timeframe: str, candles: pd.DataFrame,
                 source: str = MARKET_SOURCE) -> int:
    """Idempotent upsert. The incomplete current candle is never persisted."""
    if timeframe not in TIMEFRAME_MINUTES:
        raise ValueError("Timeframe não suportado.")
    if candles.empty:
        return 0
    _validated_candles(candles, _utc(candles.iloc[0].open_time))
    if "volume" not in candles or not candles.volume.map(lambda v: isfinite(v) and v >= 0).all():
        raise ValueError("Volume deve ser finito e não negativo.")
    closed = candles.loc[candles.close_time < pd.Timestamp.now(tz="UTC"), CANDLE_COLUMNS]
    records = [(source, symbol, timeframe, row.open_time.to_pydatetime(),
                row.close_time.to_pydatetime(), float(row.open), float(row.high),
                float(row.low), float(row.close), float(row.volume))
               for row in closed.itertuples(index=False)]
    if records:
        with _connect() as conn, conn.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO market_candles
                (source, symbol, timeframe, open_time, close_time, open, high, low, close, volume)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (source, symbol, timeframe, open_time) DO UPDATE SET
                close_time=EXCLUDED.close_time, open=EXCLUDED.open, high=EXCLUDED.high,
                low=EXCLUDED.low, close=EXCLUDED.close, volume=EXCLUDED.volume""", records)
    return len(records)


def available_datasets() -> list[dict]:
    with _connect() as conn:
        return conn.execute("""
            SELECT source, symbol, timeframe, COUNT(*) AS candles,
                   MIN(open_time) AS start_time, MAX(close_time) AS end_time,
                   (array_agg(open ORDER BY open_time))[1] AS first_open
            FROM market_candles WHERE close_time < NOW()
            GROUP BY source, symbol, timeframe ORDER BY source, symbol, timeframe
        """).fetchall()


def load_candles(symbol: str, timeframe: str, entry_time: object, max_candles: int,
                 source: str = MARKET_SOURCE) -> pd.DataFrame:
    if timeframe not in TIMEFRAME_MINUTES:
        raise ValueError("Timeframe não suportado.")
    if type(max_candles) is not int or not 1 <= max_candles <= 5000:
        raise ValueError("Informe um horizonte entre 1 e 5.000 candles.")
    entry = _utc(entry_time)
    # Include a straddling candle so the simulator rejects entry inside its range.
    with _connect() as conn:
        rows = conn.execute("""
            SELECT open_time, close_time, open, high, low, close, volume
            FROM market_candles
            WHERE source=%s AND symbol=%s AND timeframe=%s
              AND close_time > %s AND close_time < NOW()
            ORDER BY open_time LIMIT %s
        """, (source, symbol, timeframe, entry.to_pydatetime(), max_candles)).fetchall()
    frame = pd.DataFrame(rows, columns=CANDLE_COLUMNS)
    if frame.empty:
        raise ValueError("Não há candles fechados no banco após essa entrada. Consulte o período disponível.")
    first = _utc(frame.iloc[0].open_time)
    if first > entry and (first - entry).value > 1_000_000:
        raise ValueError("Não há candle no início solicitado. Escolha uma abertura no período disponível.")
    expected_ns = TIMEFRAME_MINUTES[timeframe] * 60 * 1_000_000_000
    if not frame.open_time.diff().iloc[1:].map(lambda delta: delta.value == expected_ns).all():
        raise ValueError("O período contém lacunas de candles. Complete o histórico antes de simular.")
    return frame
