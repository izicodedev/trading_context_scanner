from __future__ import annotations

import csv
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory

from .config import settings
from .db import ensure_signal_table, fetch_signal_rows, get_database_url


def get_base_url() -> str:
    return os.getenv("WEB_BASE_URL", settings.web_base_url or "http://localhost:5000")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"), static_folder=str(BASE_DIR / "static"))


@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin")
    allowed = ["http://localhost:5173", "http://127.0.0.1:5173"]
    if origin in allowed:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


def parse_timestamp(value):
    if value in (None, "", "-"):
        return None
    value = str(value).strip()
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S,%f")
        except ValueError:
            try:
                dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _normalize_bool(value):
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _read_csv(path: str | Path):
    file_path = Path(path)
    if not file_path.exists():
        return []
    with file_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def _read_postgres_rows(limit: int | None = None):
    if not get_database_url():
        return []
    rows = fetch_signal_rows(limit=limit)
    for row in rows:
        value = row.get("timestamp")
        if hasattr(value, "isoformat"):
            row["timestamp"] = value.isoformat()
    return rows


def _metric_or_none(value):
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_signal_rows():
    if get_database_url():
        rows = _read_postgres_rows()
    else:
        rows = _read_csv(DATA_DIR / "signals.csv")

    for row in rows:
        row["timestamp_dt"] = parse_timestamp(row.get("timestamp"))
        row["score_int"] = int(row.get("score", 0) or 0)
        row["price_float"] = _metric_or_none(row.get("price"))
        row["entry_float"] = _metric_or_none(row.get("entry"))
        row["stop_float"] = _metric_or_none(row.get("stop"))
        row["target_float"] = _metric_or_none(row.get("target"))
        row["ema21"] = _metric_or_none(row.get("ema21"))
        row["ema50"] = _metric_or_none(row.get("ema50"))
        row["rsi"] = _metric_or_none(row.get("rsi"))
        row["atr"] = _metric_or_none(row.get("atr"))
        row["vol_ratio"] = _metric_or_none(row.get("vol_ratio"))
        row["long_score_int"] = int(row.get("long_score", 0) or 0)
        row["short_score_int"] = int(row.get("short_score", 0) or 0)
        row["signal_state"] = row.get("signal_state", "SIGNAL")
        row["setup_state"] = row.get("setup_state", "UNSET")
        row["entry_state"] = row.get("entry_state", "UNSET")

    if get_database_url():
        rows = sorted(rows, key=lambda row: row.get("timestamp_dt") or datetime.min.replace(tzinfo=timezone.utc))
    return rows


def load_evaluation_rows():
    rows = _read_csv(DATA_DIR / "signal_evaluation.csv")
    for row in rows:
        row["signal_timestamp_dt"] = parse_timestamp(row.get("signal_timestamp"))
        for key in [
            "signal_score",
            "price",
            "long_score",
            "short_score",
            "price_after_1",
            "price_after_3",
            "price_after_5",
            "price_after_10",
            "ret_1",
            "ret_3",
            "ret_5",
            "ret_10",
            "mfe",
            "mae",
            "max_favorable_move",
            "max_adverse_move",
        ]:
            row[key] = _metric_or_none(row.get(key))
    return rows


def _latest_file_mtime(path: str | Path):
    p = Path(path)
    if not p.exists():
        return None
    return datetime.fromtimestamp(p.stat().st_mtime)


def _status_label_from_seconds(seconds: float | None):
    if seconds is None:
        return "OFFLINE"
    return "ONLINE" if seconds < 600 else "OFFLINE"


def build_status_payload():
    signals = load_signal_rows()
    last_signal = signals[-1] if signals else {}
    last_mtime = _latest_file_mtime(DATA_DIR / "signals.csv")
    now = datetime.now(timezone.utc)
    last_time = parse_timestamp(last_signal.get("timestamp"))
    if last_time and last_time.tzinfo is None:
        last_time = last_time.replace(tzinfo=timezone.utc)
    status_seconds = (now - last_time).total_seconds() if last_time else None
    return {
        "scanner_status": _status_label_from_seconds(status_seconds),
        "last_update": last_signal.get("timestamp") or "N/D",
        "market": settings.symbol,
        "timeframe": f"{settings.context_interval}/{settings.structure_interval}/{settings.trigger_interval}",
        "threshold": settings.min_score,
        "price": last_signal.get("price") or "N/D",
        "long_score": last_signal.get("long_score", "N/D"),
        "short_score": last_signal.get("short_score", "N/D"),
        "state": last_signal.get("entry_state", "UNSET") if last_signal else "UNSET",
        "signal_state": last_signal.get("signal_state", "SIGNAL") if last_signal else "SIGNAL",
        "setup_state": last_signal.get("setup_state", "UNSET") if last_signal else "UNSET",
        "entry_state": last_signal.get("entry_state", "UNSET") if last_signal else "UNSET",
        "last_file_update": last_mtime.isoformat() if last_mtime else "N/D",
        "signals_total": len(signals),
        "entries_total": sum(1 for row in signals if str(row.get("entry_state", "")).upper() == "ENTRY"),
        "signal_total": sum(1 for row in signals if str(row.get("signal_state", "")).upper() == "SIGNAL"),
        "setup_total": sum(1 for row in signals if str(row.get("setup_state", "")).upper() == "SETUP"),
    }


def build_history_payload(limit: int = 200):
    rows = load_signal_rows()
    rows = sorted(rows, key=lambda r: r.get("timestamp_dt") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return rows[:limit]


def build_components_payload():
    rows = load_signal_rows()
    if not rows:
        return []

    component_names = [
        "long_trend_ema", "long_price_above_ema", "long_rsi_favorable", "long_rsi_extreme",
        "long_volume_confirmation", "long_fib", "long_liquidity_sweep", "long_structure",
        "short_trend_ema", "short_price_below_ema", "short_rsi_favorable", "short_rsi_extreme",
        "short_volume_confirmation", "short_fib", "short_liquidity_sweep", "short_structure",
    ]
    if not any(f"{name}_active" in row for row in rows for name in component_names):
        return []

    summary = []
    for name in component_names:
        active_col = f"{name}_active"
        points_col = f"{name}_points"
        total_active = 0
        total_points = 0.0
        for row in rows:
            if _normalize_bool(row.get(active_col)):
                total_active += 1
                total_points += float(row.get(points_col, 0) or 0)
        summary.append({
            "name": name,
            "activation_count": total_active,
            "points_total": total_points,
            "points_avg": round(total_points / len(rows), 4) if rows else 0,
        })
    return summary


def build_entries_payload():
    rows = load_signal_rows()
    entries = []
    for row in rows:
        if str(row.get("entry_state", "")).upper() == "ENTRY":
            entries.append(row)
    return entries


def build_evaluation_payload():
    rows = load_evaluation_rows()
    return rows


@app.route("/")
def index():
    return render_template("index.html", base_url=get_base_url())


@app.route("/api/status")
def api_status():
    return jsonify(build_status_payload())


@app.route("/api/history")
def api_history():
    limit = max(1, min(500, int(request.args.get("limit", 200))))
    return jsonify(build_history_payload(limit=limit))


@app.route("/api/components")
def api_components():
    return jsonify(build_components_payload())


@app.route("/api/entries")
def api_entries():
    return jsonify(build_entries_payload())


@app.route("/api/evaluation")
def api_evaluation():
    return jsonify(build_evaluation_payload())


@app.route("/api/summary")
def api_summary():
    rows = load_signal_rows()
    summary = defaultdict(float)
    for row in rows:
        summary["price"] = float(row.get("price_float") or summary["price"] or 0.0)
        summary["score"] = float(row.get("score_int") or summary["score"] or 0.0)
    return jsonify({
        "total_rows": len(rows),
        "status": build_status_payload(),
        "components": build_components_payload(),
    })


@app.route("/robots.txt")
def robots():
    return send_from_directory(str(BASE_DIR), "robots.txt")


@app.route("/sitemap.xml")
def sitemap():
    return send_from_directory(str(BASE_DIR), "sitemap.xml")


@app.route("/favicon.svg")
def favicon():
    return send_from_directory(str(BASE_DIR / "static"), "favicon.svg")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
