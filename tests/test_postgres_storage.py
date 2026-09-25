import csv
import os
import sys
import types

from app.db import SIGNAL_COLUMNS, is_synthetic_signal_row, signals_table_sql
from app.migrate_csv import migrate_csv_to_postgres
from app.storage import save


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        self.conn.sql.append((sql, params))


class FakeConnection:
    def __init__(self):
        self.sql = []

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        pass

    def close(self):
        pass


def test_signals_table_sql_has_no_duplicate_columns():
    sql = signals_table_sql()
    defs = sql.split("(", 1)[1].rsplit(")", 1)[0].split(", ")
    column_names = [part.split()[0] for part in defs]
    assert len(column_names) == len(set(column_names))
    assert column_names.count("entry_state") == 1


def test_save_uses_postgres_when_database_url_is_configured(monkeypatch):
    fake_conn = FakeConnection()

    def fake_connect(url):
        assert url == "postgresql://user:pass@localhost:5432/trading_context_scanner"
        return fake_conn

    fake_psycopg = types.SimpleNamespace(connect=fake_connect)
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/trading_context_scanner")

    class DummyComp:
        def __init__(self):
            self.active = True
            self.points = 20
            self.value = 1.5

    signal = types.SimpleNamespace(
        timestamp="2026-09-25 11:00:00+00:00",
        side="LONG",
        score=20,
        price=100.0,
        entry=95.0,
        stop=90.0,
        target=110.0,
        reasons=["test"],
        long_score=20,
        short_score=0,
        ema21=101.0,
        ema50=100.0,
        rsi=60.0,
        atr=1.0,
        vol_ratio=1.2,
        trend_bias="LONG",
        signal_state="SIGNAL",
        setup_state="SETUP",
        entry_state="ENTRY",
        long_components={"long_trend_ema": DummyComp()},
        short_components={},
    )

    save(signal, "ignored.csv")
    assert any("INSERT INTO signals" in sql for sql, _ in fake_conn.sql)


def test_save_inserts_full_instrumented_signal(monkeypatch):
    fake_conn = FakeConnection()

    def fake_connect(url):
        assert url == "******localhost:5432/trading_context_scanner"
        return fake_conn

    fake_psycopg = types.SimpleNamespace(connect=fake_connect)
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)
    monkeypatch.setenv("DATABASE_URL", "******localhost:5432/trading_context_scanner")

    class DummyComp:
        def __init__(self, active, points, value):
            self.active = active
            self.points = points
            self.value = value

    signal = types.SimpleNamespace(
        timestamp="2026-09-25 11:00:00+00:00",
        side="LONG",
        score=40,
        price=100.0,
        entry=95.0,
        stop=90.0,
        target=110.0,
        reasons=["test"],
        long_score=40,
        short_score=0,
        ema21=101.0,
        ema50=100.0,
        rsi=60.0,
        atr=1.0,
        vol_ratio=1.2,
        trend_bias="LONG",
        signal_state="SIGNAL",
        setup_state="SETUP",
        entry_state="ENTRY",
        long_components={
            "long_trend_ema": DummyComp(True, 20, 1.0),
            "long_price_above_ema": DummyComp(True, 8, 1.5),
            "long_rsi_favorable": DummyComp(True, 12, 60.0),
            "long_rsi_extreme": DummyComp(False, 0, 0.0),
            "long_volume_confirmation": DummyComp(False, 0, 0.0),
            "long_fib": DummyComp(False, 0, 0.0),
            "long_liquidity_sweep": DummyComp(False, 0, 0.0),
            "long_structure": DummyComp(False, 0, 0.0),
        },
        short_components={
            "short_trend_ema": DummyComp(False, 0, 0.0),
            "short_price_below_ema": DummyComp(False, 0, 0.0),
            "short_rsi_favorable": DummyComp(False, 0, 0.0),
            "short_rsi_extreme": DummyComp(False, 0, 0.0),
            "short_volume_confirmation": DummyComp(False, 0, 0.0),
            "short_fib": DummyComp(False, 0, 0.0),
            "short_liquidity_sweep": DummyComp(False, 0, 0.0),
            "short_structure": DummyComp(False, 0, 0.0),
        },
    )

    save(signal, "ignored.csv")
    sql = "\n".join(sql_text for sql_text, _ in fake_conn.sql)
    assert "INSERT INTO signals" in sql
    assert "long_trend_ema_active" in sql
    assert "long_trend_ema_points" in sql
    assert "long_rsi_favorable_active" in sql
    assert "short_trend_ema_active" in sql
    assert "short_trend_ema_points" in sql
    assert "score" in sql
    assert "long_score" in sql
    assert "short_score" in sql


def test_save_allows_multiple_rows_with_same_timestamp(monkeypatch):
    fake_conn = FakeConnection()

    def fake_connect(url):
        return fake_conn

    fake_psycopg = types.SimpleNamespace(connect=fake_connect)
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/trading_context_scanner")

    class DummyComp:
        def __init__(self, active, points, value):
            self.active = active
            self.points = points
            self.value = value

    def build_signal(label, score, side):
        return types.SimpleNamespace(
            timestamp="2026-09-25 11:00:00+00:00",
            side=side,
            score=score,
            price=100.0 + (label == "second"),
            entry=95.0,
            stop=90.0,
            target=110.0,
            reasons=[label],
            long_score=score if side == "LONG" else 0,
            short_score=score if side == "SHORT" else 0,
            ema21=101.0,
            ema50=100.0,
            rsi=60.0,
            atr=1.0,
            vol_ratio=1.2,
            trend_bias=side,
            signal_state="SIGNAL",
            setup_state="SETUP",
            entry_state="ENTRY",
            long_components={"long_trend_ema": DummyComp(side == "LONG", score, 1.0)} if side == "LONG" else {},
            short_components={"short_trend_ema": DummyComp(side == "SHORT", score, 1.0)} if side == "SHORT" else {},
        )

    save(build_signal("first", 20, "LONG"), "ignored.csv")
    save(build_signal("second", 25, "LONG"), "ignored.csv")

    inserts = [sql for sql, _ in fake_conn.sql if "INSERT INTO signals" in str(sql)]
    assert len(inserts) == 2


def test_csv_migration_skips_synthetic_rows(monkeypatch, tmp_path):
    fake_conn = FakeConnection()
    fake_psycopg = types.SimpleNamespace(connect=lambda url: fake_conn)
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/trading_context_scanner")

    csv_path = tmp_path / "synthetic_signals.csv"
    rows = [
        {
            "timestamp": "2026-09-25 11:00:00+00:00",
            "side": "WAIT",
            "score": "30",
            "price": "100",
            "entry": "",
            "stop": "",
            "target": "",
            "reasons": "LONG=15 | SHORT=30",
            "long_score": "15",
            "short_score": "30",
            "ema21": "101",
            "ema50": "100.5",
            "rsi": "55",
            "atr": "1.0",
            "vol_ratio": "1.1",
            "trend_bias": "LONG",
            "signal_state": "SIGNAL",
            "setup_state": "NO_SETUP",
            "entry_state": "NO_ENTRY",
            "long_trend_ema_active": "true",
            "long_trend_ema_points": "15",
            "long_trend_ema_value": "0.5",
            "short_trend_ema_active": "false",
            "short_trend_ema_points": "0",
            "short_trend_ema_value": "0",
        },
        {
            "timestamp": "2026-01-01 04:59:00",
            "side": "WAIT",
            "score": "45",
            "price": "62916.89",
            "entry": "",
            "stop": "",
            "target": "",
            "reasons": "synthetic",
            "long_score": "45",
            "short_score": "15",
            "ema21": "101",
            "ema50": "100",
            "rsi": "67",
            "atr": "155",
            "vol_ratio": "0.57",
            "trend_bias": "LONG",
            "signal_state": "SIGNAL",
            "setup_state": "NO_SETUP",
            "entry_state": "NO_ENTRY",
            "long_trend_ema_active": "true",
            "long_trend_ema_points": "45",
            "long_trend_ema_value": "60",
            "short_trend_ema_active": "false",
            "short_trend_ema_points": "0",
            "short_trend_ema_value": "0",
        },
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    summary = migrate_csv_to_postgres(str(csv_path))
    assert summary.total == 2
    assert summary.migrated == 1
    assert summary.rejected == 1
    assert is_synthetic_signal_row(rows[1])
