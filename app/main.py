from __future__ import annotations
import asyncio, logging
import pandas as pd
from .config import settings
from .evaluation import evaluate_signal
from .market import BinanceClient
from .strategy import analyze
from .storage import save, save_evaluation
from .candle_storage import save_candles, latest_open_time, TIMEFRAME_MINUTES
from .db import get_database_url
from .symbols import SYMBOLS


async def catch_up_candles(client, symbol: str, timeframe: str):
    """Fill closed bars since the last saved candle after scanner downtime."""
    latest = latest_open_time(symbol, timeframe)
    if latest is None:
        if timeframe == "5m":
            from .import_candles import import_period
            await import_period(symbol, 30)
        return
    minutes = TIMEFRAME_MINUTES[timeframe]
    end_ms = int(pd.Timestamp.now(tz="UTC").floor(f"{minutes}min").timestamp() * 1000)
    step_ms = minutes * 60_000
    cursor = int(pd.Timestamp(latest).timestamp() * 1000) + step_ms
    while cursor < end_ms:
        frame = await client.klines(symbol, timeframe, 1000, cursor, end_ms - 1)
        if frame.empty:
            raise ValueError(f"{symbol} {timeframe}: lacuna na coleta.")
        first_ms = int(frame.iloc[0].open_time.timestamp() * 1000)
        last_ms = int(frame.iloc[-1].open_time.timestamp() * 1000)
        if first_ms != cursor or last_ms >= end_ms or not frame.open_time.diff().iloc[1:].map(lambda delta: delta.value == step_ms * 1_000_000).all():
            raise ValueError(f"{symbol} {timeframe}: candles fora de sequência no histórico recente.")
        save_candles(symbol, timeframe, frame)
        cursor = last_ms + step_ms
        if cursor < end_ms:
            await asyncio.sleep(.2)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", handlers=[logging.FileHandler("logs/scanner.log"), logging.StreamHandler()])

async def scan(client, symbol: str = settings.symbol):
    context, structure, trigger = await asyncio.gather(
        client.klines(symbol, settings.context_interval, settings.candle_limit),
        client.klines(symbol, settings.structure_interval, settings.candle_limit),
        client.klines(symbol, settings.trigger_interval, settings.candle_limit),
    )
    sig=analyze(context, structure, trigger, settings.risk_reward, settings.atr_stop_mult, settings.min_score)
    data_file = settings.data_file if symbol == settings.symbol else settings.data_file.replace('.csv', f'_{symbol}.csv')
    evaluation_file = settings.evaluation_file if symbol == settings.symbol else settings.evaluation_file.replace('.csv', f'_{symbol}.csv')
    save(sig, data_file, symbol)
    eval_record = evaluate_signal(sig, trigger)
    save_evaluation(eval_record, evaluation_file)
    if get_database_url():
        try:
            for interval, candles in ((settings.context_interval, context),
                                      (settings.structure_interval, structure),
                                      (settings.trigger_interval, trigger)):
                await catch_up_candles(client, symbol, interval)
                save_candles(symbol, interval, candles)
        except Exception:
            logging.exception("Candle persistence failed; scanner signal was preserved")
    prefix = "[WAIT SIGNAL]" if sig.side == "WAIT" else f"[{sig.side} SIGNAL]"
    if sig.entry_state == "ENTRY":
        prefix = f"[{sig.side} ENTRY]"
    elif sig.setup_state == "SETUP":
        prefix = f"[{sig.side} SETUP]"
    logging.info("%s %s side=%s | score=%s | price=%.2f | long=%s short=%s | ema21=%.2f ema50=%.2f rsi=%.2f atr=%.2f vol_ratio=%.2f trend=%s | entry=%s stop=%s target=%s | %s",
        prefix,
        symbol,
        sig.side,
        sig.score,
        sig.price,
        sig.long_score,
        sig.short_score,
        sig.ema21 if sig.ema21 is not None else 0.0,
        sig.ema50 if sig.ema50 is not None else 0.0,
        sig.rsi if sig.rsi is not None else 0.0,
        sig.atr if sig.atr is not None else 0.0,
        sig.vol_ratio if sig.vol_ratio is not None else 0.0,
        sig.trend_bias if sig.trend_bias is not None else "FLAT",
        fmt(sig.entry),
        fmt(sig.stop),
        fmt(sig.target),
        " | ".join(sig.reasons),
    )


def fmt(x): return "-" if x is None else f"{x:.2f}"

async def main():
    async with BinanceClient(settings.api_base) as client:
        while True:
            for symbol in SYMBOLS:
                try: await scan(client, symbol)
                except Exception: logging.exception("scan failed for %s", symbol)
            await asyncio.sleep(settings.poll_seconds)

if __name__ == "__main__": asyncio.run(main())
