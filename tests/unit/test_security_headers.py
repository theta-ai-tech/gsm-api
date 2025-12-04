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


def test_security_headers_present_on_error():
    client = TestClient(app)
    resp = client.get("/users/not-authorized")
    headers = {k.lower(): v for k, v in resp.headers.items()}

    assert headers["x-content-type-options"].lower() == "nosniff"
    assert headers["x-frame-options"].upper() == "DENY"
    assert headers["referrer-policy"].lower() == "no-referrer"
    assert headers["server"] == "gsm-api"
