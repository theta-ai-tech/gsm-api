"""Tests for CORS origin sanitization (#377 — kill wildcard origins)."""

from app.settings import sanitize_cors_origins


def test_strips_wildcard():
    cleaned, stripped = sanitize_cors_origins(["https://app.example.com", "*"])
    assert cleaned == ["https://app.example.com"]
    assert stripped is True


def test_keeps_explicit_origins():
    origins = ["https://a.example.com", "https://b.example.com"]
    cleaned, stripped = sanitize_cors_origins(origins)
    assert cleaned == origins
    assert stripped is False


def test_empty():
    assert sanitize_cors_origins([]) == ([], False)


def test_only_wildcard_yields_empty():
    assert sanitize_cors_origins(["*"]) == ([], True)
