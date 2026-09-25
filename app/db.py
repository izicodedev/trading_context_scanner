from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Iterable


SIGNAL_TABLE = "signals"

SIGNAL_COLUMNS = [
    "timestamp", "side", "score", "price", "entry", "stop", "target", "reasons",
    "long_score", "short_score", "ema21", "ema50", "rsi", "atr", "vol_ratio",
    "trend_bias", "signal_state", "setup_state", "entry_state",
    "long_trend_ema_active", "long_price_above_ema_active", "long_rsi_favorable_active",
    "long_rsi_extreme_active", "long_volume_confirmation_active", "long_fib_active",
    "long_liquidity_sweep_active", "long_structure_active", "short_trend_ema_active",
    "short_price_below_ema_active", "short_rsi_favorable_active", "short_rsi_extreme_active",
    "short_volume_confirmation_active", "short_fib_active", "short_liquidity_sweep_active",
    "short_structure_active", "long_trend_ema_points", "long_price_above_ema_points",
    "long_rsi_favorable_points", "long_rsi_extreme_points", "long_volume_confirmation_points",
    "long_fib_points", "long_liquidity_sweep_points", "long_structure_points",
    "short_trend_ema_points", "short_price_below_ema_points", "short_rsi_favorable_points",
    "short_rsi_extreme_points", "short_volume_confirmation_points", "short_fib_points",
    "short_liquidity_sweep_points", "short_structure_points", "long_trend_ema_value",
    "long_price_above_ema_value", "long_rsi_favorable_value", "long_rsi_extreme_value",
    "long_volume_confirmation_value", "long_fib_value", "long_liquidity_sweep_value",
    "long_structure_value", "short_trend_ema_value", "short_price_below_ema_value",
    "short_rsi_favorable_value", "short_rsi_extreme_value", "short_volume_confirmation_value",
    "short_fib_value", "short_liquidity_sweep_value", "short_structure_value",
]


def get_database_url() -> str | None:
    return os.getenv("DATABASE_URL")


def fetch_signal_rows(limit: int | None = None, database_url: str | None = None) -> list[dict[str, Any]]:
    url = database_url or get_database_url()
    if not url:
        return []
    try:
        import psycopg
    except ImportError:
        return []

    conn = psycopg.connect(url)
    try:
        ensure_signal_table(conn)
        sql = "SELECT * FROM signals ORDER BY timestamp DESC"
        params: list[Any] = []
        if limit is not None:
            sql = "SELECT * FROM signals ORDER BY timestamp DESC LIMIT %s"
            params = [limit]
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [desc[0] for desc in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    finally:
        conn.close()

    normalized: list[dict[str, Any]] = []
    for row in rows:
        normalized_row = dict(row)
        ts_value = normalized_row.get("timestamp")
        if hasattr(ts_value, "isoformat"):
            normalized_row["timestamp"] = ts_value.isoformat()
        normalized.append(normalized_row)
    return normalized


def parse_timestamp(value: str | None):
    if value in (None, "", "-"):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt


def to_db_value(value: Any):
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if text in {"", "N/D", "-"}:
            return None
        return text
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    return value


def signals_table_sql() -> str:
    columns = [
        "timestamp TIMESTAMPTZ NOT NULL",
        "side TEXT",
        "score INTEGER",
        "price DOUBLE PRECISION",
        "entry DOUBLE PRECISION",
        "stop DOUBLE PRECISION",
        "target DOUBLE PRECISION",
        "reasons TEXT",
        "long_score INTEGER",
        "short_score INTEGER",
        "ema21 DOUBLE PRECISION",
        "ema50 DOUBLE PRECISION",
        "rsi DOUBLE PRECISION",
        "atr DOUBLE PRECISION",
        "vol_ratio DOUBLE PRECISION",
        "trend_bias TEXT",
        "signal_state TEXT",
        "setup_state TEXT",
        "entry_state TEXT",
    ]
    for field in SIGNAL_COLUMNS[19:]:
        if field.endswith("_active"):
            columns.append(f"{field} BOOLEAN")
        elif field.endswith("_points"):
            columns.append(f"{field} INTEGER")
        elif field.endswith("_value"):
            columns.append(f"{field} DOUBLE PRECISION")
        else:
            columns.append(f"{field} TEXT")
    columns.append("id BIGSERIAL PRIMARY KEY")
    return f"CREATE TABLE IF NOT EXISTS {SIGNAL_TABLE} ({', '.join(columns)});"


def ensure_signal_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(signals_table_sql())
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{SIGNAL_TABLE}_timestamp ON {SIGNAL_TABLE} (timestamp)")
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{SIGNAL_TABLE}_side ON {SIGNAL_TABLE} (side)")
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{SIGNAL_TABLE}_score ON {SIGNAL_TABLE} (score)")
    conn.commit()


def row_to_signal_record(row: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in SIGNAL_COLUMNS:
        value = row.get(key)
        if key == "timestamp":
            parsed = parse_timestamp(value)
            result[key] = parsed
        elif key in {"side", "reasons", "trend_bias", "signal_state", "setup_state", "entry_state"}:
            result[key] = to_db_value(value)
        else:
            result[key] = to_db_value(value)
    return result


def signal_record_from_signal(signal: Any) -> dict[str, Any]:
    row = {
        "timestamp": signal.timestamp,
        "side": signal.side,
        "score": signal.score,
        "price": signal.price,
        "entry": signal.entry,
        "stop": signal.stop,
        "target": signal.target,
        "reasons": " | ".join(signal.reasons),
        "long_score": signal.long_score,
        "short_score": signal.short_score,
        "ema21": signal.ema21,
        "ema50": signal.ema50,
        "rsi": signal.rsi,
        "atr": signal.atr,
        "vol_ratio": signal.vol_ratio,
        "trend_bias": signal.trend_bias,
        "signal_state": signal.signal_state,
        "setup_state": signal.setup_state,
        "entry_state": signal.entry_state,
    }
    for key, comp in getattr(signal, "long_components", {}).items():
        row[f"{key}_active"] = bool(comp.active)
        row[f"{key}_points"] = int(comp.points)
        row[f"{key}_value"] = comp.value
    for key, comp in getattr(signal, "short_components", {}).items():
        row[f"{key}_active"] = bool(comp.active)
        row[f"{key}_points"] = int(comp.points)
        row[f"{key}_value"] = comp.value
    for column in SIGNAL_COLUMNS:
        if column not in row:
            row[column] = None
    return row_to_signal_record(row)


def insert_signal_record(conn, record: dict[str, Any]) -> None:
    columns = list(SIGNAL_COLUMNS)
    values = []
    placeholders = []
    for col in columns:
        values.append(record.get(col))
        placeholders.append("%s")
    sql = f"INSERT INTO {SIGNAL_TABLE} ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"
    with conn.cursor() as cur:
        cur.execute(sql, values)
    conn.commit()


def is_synthetic_signal_row(row: dict[str, Any]) -> bool:
    ts = str(row.get("timestamp", ""))
    if "2026-01-01" in ts:
        return True
    side = str(row.get("side") or "").strip().upper()
    if side not in {"LONG", "SHORT", "WAIT"}:
        return True
    score_text = row.get("score")
    if score_text is not None and str(score_text).strip() == "45" and "2026-01-01" in ts:
        return True
    return False
