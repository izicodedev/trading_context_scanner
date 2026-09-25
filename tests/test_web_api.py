from app.web import app


ENDPOINTS = [
    "/",
    "/api/status",
    "/api/history",
    "/api/components",
    "/api/entries",
    "/api/evaluation",
    "/api/summary",
]


def test_dashboard_endpoints_respond_and_use_real_data():
    client = app.test_client()

    for path in ENDPOINTS:
        response = client.get(path)
        assert response.status_code == 200, f"{path} did not return 200"

    status = client.get("/api/status").get_json()
    assert set(["scanner_status", "threshold", "price"]).issubset(status.keys())
    assert status["threshold"] == 65

    components = client.get("/api/components").get_json()
    assert isinstance(components, list)
    assert any(item["name"] == "long_trend_ema" for item in components)
    assert any(item["name"] == "short_trend_ema" for item in components)

    entries = client.get("/api/entries").get_json()
    assert isinstance(entries, list)

    evaluation = client.get("/api/evaluation").get_json()
    assert isinstance(evaluation, list)
