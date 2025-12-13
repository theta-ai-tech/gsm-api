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
