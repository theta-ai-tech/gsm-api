# Calling the GSM API

Everything a client (iOS or other) needs to talk to GSM. Read this first, then
[`ios-integration.md`](ios-integration.md) for end-to-end call patterns, the full
[`endpoints.md`](endpoints.md) reference, and the frozen [`contracts.md`](contracts.md) payloads.

## Base URLs

| Environment | Base URL |
|---|---|
| Local dev (emulator) | `http://localhost:8000` |
| Dev / prod (Cloud Run) | environment-specific Cloud Run URL (europe-west8) — injected per build, do not hardcode |

Interactive docs are served at `/docs` (Swagger UI) and the OpenAPI schema at `/openapi.json`.

## Authentication

Every non-public endpoint requires a Firebase **ID token** as a Bearer credential:

```
Authorization: Bearer <firebase_id_token>
```

1. Sign the user in with the Firebase Auth SDK (or the Auth emulator in dev).
2. Obtain the current ID token from the SDK (refresh it as the SDK dictates — tokens are short-lived).
3. Send it on every request in the `Authorization` header.

The server verifies the token's signature, issuer, and audience on each call. The client never
talks to Firestore directly — all data access is via this API. Full model:
[`../architecture/security.md`](../architecture/security.md).

Public endpoints (no token): `GET /health`, `GET /ready`.

## Conventions

- **JSON over HTTPS.** Request and response bodies are JSON; send `Content-Type: application/json`.
- **Field casing.** Request/response payloads use the casing documented per endpoint in
  [`endpoints.md`](endpoints.md) / [`contracts.md`](contracts.md). The frozen mobile contracts use
  `snake_case` (e.g. `court_status`, `expires_at`); follow the exact shapes there — they are frozen
  and only change via an explicit issue.
- **Timestamps** are ISO 8601 UTC strings (e.g. `2026-02-03T10:00:00Z`). Use the `serverTime` field
  returned by `GET /me/state` for any countdown/expiry math rather than the device clock.
- **Request correlation.** Responses echo an `X-Request-Id` header (generated if you don't send
  one). Log it client-side to correlate with backend logs when filing issues.

## Error model

Errors use standard HTTP status codes with a JSON body. The default shape is FastAPI's:

```json
{ "detail": "human-or-machine readable reason" }
```

Common codes across the API:

| Code | Meaning |
|---|---|
| `400` / `422` | Validation error — missing/invalid fields, bad enum, illegal combination (e.g. `expires_at` in the past, invalid doubles combo). |
| `401` | Missing or invalid token. |
| `403` | Authenticated but not allowed (e.g. accessing another user's resource; insufficient league role). |
| `404` | Resource not found (no profile for uid; unknown league/match). |
| `409` | Conflict / idempotency guard (e.g. profile already exists for this uid). |
| `429` | Rate-limited. `POST /me/journal` has a per-user spam guard (`JOURNAL_CREATE_RATE_LIMIT_PER_HOUR`, default 50 per rolling hour). |
| `503` | Dependency unavailable (e.g. `GET /ready` when Firestore is unreachable). |

All responses, including errors, are JSON — there are no HTML error pages, and 500s return a generic
message with no stack trace.

Per-endpoint error tables are in [`endpoints.md`](endpoints.md); the frozen create/offer flows list
their exact codes in [`contracts.md`](contracts.md).

## The one endpoint to understand first

`GET /me/state` is the **Play-tab UI router**: it returns the single mode the client should render
plus a mode-specific payload, and it self-corrects stale time-based state on read. Build the Play
tab around it. See [`play-tab-state-machine.md`](play-tab-state-machine.md).

## Push notifications

Register the device's FCM token via `POST /me/device-tokens` after sign-in (and unregister on
sign-out / token rotation). The backend delivers pushes server-side; the client just receives them.
See [`notifications.md`](notifications.md).
