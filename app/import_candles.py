"""Populate local historical candle storage using the existing market client."""
import argparse
import asyncio
import pandas as pd

from .candle_storage import save_candles, TIMEFRAME_MINUTES
from .config import settings
from .market import BinanceClient


async def import_recent(symbol: str, limit: int) -> None:
    async with BinanceClient(settings.api_base) as client:
        for timeframe in TIMEFRAME_MINUTES:
            candles = await client.klines(symbol, timeframe, limit)
            count = save_candles(symbol, timeframe, candles)
            print(f"{symbol} {timeframe}: {count} candles fechados gravados/atualizados")


async def import_period(symbol: str, days: int, *, end: pd.Timestamp | None = None) -> int:
    """Import exactly `days` UTC days of complete 5m candles, checking every page."""
    if not 1 <= days <= 90:
        raise ValueError("days deve estar entre 1 e 90")
    end = (end if end is not None else pd.Timestamp.now(tz="UTC")).floor("5min")
    if end.tzinfo is None:
        raise ValueError("O horário final deve incluir fuso UTC.")
    end = end.tz_convert("UTC")
    start = end - pd.Timedelta(days=days)
    cursor = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    step_ms = TIMEFRAME_MINUTES["5m"] * 60_000
    expected = days * 24 * 60 // TIMEFRAME_MINUTES["5m"]
    total = 0
    async with BinanceClient(settings.api_base) as client:
        while cursor < end_ms:
            frame = await client.klines(symbol, "5m", 1000, cursor, end_ms - 1)
            if frame.empty:
                raise ValueError(f"A Binance não retornou candles a partir de {pd.Timestamp(cursor, unit='ms', tz='UTC')}.")
            first_ms = int(frame.iloc[0].open_time.timestamp() * 1000)
            last_ms = int(frame.iloc[-1].open_time.timestamp() * 1000)
            if first_ms != cursor or last_ms >= end_ms or last_ms < first_ms:
                raise ValueError(f"Histórico incompleto ou fora de ordem a partir de {pd.Timestamp(cursor, unit='ms', tz='UTC')}.")
            if not frame.open_time.diff().iloc[1:].map(lambda delta: delta.value == step_ms * 1_000_000).all():
                raise ValueError(f"Histórico com lacunas a partir de {pd.Timestamp(cursor, unit='ms', tz='UTC')}.")
            total += save_candles(symbol, "5m", frame)
            cursor = last_ms + step_ms
            print(f"{symbol} 5m: {total}/{expected} candles processados", flush=True)
            if cursor < end_ms:
                await asyncio.sleep(.2)
    if total != expected:
        raise ValueError(f"Histórico incompleto: {total} de {expected} candles de 5m.")
    print(f"{symbol} 5m: 30 dias completos até {end.isoformat()}" if days == 30 else
          f"{symbol} 5m: {days} dias completos até {end.isoformat()}", flush=True)
    return total


def main():
    parser = argparse.ArgumentParser(description="Importar candles recentes para PostgreSQL")
    parser.add_argument("--symbol", default=settings.symbol)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--days", type=int, help="Backfill paginado de 5m, de 1 a 90 dias")
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000:
        parser.error("limit deve estar entre 1 e 1000")
    if args.days is not None:
        if not 1 <= args.days <= 90:
            parser.error("days deve estar entre 1 e 90")
        asyncio.run(import_period(args.symbol.upper(), args.days))
    else:
        asyncio.run(import_recent(args.symbol.upper(), args.limit))


if __name__ == "__main__":
    main()
