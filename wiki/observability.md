# Observability & Readiness

## Auth Regression Tests
- We keep regression tests for `GET /users/{uid}` to lock in current auth behavior:
  - 401: no token or invalid token.
  - 403: valid token but path uid mismatch.
  - 200: valid token with matching uid.
- Purpose: catch auth regressions early whenever token parsing/verification changes.

## Liveness vs Readiness
- `GET /health` (liveness): public; no external deps; confirms process is up.
- `GET /ready` (readiness): public; performs a minimal Firestore touch (emulator in dev/CI, real Firestore in prod); returns 200 when reachable, 503 otherwise.

## Request IDs
- Every request gets an `X-Request-Id` (uses incoming header or generates one) and the same value is returned in the response.
- Use this id to correlate logs for a single request across the stack.

## Slow Request Logging
- Timing middleware measures each request.
- If duration exceeds the threshold (currently 500ms), it logs: path, method, status code, duration, threshold, and `request_id`.
- Helps spot performance regressions without changing API behavior.

## CI Coverage
- GitHub Actions CI runs the unit test suite, which includes auth regression tests, health/readiness tests, and observability-focused tests (request id + timing middleware behavior).***

## Funnel Telemetry Events
Structured analytics events for the matchmaking funnel (broadcast → offer → match → score) are
defined in [wiki/telemetry.md](telemetry.md). Implementation uses the `log_analytics_event`
helper in `api/app/logging.py`, which emits JSON-serialized payloads to Cloud Logging.
