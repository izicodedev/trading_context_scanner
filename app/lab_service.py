"""Durable per-user simulation sessions. The worker progresses without a browser."""
from dataclasses import asdict

import pandas as pd
from psycopg.types.json import Jsonb

from .candle_storage import _connect, CANDLE_COLUMNS, MARKET_SOURCE
from .strategy_lab import LabConfig, Strategy, STRATEGIES, replay, validate_history
from .strategy_research import select_strategies, candidates
from .user_strategies import selected_for_session
from .symbols import DEFAULT_SYMBOL, validate_symbol


def _history(conn, start=None, symbol=DEFAULT_SYMBOL):
    validate_symbol(symbol)
    if start is None:
        records = conn.execute("""SELECT * FROM (
            SELECT open_time, close_time, open, high, low, close, volume FROM market_candles
            WHERE source=%s AND symbol=%s AND timeframe='5m' AND close_time < NOW()
            ORDER BY open_time DESC LIMIT 8640) recent ORDER BY open_time""", (MARKET_SOURCE, symbol)).fetchall()
    else:
        records = conn.execute("""SELECT open_time, close_time, open, high, low, close, volume
            FROM market_candles WHERE source=%s AND symbol=%s AND timeframe='5m'
            AND open_time >= %s AND close_time < NOW() ORDER BY open_time LIMIT 50001""",
            (MARKET_SOURCE, symbol, start)).fetchall()
        if len(records) > 50000:
            raise ValueError("Sessão atingiu 50.000 candles. Pare e inicie uma nova sessão.")
    frame = pd.DataFrame(records, columns=CANDLE_COLUMNS)
    validate_history(frame)
    return frame


def status(user_id, symbol=DEFAULT_SYMBOL):
    validate_symbol(symbol)
    with _connect() as conn:
        row = conn.execute("SELECT * FROM strategy_sessions WHERE user_id=%s AND symbol=%s", (user_id, symbol)).fetchone()
    if row is None:
        return dict(active=False, symbol=symbol, snapshot=None, configuration=asdict(LabConfig()),
                    strategies=[asdict(s) for s in candidates()[:9:3]])
    for key, value in row.items():
        if hasattr(value, "isoformat"):
            row[key] = value.isoformat()
    row["strategies"] = row["snapshot"].get("strategy_definitions", [asdict(s) for s in STRATEGIES])
    return row


def start(user_id, symbol=DEFAULT_SYMBOL):
    validate_symbol(symbol)
    config = LabConfig()
    with _connect() as conn:
        # Also serializes concurrent starts when a session row doesn't yet exist.
        conn.execute("SELECT id FROM users WHERE id=%s FOR UPDATE", (user_id,))
        existing = conn.execute("SELECT active FROM strategy_sessions WHERE user_id=%s AND symbol=%s FOR UPDATE", (user_id, symbol)).fetchone()
        if existing and existing["active"]:
            return
        frame = _history(conn, symbol=symbol)
        selected, research = select_strategies(frame, config, symbol)
        chosen = selected_for_session(conn, user_id, symbol)
        if chosen:
            selected = chosen
            research["selection_message"] = None
            validation_start = pd.Timestamp(research["validation_start"])
            research_frame = frame.loc[frame.close_time <= pd.Timestamp(research["validation_end"])]
            discovery_frame = research_frame.loc[research_frame.close_time < validation_start]
            training = [replay(discovery_frame, strategy, config, stop=True, symbol=symbol) for strategy in selected]
            validation = [replay(research_frame, strategy, config, live_start=validation_start, stop=True, symbol=symbol)
                          for strategy in selected]
            research["training"] = training
            research["validation"] = validation
            research["assessments"] = [dict(key=strategy.key,
                status="insufficient_sample" if train["closed_trades"] < 5 or test["closed_trades"] < 15
                else "promising" if test["net_pnl"] > 0 and (test["profit_factor"] or 0) > 1
                else "not_confirmed", discovery_trades=train["closed_trades"],
                validation_trades=test["closed_trades"])
                for strategy, train, test in zip(selected, training, validation)]
            known = {item["strategy"]["key"] for item in research["trials"]}
            research["trials"].extend(dict(strategy=asdict(strategy),
                discovery_return=train["total_return_pct"],
                discovery_drawdown=train["max_drawdown_pct"], trades=train["closed_trades"])
                for strategy, train in zip(selected, training) if strategy.key not in known)
            research["method"] = "Seleção do usuário; descoberta e validação temporal separadas"
        research["selected_manually"] = bool(chosen)
        research["custom_tested"] = sum(strategy.entry_rule is not None for strategy in selected)
        # Forward session begins only after selection has finished.
        started = pd.Timestamp.now(tz="UTC")
        active = bool(selected)
        historical = research["validation"]
        live = [replay(frame, strategy, config, live_start=started, symbol=symbol) for strategy in selected]
        snapshot = dict(historical=historical, live=live, source=MARKET_SOURCE,
                        symbol=symbol, timeframe="5m", history_candles=len(frame),
                        strategy_definitions=[asdict(s) for s in selected], research=research)
        if existing:
            conn.execute("""INSERT INTO strategy_session_archive(user_id, session_data)
                SELECT user_id, to_jsonb(strategy_sessions) FROM strategy_sessions WHERE user_id=%s AND symbol=%s""", (user_id, symbol))
        conn.execute("""INSERT INTO strategy_sessions
            (user_id, symbol, active, started_at, history_start, history_end, processed_through,
             configuration, snapshot, heartbeat)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT(user_id,symbol) DO UPDATE SET active=EXCLUDED.active, started_at=EXCLUDED.started_at,
            history_start=EXCLUDED.history_start, history_end=EXCLUDED.history_end,
            processed_through=EXCLUDED.processed_through, configuration=EXCLUDED.configuration,
            snapshot=EXCLUDED.snapshot, heartbeat=NOW(),
            stopped_at=CASE WHEN EXCLUDED.active THEN NULL ELSE NOW() END, last_error=NULL""",
            (user_id, symbol, active, started.to_pydatetime(), frame.iloc[0].open_time,
             frame.iloc[-1].close_time, frame.iloc[-1].close_time,
             Jsonb(asdict(config)), Jsonb(snapshot)))


def advance(user_id, stopping=False, symbol=DEFAULT_SYMBOL):
    validate_symbol(symbol)
    with _connect() as conn:
        row = conn.execute("SELECT * FROM strategy_sessions WHERE user_id=%s AND symbol=%s FOR UPDATE", (user_id, symbol)).fetchone()
        if row is None or not row["active"]:
            return
        config = LabConfig(**row["configuration"])
        try:
            frame = _history(conn, row["history_start"], symbol)
            cutoff = frame.iloc[-1].close_time
            snapshot = row["snapshot"]
            selected = [Strategy(**item) for item in snapshot.get("strategy_definitions", [asdict(s) for s in STRATEGIES])]
            if stopping or cutoff != row["processed_through"]:
                snapshot["live"] = [replay(frame, strategy, config,
                                           live_start=pd.Timestamp(row["started_at"]), stop=stopping,
                                           symbol=symbol)
                                    for strategy in selected]
            conn.execute("""UPDATE strategy_sessions SET snapshot=%s, processed_through=%s,
                heartbeat=NOW(), last_error=NULL, active=%s,
                stopped_at=CASE WHEN %s THEN NOW() ELSE NULL END WHERE user_id=%s AND symbol=%s""",
                (Jsonb(snapshot), cutoff, not stopping, stopping, user_id, symbol))
        except ValueError as exc:
            # Persist actionable data-quality errors; do not silently skip missing bars.
            conn.execute("""UPDATE strategy_sessions SET heartbeat=NOW(), last_error=%s,
                active=%s, stopped_at=CASE WHEN %s THEN NOW() ELSE stopped_at END WHERE user_id=%s AND symbol=%s""",
                (str(exc), not stopping, stopping, user_id, symbol))


def tick():
    with _connect() as conn:
        users = conn.execute("SELECT user_id, symbol FROM strategy_sessions WHERE active=TRUE").fetchall()
    for row in users:
        try:
            advance(row["user_id"], symbol=row["symbol"])
        except Exception:
            import logging
            logging.exception("Strategy worker failed for a session")
