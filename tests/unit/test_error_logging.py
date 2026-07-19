import json
import logging

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.main import app as base_app
from app.observability import bodies_logging_enabled


def _mirror_app() -> FastAPI:
    """Fresh app carrying base_app's middleware + exception handlers."""
    app = FastAPI()
    for m in base_app.user_middleware:
        app.add_middleware(m.cls, **m.kwargs)
    app.exception_handlers.update(base_app.exception_handlers)
    app.include_router(base_app.router)
    return app


def _http_error_records(caplog):
    records = []
    for r in caplog.records:
        if r.name != "gsm-api":
            continue
        try:
            payload = json.loads(r.getMessage())
        except (ValueError, TypeError):
            continue
        if payload.get("event") == "http_error":
            records.append((r, payload))
    return records


def _http_body_records(caplog):
    records = []
    for r in caplog.records:
        if r.name != "gsm-api":
            continue
        try:
            payload = json.loads(r.getMessage())
        except (ValueError, TypeError):
            continue
        if payload.get("event") == "http_body":
            records.append((r, payload))
    return records


# --- Part 1: always-on non-2xx logging ---------------------------------------


def test_4xx_logs_warning_with_detail_and_request_id(caplog):
    caplog.set_level(logging.WARNING, logger="gsm-api")
    client = TestClient(base_app)
    resp = client.get("/users/not-authorized", headers={"X-Request-Id": "test-corr-1"})
    assert resp.status_code == 401

    records = _http_error_records(caplog)
    assert len(records) == 1
    record, payload = records[0]
    assert record.levelno == logging.WARNING
    assert payload["status"] == 401
    assert payload["path"] == "/users/not-authorized"
    assert payload["method"] == "GET"
    assert payload["request_id"] == "test-corr-1"
    assert payload["detail"]


def test_404_detail_value_is_logged(caplog):
    caplog.set_level(logging.WARNING, logger="gsm-api")
    app = _mirror_app()

    @app.get("/missing")
    def missing():
        raise HTTPException(status_code=404, detail="User not found")

    client = TestClient(app)
    resp = client.get("/missing")
    assert resp.status_code == 404

    records = _http_error_records(caplog)
    assert len(records) == 1
    _, payload = records[0]
    assert payload["detail"] == "User not found"
    assert payload["status"] == 404


def test_422_logs_loc_msg_type_but_never_input(caplog):
    caplog.set_level(logging.WARNING, logger="gsm-api")
    app = _mirror_app()

    class Body(BaseModel):
        count: int

    @app.post("/validate")
    def validate(body: Body):
        return {"ok": True}

    client = TestClient(app)
    resp = client.post("/validate", json={"count": "SENTINEL_PII"})
    assert resp.status_code == 422

    records = _http_error_records(caplog)
    assert len(records) == 1
    record, payload = records[0]
    assert record.levelno == logging.WARNING
    assert payload["status"] == 422
    assert "SENTINEL_PII" not in record.getMessage()
    entry = payload["detail"][0]
    assert set(entry.keys()) == {"loc", "msg", "type"}


def test_500_logs_error_with_exception_class_and_traceback(caplog):
    caplog.set_level(logging.ERROR, logger="gsm-api")
    app = _mirror_app()

    @app.get("/boom")
    def boom():
        raise RuntimeError("boom-secret")

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/boom")
    assert resp.status_code == 500
    assert resp.json()["error"] == "internal_error"

    records = _http_error_records(caplog)
    assert len(records) == 1
    record, payload = records[0]
    assert record.levelno == logging.ERROR
    # The JSON `detail` (and the message string) carries only the exception class
    # name, never str(exc) — so the structured payload stays PII-free.
    assert payload["detail"] == "unhandled_exception: RuntimeError"
    assert "boom-secret" not in record.getMessage()

    # But exc_info IS attached (needed to debug unhandled 5xx bugs), and a rendered
    # traceback's last line is "<ClassName>: <str(exc)>" — so the exception's own
    # message DOES reach the traceback. This is the intentional, accepted 5xx-only
    # tradeoff; assert the real behavior rather than a false absence.
    assert record.exc_info is not None
    rendered_traceback = logging.Formatter().formatException(record.exc_info)
    assert "boom-secret" in rendered_traceback


def test_2xx_logs_nothing(caplog):
    caplog.set_level(logging.WARNING, logger="gsm-api")
    client = TestClient(base_app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert _http_error_records(caplog) == []


# --- Part 2: gated body logging ----------------------------------------------


def _echo_app() -> FastAPI:
    app = _mirror_app()

    @app.post("/echo")
    async def echo(payload: dict):
        return payload

    @app.post("/echo_text")
    async def echo_text():
        return {"ok": True}

    return app


def test_flag_off_no_body_logs(caplog, monkeypatch):
    monkeypatch.delenv("GSM_LOG_BODIES", raising=False)
    caplog.set_level(logging.INFO, logger="gsm-api")
    app = _echo_app()
    client = TestClient(app)
    resp = client.post("/echo", json={"name": "x"})
    assert resp.status_code == 200
    assert _http_body_records(caplog) == []


def test_flag_on_bodies_logged_with_redaction(caplog, monkeypatch):
    monkeypatch.setenv("GSM_LOG_BODIES", "1")
    caplog.set_level(logging.INFO, logger="gsm-api")
    app = _echo_app()
    client = TestClient(app)
    resp = client.post(
        "/echo",
        json={"name": "x", "password": "hunter2", "email": "a@b.c"},
        headers={"X-Request-Id": "body-corr-1"},
    )
    assert resp.status_code == 200
    # Client-facing response is NOT redacted.
    assert resp.json() == {"name": "x", "password": "hunter2", "email": "a@b.c"}

    records = _http_body_records(caplog)
    assert len(records) == 1
    record, payload = records[0]
    assert payload["request_body"]["password"] == "[REDACTED]"
    assert payload["request_body"]["email"] == "[REDACTED]"
    assert payload["request_body"]["name"] == "x"
    assert payload["request_id"] == "body-corr-1"
    assert payload["response_body"] is not None
    assert "hunter2" not in record.getMessage()


def test_flag_on_redaction_under_real_app_middleware(caplog, monkeypatch):
    """Prove redaction works under the PRODUCTION middleware stack, not just the mirror app.

    The mirror app rebuilds middleware via add_middleware (which inserts at position 0,
    inverting order), so it does not guarantee the real topology. Here we hit the real
    `app` from app.main directly. POST /me is unauthenticated → 401, but the body-logging
    middleware runs regardless of the downstream auth outcome, so the request body is still
    logged and must be redacted.
    """
    monkeypatch.setenv("GSM_LOG_BODIES", "1")
    caplog.set_level(logging.INFO, logger="gsm-api")
    client = TestClient(base_app)
    resp = client.post("/me", json={"name": "x", "password": "hunter2-secret"})
    assert resp.status_code == 401

    records = _http_body_records(caplog)
    assert len(records) == 1
    record, payload = records[0]
    assert payload["path"] == "/me"
    assert payload["request_body"]["password"] == "[REDACTED]"
    assert payload["request_body"]["name"] == "x"
    assert "hunter2-secret" not in record.getMessage()


def test_nested_redaction(caplog, monkeypatch):
    monkeypatch.setenv("GSM_LOG_BODIES", "1")
    caplog.set_level(logging.INFO, logger="gsm-api")
    app = _echo_app()
    client = TestClient(app)
    resp = client.post(
        "/echo", json={"user": {"token": "t", "profile": {"email": "e"}}}
    )
    assert resp.status_code == 200

    records = _http_body_records(caplog)
    assert len(records) == 1
    _, payload = records[0]
    body = payload["request_body"]
    assert body["user"]["token"] == "[REDACTED]"
    assert body["user"]["profile"]["email"] == "[REDACTED]"


def test_non_json_and_oversized_body(caplog, monkeypatch):
    monkeypatch.setenv("GSM_LOG_BODIES", "1")
    caplog.set_level(logging.INFO, logger="gsm-api")
    app = _echo_app()
    client = TestClient(app)

    resp = client.post(
        "/echo_text", content="plain text body", headers={"content-type": "text/plain"}
    )
    assert resp.status_code == 200
    records = _http_body_records(caplog)
    assert len(records) == 1
    _, payload = records[0]
    assert payload["request_body"] == "plain text body"

    caplog.clear()
    big = "x" * 20_000
    resp = client.post(
        "/echo_text", content=big, headers={"content-type": "text/plain"}
    )
    assert resp.status_code == 200
    records = _http_body_records(caplog)
    assert len(records) == 1
    _, payload = records[0]
    assert payload["request_body"] == f"[truncated: {len(big.encode())} bytes]"


@pytest.mark.parametrize("value", ["0", "false", "off", "no", "", "maybe"])
def test_truthiness_disabled(value, monkeypatch):
    monkeypatch.setenv("GSM_LOG_BODIES", value)
    assert bodies_logging_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "on", "yes", "TRUE", " Yes "])
def test_truthiness_enabled(value, monkeypatch):
    monkeypatch.setenv("GSM_LOG_BODIES", value)
    assert bodies_logging_enabled() is True


def test_truthiness_unset(monkeypatch):
    monkeypatch.delenv("GSM_LOG_BODIES", raising=False)
    assert bodies_logging_enabled() is False


def test_flag_on_preserves_headers_and_status(monkeypatch):
    monkeypatch.setenv("GSM_LOG_BODIES", "1")
    client = TestClient(base_app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-Id")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
