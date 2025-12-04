from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import app as base_app


def test_http_exception_returns_json():
    client = TestClient(base_app)
    resp = client.get("/users/not-authorized")

    assert resp.status_code == 401
    body = resp.json()
    assert isinstance(body, dict)
    assert body.get("error") or body.get("message") or body.get("detail")
    assert "text/html" not in resp.headers.get("content-type", "").lower()


def test_unhandled_exception_returns_internal_error_json():
    app = FastAPI()
    # Mirror middleware and exception handlers from base_app.
    for m in base_app.user_middleware:
        app.add_middleware(m.cls, **m.kwargs)
    app.exception_handlers.update(base_app.exception_handlers)
    app.include_router(base_app.router)

    @app.get("/boom")
    def boom():
        raise RuntimeError("boom")

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/boom")

    assert resp.status_code == 500
    assert resp.json()["error"] == "internal_error"
    assert "text/html" not in resp.headers.get("content-type", "").lower()
