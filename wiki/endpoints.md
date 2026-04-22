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

## `GET /me/state`

### Purpose
Tab 1 (Play) home state. Returns the user's current play mode and mode-specific payload.

### Auth
Required (`Authorization: Bearer <Firebase ID token>`).

### Behavior
- Reads `users/{uid}` to get persisted `playTab.state`.
- Performs **freshness reconciliation**: checks time-based expirations (broadcast TTL, offer expiry, match scheduledAt) and corrects stale state on read.
- Returns the stable response envelope with mode-specific payload.

### Example call
```bash
curl -s \
  -H "Authorization: Bearer $ID_TOKEN" \
  http://localhost:8000/me/state
```

### Example response (`200`)
```json
{
  "mode": "DISCOVERY",
  "serverTime": "2026-02-03T10:00:00Z",
  "primary": {
    "broadcastId": null,
    "matchId": null,
    "activeOfferIds": []
  },
  "payload": {},
  "annotations": {},
  "uiEvents": []
}
```

### Common error responses
- `401` missing/invalid token

See `spec/tab1-play-payloads.md` for full payload examples per mode.

---

## `POST /me/broadcast`

### Purpose
Start an availability broadcast ("I'm Ready to Play").

### Auth
Required.

### Preconditions
- User's `playTab.state` must be `DISCOVERY` (no active broadcast, offer, or match).

### Request body
```json
{
  "sport": "tennis",
  "availability": "today",
  "courtStatus": "have_court",
  "courtLocation": "Central Court, Athens",
  "venueRef": {
    "venueId": "ten_twenty_club",
    "placeId": null,
    "name": "Ten Twenty Club",
    "coordinates": {"lat": 37.8362, "lng": 23.7627}
  },
  "expiresAt": "2026-02-03T16:00:00Z",
  "location": {
    "area": 101,
    "geo": {"lat": 37.98, "lng": 23.73},
    "radiusKm": 10
  }
}
```

### Behavior
- Validates `expiresAt` is in the future.
- Persists `venueRef` for `have_court` broadcasts when supplied.
- Allows `have_court` broadcasts without `venueRef` for backwards compatibility.
- Ignores `venueRef` for `need_court` broadcasts.
- Creates `broadcasts/{id}` doc (status=active, denormalized owner fields).
- Updates `users/{uid}.playTab`: state → `BROADCAST_ACTIVE`, activeBroadcastId → new ID.
- Both writes in a single Firestore transaction.

### Example response (`201`)
```json
{
  "broadcastId": "broadcast_abc",
  "sport": "tennis",
  "availability": "today",
  "courtStatus": "have_court",
  "courtLocation": "Central Court, Athens",
  "status": "active",
  "expiresAt": "2026-02-03T16:00:00Z",
  "createdAt": "2026-02-03T08:00:00Z"
}
```

### Common error responses
- `401` missing/invalid token
- `409` user is not in DISCOVERY state (active broadcast, offer, or match exists)
- `422` validation error (expiresAt in past, missing required fields)

---

## `DELETE /me/broadcast`

### Purpose
Cancel the user's active broadcast.

### Auth
Required.

### Preconditions
- User's `playTab.state` must be `BROADCAST_ACTIVE`.

### Behavior
- Updates `broadcasts/{id}`: status → `cancelled`.
- Declines all pending incoming offers against this broadcast.
- Updates `users/{uid}.playTab`: state → `DISCOVERY`, clears activeBroadcastId and pendingIncomingOfferIds.
- All writes in a single Firestore transaction.

### Example response
- HTTP `204` (no content).

### Common error responses
- `401` missing/invalid token
- `409` user has no active broadcast

---

## `POST /me/offers`

### Purpose
Send a challenge (offer) to another user.

### Auth
Required.

### Preconditions
- Sender's `playTab.state` must be `DISCOVERY` or `BROADCAST_ACTIVE`.
- Sender must not have an active outgoing offer already.
- Target user must exist.

### Request body
```json
{
  "toUid": "user_789",
  "sport": "tennis",
  "proposedTime": "2026-02-03T18:00:00Z",
  "courtLocation": "Central Court, Athens",
  "message": "Up for a game?"
}
```

### Behavior
- Creates `offers/{id}` doc (status=pending, expiresAt=now+5min, denormalized fields from both users).
- Updates sender's `playTab`: state → `OUTGOING_OFFER_PENDING`, activeOutgoingOfferId → new ID.
- Updates recipient's `playTab.pendingIncomingOfferIds` (append offer ID). If recipient is in DISCOVERY, transitions to `INCOMING_OFFER_PENDING`. If recipient is in BROADCAST_ACTIVE, state stays (offers queue).
- All writes in a single Firestore transaction.

### Example response (`201`)
```json
{
  "offerId": "offer_123",
  "toUid": "user_789",
  "toName": "Jamie",
  "sport": "tennis",
  "proposedTime": "2026-02-03T18:00:00Z",
  "status": "pending",
  "expiresAt": "2026-02-03T10:10:00Z",
  "createdAt": "2026-02-03T10:05:00Z"
}
```

### Common error responses
- `401` missing/invalid token
- `404` target user not found
- `409` sender not in valid state, or already has an active outgoing offer
- `422` validation error

---

## `POST /me/offers/{offer_id}/accept`

### Purpose
Accept an incoming offer. Creates a scheduled match.

### Auth
Required (must be the offer recipient).

### Preconditions
- Offer status must be `pending` and not expired.
- Caller must be `offer.toUid`.

### Behavior
- Updates `offers/{id}`: status → `accepted`, matchId → new match ID.
- Creates `matches/{id}` doc (status=scheduled, participants from offer).
- Cancels the recipient's broadcast if active (status → `matched`).
- Declines all other pending offers for both users.
- Updates both users' `playTab`: state → `MATCH_SCHEDULED`, activeMatchId → new match ID, clears broadcast/offer fields.
- All writes in a single Firestore transaction.

### Example response (`200`)
```json
{
  "offerId": "offer_456",
  "matchId": "match_789",
  "status": "accepted",
  "scheduledAt": "2026-02-03T18:00:00Z"
}
```

### Common error responses
- `401` missing/invalid token
- `403` caller is not the offer recipient
- `404` offer not found
- `409` offer already resolved (accepted/declined/expired) or match conflict
- `410` offer expired

---

## `POST /me/offers/{offer_id}/decline`

### Purpose
Decline an incoming offer.

### Auth
Required (must be the offer recipient).

### Preconditions
- Offer status must be `pending`.
- Caller must be `offer.toUid`.

### Behavior
- Updates `offers/{id}`: status → `declined`.
- Removes offer from recipient's `playTab.pendingIncomingOfferIds`.
- Recalculates recipient's state (back to DISCOVERY or stays BROADCAST_ACTIVE if broadcasting).
- Updates sender's `playTab` if this was their active outgoing offer (back to DISCOVERY or BROADCAST_ACTIVE).
- All writes in a single Firestore transaction.

### Example response (`200`)
```json
{
  "offerId": "offer_456",
  "status": "declined"
}
```

### Common error responses
- `401` missing/invalid token
- `403` caller is not the offer recipient
- `404` offer not found
- `409` offer already resolved

---

## `POST /me/offers/{offer_id}/cancel`

### Purpose
Sender withdraws their pending offer.

### Auth
Required (must be the offer sender).

### Preconditions
- Offer status must be `pending`.
- Caller must be `offer.fromUid`.

### Behavior
- Updates `offers/{id}`: status → `cancelled`.
- Removes offer from recipient's `playTab.pendingIncomingOfferIds`.
- Recalculates both users' states (sender back to DISCOVERY or BROADCAST_ACTIVE; recipient recalculated).
- All writes in a single Firestore transaction.

### Example response (`200`)
```json
{
  "offerId": "offer_123",
  "status": "cancelled"
}
```

### Common error responses
- `401` missing/invalid token
- `403` caller is not the offer sender
- `404` offer not found
- `409` offer already resolved

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
