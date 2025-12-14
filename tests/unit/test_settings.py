from app import deps
from app.settings import get_settings


def test_get_settings_reads_emulator_env(monkeypatch):
    """Local dev (make api-dev) config: dev project id + Firestore emulator host."""
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "gsm-dev-test")
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8082")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)

    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.project_id == "gsm-dev-test"
        assert settings.firestore_emulator_host == "127.0.0.1:8082"
    finally:
        get_settings.cache_clear()


def test_get_settings_real_firestore(monkeypatch):
    """Optional api-dev-real config: talks to real Firestore (no emulator host set)."""
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "gsm-real-test")
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)

    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.project_id == "gsm-real-test"
        assert settings.firestore_emulator_host is None
    finally:
        get_settings.cache_clear()


def test_firebase_app_uses_adc_without_key_file(monkeypatch):
    """Simulates Cloud Run ADC: no GOOGLE_APPLICATION_CREDENTIALS; should init without key file."""
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "cloud-run-test")
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)
    monkeypatch.delenv("FIREBASE_AUTH_EMULATOR_HOST", raising=False)

    init_calls: dict = {}

    def _raise_no_app():
        raise ValueError("no app")

    def _fake_initialize_app(*args, **kwargs):
        init_calls["args"] = args
        init_calls["kwargs"] = kwargs
        assert "credential" not in kwargs and "credentials" not in kwargs
        return object()

    monkeypatch.setattr(deps.firebase_admin, "get_app", _raise_no_app)
    monkeypatch.setattr(deps.firebase_admin, "initialize_app", _fake_initialize_app)

    deps.get_settings.cache_clear()
    try:
        settings = deps.get_settings()
        app_instance = deps._get_firebase_app(settings)
        assert app_instance is not None
        assert init_calls["kwargs"]["options"]["projectId"] == "cloud-run-test"
    finally:
        deps.get_settings.cache_clear()


def test_ci_emulator_settings(monkeypatch):
    """Matches CI env: Firestore emulator host + project id set for tests."""
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "gsm-dev-f70d0")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "gsm-dev-f70d0")
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8082")
    monkeypatch.delenv("FIREBASE_AUTH_EMULATOR_HOST", raising=False)

    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.project_id == "gsm-dev-f70d0"
        assert settings.firestore_emulator_host == "127.0.0.1:8082"
    finally:
        get_settings.cache_clear()
