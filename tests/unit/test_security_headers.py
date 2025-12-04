from app.main import app
from fastapi.testclient import TestClient


def test_security_headers_present_on_success():
    client = TestClient(app)
    resp = client.get("/health")
    headers = {k.lower(): v for k, v in resp.headers.items()}

    assert headers["x-content-type-options"].lower() == "nosniff"
    assert headers["x-frame-options"].upper() == "DENY"
    assert headers["referrer-policy"].lower() == "no-referrer"
    assert headers["server"] == "gsm-api"


def test_request_id_preserved_when_provided():
    client = TestClient(app)
    resp = client.get("/health", headers={"X-Request-Id": "abc-123"})

    assert resp.headers["x-request-id"] == "abc-123"


def test_request_id_generated_when_missing():
    client = TestClient(app)
    resp = client.get("/health")

    assert "x-request-id" in resp.headers
    assert resp.headers["x-request-id"]


def test_security_headers_present_on_error():
    client = TestClient(app)
    resp = client.get("/users/not-authorized")
    headers = {k.lower(): v for k, v in resp.headers.items()}

    assert headers["x-content-type-options"].lower() == "nosniff"
    assert headers["x-frame-options"].upper() == "DENY"
    assert headers["referrer-policy"].lower() == "no-referrer"
    assert headers["server"] == "gsm-api"
