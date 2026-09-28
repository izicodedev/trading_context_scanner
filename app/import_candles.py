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


async def import_period(symbol: str, days: int):
    end = pd.Timestamp.now(tz="UTC")
    cursor = int((end - pd.Timedelta(days=days)).timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    total = 0
    async with BinanceClient(settings.api_base) as client:
        while cursor < end_ms:
            frame = await client.klines(symbol, "5m", 1000, cursor, end_ms)
            if frame.empty:
                break
            next_cursor = int(frame.iloc[-1].close_time.timestamp() * 1000) + 1
            if next_cursor <= cursor:
                raise ValueError("Paginação sem avanço")
            total += save_candles(symbol, "5m", frame)
            cursor = next_cursor
            print(f"{symbol} 5m: {total} candles processados", flush=True)
            await asyncio.sleep(.2)


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
