# Endpoints (Current State)

This document summarizes the API endpoints implemented right now, how they behave,
and example calls/responses.

Base URL (local dev): `http://localhost:8000`

---

## `GET /health`

### Purpose
Liveness probe. Confirms the API process is up.

### Auth
Public (no token required).

### Behavior
- Does not call Firestore.
- Always returns HTTP `200` if process is running.

### Example call
```bash
curl -s http://localhost:8000/health
```

### Example response
```json
{
  "status": "ok",
  "service": "gsm-api",
  "version": "0.1.0",
  "ok": true
}
```

---

## `GET /ready`

### Purpose
Readiness probe. Confirms the API can reach Firestore.

### Auth
Public (no token required).

### Behavior
- Performs a minimal Firestore read (`ready` collection, limit 1).
- Returns:
  - HTTP `200` when Firestore is reachable
  - HTTP `503` when Firestore is unavailable

### Example call
```bash
curl -s http://localhost:8000/ready
```

### Example success response (`200`)
```json
{
  "status": "ok",
  "firestore": "ok",
  "service": "gsm-api",
  "version": "0.1.0"
}
```

### Example failure response (`503`)
```json
{
  "status": "degraded",
  "firestore": "error",
  "detail": "firestore_unavailable",
  "message": "<error text>"
}
```

---

## `GET /users/{uid}`

### Purpose
Get private profile for the authenticated user.

### Auth
Required (`Authorization: Bearer <Firebase ID token>`).

### Authorization
- Only the same user can access (`current_user.uid == {uid}`).
- Returns HTTP `403` if token is valid but path uid is different.

### Behavior
- Verifies Firebase token (`aud`/`iss` checks).
- Reads `users/{uid}` via `UsersRepo.get_private_profile`.
- Returns HTTP `404` if user document does not exist.

### Example call
```bash
curl -s \
  -H "Authorization: Bearer $ID_TOKEN" \
  http://localhost:8000/users/user_123
```

### Example success response (`200`)
```json
{
  "uid": "user_123",
  "name": "Alex",
  "email": "alex@example.com",
  "phone": "+301111111111",
  "profile_url": "https://example.com/avatar.png",
  "rankings": {
    "tennis": {"sport": "tennis", "pts": 820, "global_ranking": 340},
    "padel": null,
    "pickleball": null
  },
  "preferences": {
    "area": 101,
    "comment": "integer key referencing a separate region config; may evolve to ISO code later.",
    "levels": {"tennis": "advanced", "padel": null, "pickleball": null},
    "sports": ["tennis"]
  },
  "leagues_active": [],
  "leagues_completed": [],
  "upcoming_matches": [],
  "completed_matches": [],
  "journal_recent": [],
  "cursors": null
}
```

### Common error responses
- `401` missing/invalid token
- `403` not owner
- `404` user not found

---

## `POST /leagues/{league_id}/members` (placeholder)

### Purpose
Planned member add endpoint (currently stubbed).

### Auth
Required.

### Authorization
Requires league admin permission via `require_league_member("admin")`:
- passes if caller has global admin role claim OR
- is league owner OR
- has membership doc role `admin`.

### Current behavior
- Returns HTTP `201` with a placeholder payload.
- Does not yet create Firestore membership docs.

### Example call
```bash
curl -s -X POST \
  -H "Authorization: Bearer $ID_TOKEN" \
  http://localhost:8000/leagues/league_1/members
```

### Example response (`201`)
```json
{
  "league_id": "league_1",
  "requested_by": "user_admin"
}
```

---

## `DELETE /leagues/{league_id}/members/{uid}` (placeholder)

### Purpose
Planned member remove endpoint (currently stubbed).

### Auth
Required.

### Authorization
Requires league admin permission via `require_league_member("admin")`.

### Current behavior
- Returns HTTP `204` in route declaration, with placeholder body currently returned by handler.
- Does not yet delete membership docs.

### Example call
```bash
curl -i -X DELETE \
  -H "Authorization: Bearer $ID_TOKEN" \
  http://localhost:8000/leagues/league_1/members/user_123
```

### Example response intent
- HTTP `204` (no content) once fully implemented.

---

## Cross-cutting behavior

### Headers
- Every response includes `X-Request-Id`.
- Security headers include:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: no-referrer`
  - `Server: gsm-api`

### Error format
- API returns JSON errors (no HTML pages).
- Validation errors use a structured payload:
  - `error: "validation_error"`
  - `message: "Invalid request"`
  - `details: [...]`

### OpenAPI auth
- Swagger/OpenAPI is configured with bearer auth scheme (`bearerAuth`).
