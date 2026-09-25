from __future__ import annotations
import csv, os
from dataclasses import asdict

from .db import SIGNAL_COLUMNS, ensure_signal_table, get_database_url, insert_signal_record, signal_record_from_signal
from .evaluation import SignalEvaluation
from .strategy import Signal, validate_component_totals

LONG_COMPONENT_KEYS = [
    "long_trend_ema",
    "long_price_above_ema",
    "long_rsi_favorable",
    "long_rsi_extreme",
    "long_volume_confirmation",
    "long_fib",
    "long_liquidity_sweep",
    "long_structure",
]

SHORT_COMPONENT_KEYS = [
    "short_trend_ema",
    "short_price_below_ema",
    "short_rsi_favorable",
    "short_rsi_extreme",
    "short_volume_confirmation",
    "short_fib",
    "short_liquidity_sweep",
    "short_structure",
]

BASE_FIELDS = [
    "timestamp","side","score","price","entry","stop","target","reasons",
    "long_score","short_score","ema21","ema50","rsi","atr","vol_ratio",
    "trend_bias","signal_state","setup_state","entry_state",
]

FIELDS = BASE_FIELDS + [
    f"{key}_active" for key in LONG_COMPONENT_KEYS + SHORT_COMPONENT_KEYS
] + [
    f"{key}_points" for key in LONG_COMPONENT_KEYS + SHORT_COMPONENT_KEYS
] + [
    f"{key}_value" for key in LONG_COMPONENT_KEYS + SHORT_COMPONENT_KEYS
]

EVALUATION_FIELDS = [
    "signal_timestamp","signal_side","signal_score","price","long_score","short_score",
    "trend_bias","price_after_1","price_after_3","price_after_5","price_after_10",
    "ret_1","ret_3","ret_5","ret_10","mfe","mae","max_favorable_move","max_adverse_move","outcome",
]


def _legacy_csv_save(signal: Signal, path: str):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if not exists:
            writer.writeheader()
        row = asdict(signal)
        row["reasons"] = " | ".join(signal.reasons)
        for key, comp in signal.long_components.items():
            row[f"{key}_active"] = bool(comp.active)
            row[f"{key}_points"] = int(comp.points)
            row[f"{key}_value"] = "" if comp.value is None else comp.value
        for key, comp in signal.short_components.items():
            row[f"{key}_active"] = bool(comp.active)
            row[f"{key}_points"] = int(comp.points)
            row[f"{key}_value"] = "" if comp.value is None else comp.value
        writer.writerow({k: row.get(k, "") for k in FIELDS})


def _db_save(signal: Signal):
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg is required for PostgreSQL storage") from exc

    database_url = get_database_url()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    conn = psycopg.connect(database_url)
    try:
        ensure_signal_table(conn)
        record = signal_record_from_signal(signal)
        insert_signal_record(conn, record)
    finally:
        conn.close()


def flatten_components(components):
    flattened = {}
    for key, comp in components.items():
        flattened[f"{key}_active"] = bool(comp.active)
        flattened[f"{key}_points"] = int(comp.points)
        flattened[f"{key}_value"] = "" if comp.value is None else comp.value
    return flattened


def ensure_signal_schema(path: str):
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
        return

    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        existing_fields = reader.fieldnames or []

    missing = [field for field in FIELDS if field not in existing_fields]
    if not missing:
        return

    rows = []
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            normalized = {key: row.get(key, "") for key in existing_fields}
            for field in missing:
                normalized[field] = ""
            rows.append(normalized)

    merged_fields = existing_fields + [field for field in FIELDS if field not in existing_fields]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=merged_fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in merged_fields})


def save(signal: Signal, path: str | None = None):
    validate_component_totals(signal)
    if get_database_url():
        _db_save(signal)
        return
    if path is None:
        raise RuntimeError("CSV path is required when DATABASE_URL is not configured")
    ensure_signal_schema(path)
    _legacy_csv_save(signal, path)


def save_evaluation(evaluation: SignalEvaluation, path: str):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=EVALUATION_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(asdict(evaluation))
