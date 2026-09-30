from datetime import timedelta

import pandas as pd

from app import strategy_audit


def test_ninety_day_audit_keeps_future_bars_out_of_earlier_periods(monkeypatch):
    times = pd.date_range("2026-06-01T00:00:00Z", periods=25920, freq="5min")
    frame = pd.DataFrame({"open_time": times, "close_time": times + timedelta(minutes=5)})

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    monkeypatch.setattr(strategy_audit, "_connect", Connection)
    monkeypatch.setattr(strategy_audit, "_history", lambda conn, start=None, symbol=None: frame)
    candidate = strategy_audit.candidates()[0]
    monkeypatch.setattr(strategy_audit, "candidates", lambda: [candidate])
    calls = []

    def replay(data, strategy, config, live_start=None, stop=False, symbol=None):
        calls.append((data.iloc[0].open_time, data.iloc[-1].open_time, live_start, len(data)))
        return dict(closed_trades=20, net_pnl=1, profit_factor=2,
                    total_return_pct=1, max_drawdown_pct=0)

    monkeypatch.setattr(strategy_audit, "replay", replay)
    result = strategy_audit.audit("BTCUSDT", days=90)
    assert len(result) == 1
    assert result[0]["qualified"] is True
    assert calls[0] == (times[0], times[8639], None, 8640)
    assert calls[1] == (times[7640], times[17279], times[8640], 9640)
    assert calls[2] == (times[16280], times[-1], times[17280], 9640)
    assert calls[3] == calls[2]
