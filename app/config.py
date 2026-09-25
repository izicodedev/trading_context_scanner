import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    symbol: str = "BTCUSDT"
    context_interval: str = "1h"
    structure_interval: str = "15m"
    trigger_interval: str = "5m"
    candle_limit: int = 300
    poll_seconds: int = 60
    min_score: int = 65
    risk_reward: float = 2.0
    atr_stop_mult: float = 1.2
    api_base: str = "https://api.binance.com"
    data_file: str = "data/signals.csv"
    evaluation_file: str = "data/signal_evaluation.csv"
    web_base_url: str = os.getenv("WEB_BASE_URL", "http://localhost:5000")


settings = Settings()
