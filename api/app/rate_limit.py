"""Per-uid, app-level rate limiting for write endpoints.

Rationale (see docs/operations/api-hardening.md): the API is fronted by Cloud Run
and about to face public traffic via the iOS app. The cheapest adequate first line
of defense against abusive write loops from a single account is an in-process,
per-uid fixed-window limiter applied to the mutating endpoints (broadcasts, offers,
verify-score, journal writes).

Tradeoff — this is **per-instance**: Cloud Run may run several instances, so the
effective global limit is (per-instance limit × instance count). It bounds abuse
from one client rather than enforcing a precise global quota. A global limiter
(Cloud Armor / API Gateway) is the documented operator upgrade for hard quotas.

Disable via env `GSM_RATE_LIMIT_ENABLED=0` (default enabled). Read at request time
(not baked into cached Settings) so tests and ops can toggle it without a restart.
"""

from __future__ import annotations

import os
import threading
import time

from fastapi import Depends, HTTPException, status

from app.deps import get_current_user
from app.security import CurrentUser

_TRUTHY = {"1", "true", "on", "yes"}

# Default budget for a write endpoint: 30 requests per 60s window, per uid per bucket.
DEFAULT_WRITE_LIMIT = 30
DEFAULT_WRITE_WINDOW_SECONDS = 60


def rate_limiting_enabled() -> bool:
    return os.getenv("GSM_RATE_LIMIT_ENABLED", "1").strip().lower() in _TRUTHY


class FixedWindowRateLimiter:
    """Thread-safe in-memory fixed-window counter keyed by an arbitrary string."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # key -> (window_start_monotonic, count)
        self._buckets: dict[str, tuple[float, int]] = {}

    def check(
        self,
        key: str,
        limit: int,
        window_seconds: int,
        *,
        now: float | None = None,
    ) -> tuple[bool, int]:
        """Record a hit for ``key`` and report whether it is allowed.

        Returns ``(allowed, retry_after_seconds)``. When not allowed the count is
        left unchanged and ``retry_after_seconds`` is the whole seconds until the
        current window rolls over.
        """
        current = time.monotonic() if now is None else now
        with self._lock:
            window_start, count = self._buckets.get(key, (current, 0))
            elapsed = current - window_start
            if elapsed >= window_seconds:
                # Window expired — start a fresh one.
                window_start, count, elapsed = current, 0, 0.0
            if count >= limit:
                retry_after = max(1, int(window_seconds - elapsed) + 1)
                self._buckets[key] = (window_start, count)
                return False, retry_after
            self._buckets[key] = (window_start, count + 1)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


_default_limiter = FixedWindowRateLimiter()


def get_rate_limiter() -> FixedWindowRateLimiter:
    return _default_limiter


def rate_limit(
    bucket: str,
    limit: int = DEFAULT_WRITE_LIMIT,
    window_seconds: int = DEFAULT_WRITE_WINDOW_SECONDS,
):
    """Build a FastAPI dependency that enforces a per-uid limit for ``bucket``.

    Attach via the route decorator's ``dependencies=[...]`` so the endpoint
    signature is unchanged, e.g.::

        @router.post("/me/broadcast", dependencies=[Depends(rate_limit("broadcast"))])

    Depends on ``get_current_user`` (resolved once per request by FastAPI), so
    an unauthenticated request is rejected with 401 before the limiter runs.
    """

    def dependency(current_user: CurrentUser = Depends(get_current_user)) -> None:
        if not rate_limiting_enabled():
            return
        allowed, retry_after = get_rate_limiter().check(
            f"{bucket}:{current_user.uid}", limit, window_seconds
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please slow down.",
                headers={"Retry-After": str(retry_after)},
            )

    return dependency
