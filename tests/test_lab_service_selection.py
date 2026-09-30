"""Selection changes in paper trading must appear in the active session."""
from datetime import timedelta

import pandas as pd

from app import lab_service
from app.strategy_research import candidates


class Connection:
    def __init__(self, active):
        self.active = active
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, params):
        self.queries.append((query, params))
        if "SELECT active FROM strategy_sessions" in query:
            row = {"active": self.active}
            return type("Result", (), {"fetchone": lambda self: row})()
        return type("Result", (), {"fetchone": lambda self: None})()


def test_save_replaces_active_paper_session_and_archives_previous(monkeypatch):
    conn = Connection(active=True)
    monkeypatch.setattr(lab_service, "_connect", lambda: conn)
    opens = pd.date_range("2026-09-01", periods=4, freq="5min", tz="UTC")
    frame = pd.DataFrame({"open_time": opens,
                          "close_time": opens + timedelta(minutes=5) - timedelta(milliseconds=1)})
    monkeypatch.setattr(lab_service, "_history", lambda *_, **__: frame)
    old, new = candidates()[0], next(item for item in candidates() if item.key == "breakout_retest_0")
    research = {"validation_start": opens[2].isoformat(), "validation_end": frame.iloc[-1].close_time.isoformat(),
                "training": [], "validation": [], "trials": [], "assessments": []}
    monkeypatch.setattr(lab_service, "select_strategies", lambda *args: ([old], research))
    monkeypatch.setattr(lab_service, "selected_for_session", lambda *args: [new])
    monkeypatch.setattr(lab_service, "replay", lambda *args, **kwargs: {
        "closed_trades": 20, "net_pnl": 1, "profit_factor": 2,
        "total_return_pct": 1, "max_drawdown_pct": 1})

    assert lab_service.start(7, "ETHUSDT", refresh_active=True) is True
    assert any("INSERT INTO strategy_session_archive" in query for query, _ in conn.queries)
    saved = next(params for query, params in conn.queries if "INSERT INTO strategy_sessions" in query)
    assert saved[1] == "ETHUSDT" and saved[2] is True
    assert saved[-1].obj["strategy_definitions"][0]["key"] == "breakout_retest_0"


def test_save_does_not_start_a_stopped_paper_session(monkeypatch):
    conn = Connection(active=False)
    monkeypatch.setattr(lab_service, "_connect", lambda: conn)
    monkeypatch.setattr(lab_service, "_history", lambda *_, **__: (_ for _ in ()).throw(AssertionError("no replay")))
    assert lab_service.start(7, "ETHUSDT", refresh_active=True) is False
    assert not any("INSERT INTO strategy_sessions" in query for query, _ in conn.queries)
