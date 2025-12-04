# CORS Configuration Guide

CORS here is scoped to browser-based frontends so that native/mobile apps and server-to-server calls remain unaffected.

## What we built
- **Env-driven origins:** `CORS_ORIGINS` parsed from env; dev example `http://localhost:3000,http://127.0.0.1:3000`, prod example `https://app.gamesetmatch.io`.
- **Credentials toggle:** `CORS_ALLOW_CREDENTIALS` (default `0`) because we use Bearer tokens, not cookies.
- **Middleware wiring:** `CORSMiddleware` is added in `app/main.py` with `allow_origins=settings.cors_origins`, `allow_credentials=settings.cors_allow_credentials`, and headers limited to `Authorization` + `Content-Type`.
- **Scope:** Only applies when browsers send an `Origin` header; non-browser calls are unchanged.

## Why
- Protect APIs from unauthorized browser origins while allowing first-party SPA/portal to call the backend.
- Keep configuration per environment without code changes.

## How it works
1) Browser sends `Origin` and optional preflight (`OPTIONS` with `Access-Control-Request-Method`).
2) Middleware checks `Origin` against `settings.cors_origins`.
3) If allowed, response includes `Access-Control-Allow-Origin` and passes preflight; if not, that header is omitted and browsers block the call.
4) Calls without `Origin` (mobile, curl, server-to-server) skip CORS.

## Testing
- Unit: `tests/unit/test_cors.py` covers allowed/disallowed preflight.
- Manual (requires running API, e.g., `make api-dev`):
  - Allowed preflight:
    ```bash
    curl -i -X OPTIONS "http://localhost:8000/users/abc" \
      -H "Origin: http://localhost:3000" \
      -H "Access-Control-Request-Method: GET"
    ```
    Expect `HTTP/1.1 200 OK` and `Access-Control-Allow-Origin: http://localhost:3000`.
  - Disallowed origin:
    ```bash
    curl -i -X OPTIONS "http://localhost:8000/users/abc" \
      -H "Origin: https://random.com" \
      -H "Access-Control-Request-Method: GET"
    ```
    Expect **no** `Access-Control-Allow-Origin`.
  - Non-browser sanity (mobile/server-style):
    ```bash
    API_URL=http://127.0.0.1:8000/health tests/bash/mobile_no_origin.sh
    ```

## Env examples
- Dev: `CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000`
- Prod: `CORS_ORIGINS=https://app.gamesetmatch.io`
- Credentials (only if using cookies): `CORS_ALLOW_CREDENTIALS=1`
