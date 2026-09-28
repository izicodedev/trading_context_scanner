"""Durable per-user simulation sessions. The worker progresses without a browser."""
from dataclasses import asdict

import pandas as pd
from psycopg.types.json import Jsonb

from .candle_storage import _connect, CANDLE_COLUMNS, MARKET_SOURCE
from .strategy_lab import LabConfig, Strategy, STRATEGIES, replay, validate_history
from .strategy_research import select_strategies, candidates


def _history(conn, start=None):
    if start is None:
        records = conn.execute("""SELECT * FROM (
            SELECT open_time, close_time, open, high, low, close, volume FROM market_candles
            WHERE source=%s AND symbol='BTCUSDT' AND timeframe='5m' AND close_time < NOW()
            ORDER BY open_time DESC LIMIT 8640) recent ORDER BY open_time""", (MARKET_SOURCE,)).fetchall()
    else:
        records = conn.execute("""SELECT open_time, close_time, open, high, low, close, volume
            FROM market_candles WHERE source=%s AND symbol='BTCUSDT' AND timeframe='5m'
            AND open_time >= %s AND close_time < NOW() ORDER BY open_time LIMIT 50001""",
            (MARKET_SOURCE, start)).fetchall()
        if len(records) > 50000:
            raise ValueError("Sessão atingiu 50.000 candles. Pare e inicie uma nova sessão.")
    frame = pd.DataFrame(records, columns=CANDLE_COLUMNS)
    validate_history(frame)
    return frame


def status(user_id):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM strategy_sessions WHERE user_id=%s", (user_id,)).fetchone()
    if row is None:
        return dict(active=False, snapshot=None, configuration=asdict(LabConfig()),
                    strategies=[asdict(s) for s in candidates()[:9:3]])
    for key, value in row.items():
        if hasattr(value, "isoformat"):
            row[key] = value.isoformat()
    row["strategies"] = row["snapshot"].get("strategy_definitions", [asdict(s) for s in STRATEGIES])
    return row


def start(user_id):
    config = LabConfig()
    with _connect() as conn:
        # Also serializes concurrent starts when a session row doesn't yet exist.
        conn.execute("SELECT id FROM users WHERE id=%s FOR UPDATE", (user_id,))
        existing = conn.execute("SELECT active FROM strategy_sessions WHERE user_id=%s FOR UPDATE", (user_id,)).fetchone()
        if existing and existing["active"]:
            return
        frame = _history(conn)
        selected, research = select_strategies(frame, config)
        # Forward session begins only after selection has finished.
        started = pd.Timestamp.now(tz="UTC")
        historical = research["validation"]
        live = [replay(frame, strategy, config, live_start=started) for strategy in selected]
        snapshot = dict(historical=historical, live=live, source=MARKET_SOURCE,
                        symbol="BTCUSDT", timeframe="5m", history_candles=len(frame),
                        strategy_definitions=[asdict(s) for s in selected], research=research)
        if existing:
            conn.execute("""INSERT INTO strategy_session_archive(user_id, session_data)
                SELECT user_id, to_jsonb(strategy_sessions) FROM strategy_sessions WHERE user_id=%s""", (user_id,))
        conn.execute("""INSERT INTO strategy_sessions
            (user_id, active, started_at, history_start, history_end, processed_through,
             configuration, snapshot, heartbeat)
            VALUES (%s, TRUE, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT(user_id) DO UPDATE SET active=TRUE, started_at=EXCLUDED.started_at,
            history_start=EXCLUDED.history_start, history_end=EXCLUDED.history_end,
            processed_through=EXCLUDED.processed_through, configuration=EXCLUDED.configuration,
            snapshot=EXCLUDED.snapshot, heartbeat=NOW(), stopped_at=NULL, last_error=NULL""",
            (user_id, started.to_pydatetime(), frame.iloc[0].open_time,
             frame.iloc[-1].close_time, frame.iloc[-1].close_time,
             Jsonb(asdict(config)), Jsonb(snapshot)))


def advance(user_id, stopping=False):
    with _connect() as conn:
        row = conn.execute("SELECT * FROM strategy_sessions WHERE user_id=%s FOR UPDATE", (user_id,)).fetchone()
        if row is None or not row["active"]:
            return
        config = LabConfig(**row["configuration"])
        try:
            frame = _history(conn, row["history_start"])
            cutoff = frame.iloc[-1].close_time
            snapshot = row["snapshot"]
            selected = [Strategy(**item) for item in snapshot.get("strategy_definitions", [asdict(s) for s in STRATEGIES])]
            if stopping or cutoff != row["processed_through"]:
                snapshot["live"] = [replay(frame, strategy, config,
                                           live_start=pd.Timestamp(row["started_at"]), stop=stopping)
                                    for strategy in selected]
            conn.execute("""UPDATE strategy_sessions SET snapshot=%s, processed_through=%s,
                heartbeat=NOW(), last_error=NULL, active=%s,
                stopped_at=CASE WHEN %s THEN NOW() ELSE NULL END WHERE user_id=%s""",
                (Jsonb(snapshot), cutoff, not stopping, stopping, user_id))
        except ValueError as exc:
            # Persist actionable data-quality errors; do not silently skip missing bars.
            conn.execute("""UPDATE strategy_sessions SET heartbeat=NOW(), last_error=%s,
                active=%s, stopped_at=CASE WHEN %s THEN NOW() ELSE stopped_at END WHERE user_id=%s""",
                (str(exc), not stopping, stopping, user_id))


def tick():
    with _connect() as conn:
        users = conn.execute("SELECT user_id FROM strategy_sessions WHERE active=TRUE").fetchall()
    for row in users:
        try:
            advance(row["user_id"])
        except Exception:
            import logging
            logging.exception("Strategy worker failed for a session")
