"""Tests for app.telemetry — Cloud Logging / Error Reporting gating."""

from app.telemetry import cloud_logging_enabled, setup_cloud_logging


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("GSM_ENABLE_CLOUD_LOGGING", raising=False)
    monkeypatch.delenv("K_SERVICE", raising=False)
    assert cloud_logging_enabled() is False
    # Never attempts to reach GCP when disabled.
    assert setup_cloud_logging() is False


def test_explicit_enable(monkeypatch):
    monkeypatch.setenv("GSM_ENABLE_CLOUD_LOGGING", "1")
    monkeypatch.delenv("K_SERVICE", raising=False)
    assert cloud_logging_enabled() is True


def test_explicit_disable_overrides_cloud_run(monkeypatch):
    # Even on Cloud Run, an explicit 0 wins.
    monkeypatch.setenv("GSM_ENABLE_CLOUD_LOGGING", "0")
    monkeypatch.setenv("K_SERVICE", "gsm-api")
    assert cloud_logging_enabled() is False


def test_auto_enable_on_cloud_run(monkeypatch):
    monkeypatch.delenv("GSM_ENABLE_CLOUD_LOGGING", raising=False)
    monkeypatch.setenv("K_SERVICE", "gsm-api")
    assert cloud_logging_enabled() is True
