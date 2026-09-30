from app import hyperliquid_audit


def test_recent_perp_candles_use_public_info_and_validate_sequence(monkeypatch):
    start = 1767225600000
    rows = [dict(t=start + i * 300000, T=start + (i + 1) * 300000 - 1,
                 o="100", h="101", l="99", c="100", v="10") for i in range(61)]
    calls = []

    def fake_info(network, payload):
        calls.append((network, payload))
        return rows

    monkeypatch.setattr(hyperliquid_audit, "info", fake_info)
    frame = hyperliquid_audit.recent_candles("ETH")
    assert len(frame) == 61
    assert frame.iloc[0].open == 100
    assert calls[0][0] == "mainnet"
    assert calls[0][1]["type"] == "candleSnapshot"
    assert calls[0][1]["req"]["coin"] == "ETH"
    assert calls[0][1]["req"]["interval"] == "5m"
