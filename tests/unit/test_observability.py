import time

from fastapi.testclient import TestClient

from app.main import app, SLOW_REQUEST_THRESHOLD_MS


def test_request_id_middleware_sets_and_returns_header(monkeypatch):
    client = TestClient(app)
    resp = client.get("/health", headers={"X-Request-Id": "abc123"})
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-Id") == "abc123"


def test_timing_middleware_keeps_response_intact(monkeypatch):
    client = TestClient(app)

    # Temporarily add a slow route to trigger timing path without altering app behavior permanently.
    @app.get("/_slow_test")
    async def _slow_test():
        time.sleep((SLOW_REQUEST_THRESHOLD_MS + 10) / 1000)
        return {"ok": True}

    resp = client.get("/_slow_test")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
