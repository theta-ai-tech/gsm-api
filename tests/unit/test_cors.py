import importlib
import os

from fastapi.testclient import TestClient

import app.settings as settings_module


def _build_app_with_origins(origins: list[str]):
    os.environ.setdefault("FIREBASE_PROJECT_ID", "test-project")
    os.environ["CORS_ORIGINS"] = ",".join(origins)
    os.environ["CORS_ALLOW_CREDENTIALS"] = "0"
    settings_module.get_settings.cache_clear()

    import app.main as main_module

    importlib.reload(settings_module)
    importlib.reload(main_module)
    return main_module.app


def test_cors_preflight_allowed():
    app = _build_app_with_origins(["http://localhost:3000"])
    client = TestClient(app)

    resp = client.options(
        "/users/abc",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_preflight_disallowed():
    app = _build_app_with_origins(["http://localhost:3000"])
    client = TestClient(app)

    resp = client.options(
        "/users/abc",
        headers={
            "Origin": "https://random.com",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert "access-control-allow-origin" not in resp.headers
