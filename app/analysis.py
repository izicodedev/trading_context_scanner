from __future__ import annotations

import pandas as pd
from collections import Counter
from itertools import combinations


LONG_COMPONENTS = [
    "long_trend_ema",
    "long_price_above_ema",
    "long_rsi_favorable",
    "long_rsi_extreme",
    "long_volume_confirmation",
    "long_fib",
    "long_liquidity_sweep",
    "long_structure",
]

SHORT_COMPONENTS = [
    "short_trend_ema",
    "short_price_below_ema",
    "short_rsi_favorable",
    "short_rsi_extreme",
    "short_volume_confirmation",
    "short_fib",
    "short_liquidity_sweep",
    "short_structure",
]


def load_signal_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    for comp in LONG_COMPONENTS + SHORT_COMPONENTS:
        if f"{comp}_active" in df.columns:
            df[f"{comp}_active"] = df[f"{comp}_active"].fillna(False).astype(bool)
    return df


def component_frequency(path: str, side: str | None = None) -> dict[str, int]:
    df = load_signal_csv(path)
    if side == "LONG":
        comps = LONG_COMPONENTS
    elif side == "SHORT":
        comps = SHORT_COMPONENTS
    else:
        comps = LONG_COMPONENTS + SHORT_COMPONENTS

    counts = {}
    for comp in comps:
        active_col = f"{comp}_active"
        if active_col not in df.columns:
            continue
        counts[comp] = int(df[active_col].sum())
    return counts


def combination_frequency(path: str, side: str | None = None, max_size: int = 3) -> Counter:
    df = load_signal_csv(path)
    if side == "LONG":
        comps = LONG_COMPONENTS
    elif side == "SHORT":
        comps = SHORT_COMPONENTS
    else:
        comps = LONG_COMPONENTS + SHORT_COMPONENTS

    combo_counter: Counter = Counter()
    for _, row in df.iterrows():
        active = [comp for comp in comps if row.get(f"{comp}_active", False)]
        for size in range(2, min(max_size, len(active)) + 1):
            for combo in combinations(active, size):
                combo_counter[combo] += 1
    return combo_counter


def score_band_counts(path: str):
    df = load_signal_csv(path)
    bands = {
        "<50": (df["score"] < 50),
        "50_54": (df["score"].between(50, 54)),
        "55_59": (df["score"].between(55, 59)),
        "60_63": (df["score"].between(60, 63)),
        ">=64": (df["score"] >= 64),
    }
    return {label: int(mask.sum()) for label, mask in bands.items()}
