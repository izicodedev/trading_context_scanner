from __future__ import annotations
import asyncio, logging
from .config import settings
from .evaluation import evaluate_signal
from .market import BinanceClient
from .strategy import analyze
from .storage import save, save_evaluation

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s", handlers=[logging.FileHandler("logs/scanner.log"), logging.StreamHandler()])

async def scan(client):
    context, structure, trigger = await asyncio.gather(
        client.klines(settings.symbol, settings.context_interval, settings.candle_limit),
        client.klines(settings.symbol, settings.structure_interval, settings.candle_limit),
        client.klines(settings.symbol, settings.trigger_interval, settings.candle_limit),
    )
    sig=analyze(context, structure, trigger, settings.risk_reward, settings.atr_stop_mult, settings.min_score)
    save(sig, settings.data_file)
    eval_record = evaluate_signal(sig, trigger)
    save_evaluation(eval_record, settings.evaluation_file)
    prefix = "[WAIT SIGNAL]" if sig.side == "WAIT" else f"[{sig.side} SIGNAL]"
    if sig.entry_state == "ENTRY":
        prefix = f"[{sig.side} ENTRY]"
    elif sig.setup_state == "SETUP":
        prefix = f"[{sig.side} SETUP]"
    logging.info("%s side=%s | score=%s | price=%.2f | long=%s short=%s | ema21=%.2f ema50=%.2f rsi=%.2f atr=%.2f vol_ratio=%.2f trend=%s | entry=%s stop=%s target=%s | %s",
        prefix,
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
            try: await scan(client)
            except Exception: logging.exception("scan failed")
            await asyncio.sleep(settings.poll_seconds)

if __name__ == "__main__": asyncio.run(main())
