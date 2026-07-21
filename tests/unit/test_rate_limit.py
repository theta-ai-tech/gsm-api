"""Tests for app.rate_limit — the per-uid write-endpoint limiter."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.deps import get_current_user
from app.main import app
from app.models.enums import (
    AvailabilityEnum,
    BroadcastStatusEnum,
    CourtStatusEnum,
    SportEnum,
)
from app.models.play import CreateBroadcastResponse
from app.rate_limit import (
    FixedWindowRateLimiter,
    get_rate_limiter,
    rate_limit,
    rate_limiting_enabled,
)
from app.routers.play import get_play_service
from app.security import CurrentUser
from unittest.mock import Mock
from app.services.play_service import PlayService


# ---- FixedWindowRateLimiter unit tests ----


def test_allows_up_to_limit_then_blocks():
    limiter = FixedWindowRateLimiter()
    # Pin time so the window never rolls over mid-test.
    for i in range(3):
        allowed, retry = limiter.check("k", limit=3, window_seconds=60, now=100.0)
        assert allowed is True, f"call {i} should be allowed"
        assert retry == 0
    allowed, retry = limiter.check("k", limit=3, window_seconds=60, now=100.0)
    assert allowed is False
    assert retry >= 1


def test_window_rolls_over():
    limiter = FixedWindowRateLimiter()
    for _ in range(3):
        limiter.check("k", limit=3, window_seconds=60, now=100.0)
    # Still blocked inside the window...
    assert limiter.check("k", limit=3, window_seconds=60, now=140.0)[0] is False
    # ...allowed again once the window has fully elapsed.
    assert limiter.check("k", limit=3, window_seconds=60, now=161.0)[0] is True


def test_keys_are_independent():
    limiter = FixedWindowRateLimiter()
    for _ in range(3):
        limiter.check("a", limit=3, window_seconds=60, now=100.0)
    # 'a' is exhausted but 'b' is fresh.
    assert limiter.check("a", limit=3, window_seconds=60, now=100.0)[0] is False
    assert limiter.check("b", limit=3, window_seconds=60, now=100.0)[0] is True


def test_reset_clears_state():
    limiter = FixedWindowRateLimiter()
    for _ in range(3):
        limiter.check("k", limit=3, window_seconds=60, now=100.0)
    assert limiter.check("k", limit=3, window_seconds=60, now=100.0)[0] is False
    limiter.reset()
    assert limiter.check("k", limit=3, window_seconds=60, now=100.0)[0] is True


def test_enabled_flag(monkeypatch):
    monkeypatch.setenv("GSM_RATE_LIMIT_ENABLED", "0")
    assert rate_limiting_enabled() is False
    monkeypatch.setenv("GSM_RATE_LIMIT_ENABLED", "1")
    assert rate_limiting_enabled() is True
    monkeypatch.delenv("GSM_RATE_LIMIT_ENABLED", raising=False)
    assert rate_limiting_enabled() is True  # default enabled


# ---- Dependency behavior on a minimal app ----


def test_dependency_returns_429_with_retry_after(monkeypatch):
    monkeypatch.setenv("GSM_RATE_LIMIT_ENABLED", "1")
    get_rate_limiter().reset()

    mini = FastAPI()

    @mini.post(
        "/thing", dependencies=[Depends(rate_limit("t", limit=2, window_seconds=60))]
    )
    def _thing():
        return {"ok": True}

    mini.dependency_overrides[get_current_user] = lambda: CurrentUser(uid="u1")
    client = TestClient(mini)

    assert client.post("/thing").status_code == 200
    assert client.post("/thing").status_code == 200
    resp = client.post("/thing")
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    assert int(resp.headers["Retry-After"]) >= 1
    get_rate_limiter().reset()


def test_dependency_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("GSM_RATE_LIMIT_ENABLED", "0")
    get_rate_limiter().reset()

    mini = FastAPI()

    @mini.post(
        "/thing", dependencies=[Depends(rate_limit("t", limit=1, window_seconds=60))]
    )
    def _thing():
        return {"ok": True}

    mini.dependency_overrides[get_current_user] = lambda: CurrentUser(uid="u1")
    client = TestClient(mini)

    for _ in range(5):
        assert client.post("/thing").status_code == 200


# ---- End-to-end through the real app (exercises the custom exception handler) ----


def test_real_endpoint_emits_429_and_retry_after(monkeypatch):
    """create_broadcast is limited, and Retry-After survives the custom handler."""
    monkeypatch.setenv("GSM_RATE_LIMIT_ENABLED", "1")
    get_rate_limiter().reset()

    now = datetime.now(timezone.utc)
    mock_service = Mock(spec=PlayService)
    mock_service.create_broadcast.return_value = CreateBroadcastResponse(
        broadcast_id="b1",
        sport=SportEnum.TENNIS,
        availability=AvailabilityEnum.TODAY,
        court_status=CourtStatusEnum.HAVE_COURT,
        status=BroadcastStatusEnum.ACTIVE,
        expires_at=now + timedelta(hours=2),
        created_at=now,
    )

    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_play_service] = lambda: mock_service
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(uid="rl_user")
    try:
        client = TestClient(app)
        payload = {
            "sport": "tennis",
            "availability": "today",
            "court_status": "have_court",
            "expires_at": (now + timedelta(hours=2)).isoformat(),
            "location": {"area": 10001},
        }
        statuses = [
            client.post("/me/broadcast", json=payload).status_code for _ in range(31)
        ]
        assert statuses.count(201) == 30
        last = client.post("/me/broadcast", json=payload)
        assert last.status_code == 429
        assert "Retry-After" in last.headers
        assert last.json()["detail"].startswith("Rate limit exceeded")
    finally:
        app.dependency_overrides = previous
        get_rate_limiter().reset()


@pytest.fixture(autouse=True)
def _reset_limiter():
    get_rate_limiter().reset()
    yield
    get_rate_limiter().reset()
