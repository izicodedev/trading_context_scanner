from __future__ import annotations
import asyncio, logging
from .config import settings
from .market import BinanceClient
from .strategy import analyze
from .storage import save

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", handlers=[logging.FileHandler("logs/scanner.log"), logging.StreamHandler()])

async def scan(client):
    context, structure, trigger = await asyncio.gather(
        client.klines(settings.symbol, settings.context_interval, settings.candle_limit),
        client.klines(settings.symbol, settings.structure_interval, settings.candle_limit),
        client.klines(settings.symbol, settings.trigger_interval, settings.candle_limit),
    )
    sig=analyze(context, structure, trigger, settings.risk_reward, settings.atr_stop_mult, settings.min_score)
    save(sig, settings.data_file)
    logging.info("%s | score=%s | price=%.2f | entry=%s stop=%s target=%s | %s", sig.side, sig.score, sig.price, fmt(sig.entry), fmt(sig.stop), fmt(sig.target), " | ".join(sig.reasons))

def fmt(x): return "-" if x is None else f"{x:.2f}"

async def main():
    async with BinanceClient(settings.api_base) as client:
        while True:
            try: await scan(client)
            except Exception: logging.exception("scan failed")
            await asyncio.sleep(settings.poll_seconds)

if __name__ == "__main__": asyncio.run(main())
