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

## `GET /leagues`

### Purpose
Browse leagues with optional filters and cursor-based pagination. Returns `LeagueBrowseCard` summaries.

### Auth
Required (Firebase Bearer token).

### Query parameters
| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `region` | string | No | — | Filter by named region (e.g. `"athens"`) |
| `sport` | `tennis \| padel \| pickleball` | No | — | Filter by sport |
| `status` | `open \| active \| upcoming \| completed` | No | `open` | Filter by league status |
| `limit` | int (1–50) | No | 20 | Max leagues to return per page |
| `cursor` | string | No | — | Opaque pagination token from previous response |

### Example call
```bash
curl -s \
  -H "Authorization: Bearer $ID_TOKEN" \
  "http://localhost:8000/leagues?region=athens&sport=padel&status=open&limit=10"
```

### Example success response (`200`)
```json
{
  "leagues": [
    {
      "league_id": "padel-local-2025",
      "name": "Padel Local 2025",
      "sport": "padel",
      "status": "open",
      "region": "athens",
      "tier": "intermediate",
      "max_players": 16,
      "current_players": 4,
      "start_date": "2025-06-01T00:00:00+00:00"
    }
  ],
  "next_cursor": null
}
```

### Behavior
- Pagination uses cursor-based approach with opaque tokens (base64-encoded). Treat `next_cursor` as opaque — do not parse it.
- `next_cursor` is `null` when there are no more pages.
- Returns `200` with `leagues: []` when no results match — never `404`.

### Common error responses
- `400` invalid cursor token
- `401` missing/invalid token
- `422` validation error (invalid `sport` or `status` value, `limit` out of range)

---

## `GET /leagues/{league_id}/standings`

### Purpose
Returns the current standings table for a league, sorted by wins (desc), losses (asc), net wins (desc), then name (asc). Uses dense ranking (tied players share a rank; next rank is +1, not +gap).

### Auth
Required (Firebase Bearer token). Caller must be a member of the league.

### Path parameters
- `league_id` — string identifier of the league

### Example call
```bash
curl -s \
  -H "Authorization: Bearer $ID_TOKEN" \
  http://localhost:8000/leagues/padel-local-2025/standings
```

### Example success response (`200`)
```json
{
  "league_id": "padel-local-2025",
  "standings": [
    {
      "rank": 1,
      "uid": "user_ignatios",
      "display_name": "user_ignatios",
      "wins": 5,
      "losses": 1,
      "tier_ring": null
    },
    {
      "rank": 2,
      "uid": "user_sam",
      "display_name": "user_sam",
      "wins": 3,
      "losses": 2,
      "tier_ring": null
    }
  ]
}
```

### Notes
- `display_name` currently falls back to `uid` — `displayName` is not yet stored in member docs (MVP limitation).
- `tier_ring` is always `null` for MVP.

### Common error responses
- `401` missing/invalid token
- `403` caller is not a league member
- `404` league not found

---

## `POST /leagues/{league_id}/join`

### Purpose
Self-serve join flow. Adds the authenticated user as a `player` member of the league. No request body required.

### Auth
Required (Firebase Bearer token).

### Path parameters
- `league_id` — string identifier of the league

### Request body
None.

### Example call
```bash
curl -s -X POST \
  -H "Authorization: Bearer $ID_TOKEN" \
  http://localhost:8000/leagues/padel-local-2025/join
```

### Example success response (`201`)
```json
{
  "uid": "user_ignatios",
  "role": "player",
  "status": "active",
  "joined_at": "2026-05-27T10:00:00+00:00",
  "stats": null
}
```

### Behavior
- Checks are performed transactionally:
  1. League must exist.
  2. League status must be `open` or `upcoming`.
  3. Caller must not already be a member.
  4. League must not be at full capacity (`currentPlayers >= maxPlayers`, if both are set).
- On success: creates `leagues/{leagueId}/members/{uid}` doc and increments `currentPlayers` on the league doc in one Firestore transaction.

### Common error responses
- `401` missing/invalid token
- `404` league not found
- `409` already a member, league not open/upcoming, or league at full capacity

---

## `GET /leagues/{league_id}/matches`

### Purpose
List upcoming or completed matches for a league. Requires league membership.

### Auth
Required (Firebase Bearer token). Caller must be a member of the league.

### Path parameters
- `league_id` — string identifier of the league

### Query parameters
| Param | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `type` | `upcoming \| completed` | No | `upcoming` | Which match bucket to return |
| `limit` | int (1–50) | No | 10 | Max matches per page |
| `cursor` | string | No | — | Opaque pagination token from previous response |

### Example call
```bash
curl -s \
  -H "Authorization: Bearer $ID_TOKEN" \
  "http://localhost:8000/leagues/padel-local-2025/matches?type=upcoming&limit=5"
```

### Example success response (`200`)
```json
{
  "matches": [
    {
      "match_id": "match_123",
      "sport": "padel",
      "status": "scheduled",
      "scheduled_at": "2026-06-10T18:00:00+00:00",
      "finished_at": null,
      "league_id": "padel-local-2025",
      "court_id": null,
      "participants": [
        {"uid": "user_ignatios", "team": 1, "role": "player", "result": null},
        {"uid": "user_sam", "team": 2, "role": "player", "result": null}
      ],
      "participant_uids": ["user_ignatios", "user_sam"],
      "result_by_user": null,
      "score": null
    }
  ],
  "next_cursor": null
}
```

### Behavior
- `type=upcoming`: ordered by `scheduledAt` ASC.
- `type=completed`: ordered by `finishedAt` DESC.
- Cursor tokens are opaque (base64-encoded). Treat `next_cursor` as opaque — do not parse it.
- Returns `200` with `matches: []` when no matches — never `404`.

### Common error responses
- `400` invalid cursor token
- `401` missing/invalid token
- `403` caller is not a league member
- `404` league not found

---

## `GET /leagues/{league_id}`

### Purpose
Returns the full `League` detail object for a given league ID.

### Auth
Required (Firebase Bearer token).

### Path parameters
- `league_id` — string identifier of the league

### Example call
```bash
curl -s \
  -H "Authorization: Bearer $ID_TOKEN" \
  http://localhost:8000/leagues/padel-local-2025
```

### Example success response (`200`)
```json
{
  "league_id": "padel-local-2025",
  "name": "Padel Local 2025",
  "sport": "padel",
  "season": "2025",
  "status": "open",
  "owner_uid": "user_ignatios",
  "region": "athens",
  "max_players": 16,
  "current_players": 4,
  "start_date": "2025-06-01T00:00:00+00:00",
  "end_date": null,
  "tier": "intermediate",
  "meta": null
}
```

### Common error responses
- `401` missing/invalid token
- `404` league not found

---

## `POST /leagues/{league_id}/members`

### Purpose
Add a member to a league (admin operation). Not yet implemented.

### Auth
Required.

### Authorization
Requires league admin permission via `require_league_member("admin")`:
- passes if caller has global admin role claim OR
- is league owner OR
- has membership doc role `admin`.

### Current behavior
- Returns HTTP `501 Not Implemented`.
- Member creation is planned for a future sprint.

### Common error responses
- `401` missing/invalid token
- `403` not league admin
- `501` not implemented

---

## `DELETE /leagues/{league_id}/members/{uid}`

### Purpose
Remove a member from a league (admin operation). Not yet implemented.

### Auth
Required.

### Authorization
Requires league admin permission via `require_league_member("admin")`.

### Current behavior
- Returns HTTP `501 Not Implemented`.
- Member removal is planned for a future sprint.

### Common error responses
- `401` missing/invalid token
- `403` not league admin
- `501` not implemented

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
  "match_type": "singles",
  "broadcast_type": "find_opponent",
  "partner_uid": null,
  "availability": "today",
  "court_status": "have_court",
  "court_location": "Central Court, Athens",
  "venue_ref": {
    "venueId": "ten_twenty_club",
    "placeId": null,
    "name": "Ten Twenty Club",
    "coordinates": {"lat": 37.8362, "lng": 23.7627}
  },
  "expires_at": "2026-02-03T16:00:00Z",
  "location": {
    "area": 101,
    "geo": {"lat": 37.98, "lng": 23.73},
    "radiusKm": 10
  }
}
```

`match_type` defaults to `singles` and `broadcast_type` defaults to `find_opponent`,
so existing singles clients can continue to omit them. Doubles rules:
- `broadcast_type=find_fourth` requires `match_type=doubles`.
- `match_type=doubles` + `broadcast_type=find_opponent` requires `partner_uid`.
- `match_type=doubles` + `broadcast_type=find_fourth` makes `partner_uid` optional.

### Behavior
- Validates `expiresAt` is in the future.
- Persists `venueRef` for `have_court` broadcasts when supplied.
- Allows `have_court` broadcasts without `venueRef` for backwards compatibility.
- Ignores `venueRef` for `need_court` broadcasts.
- Persists `matchType`, `broadcastType`, `partnerUid` on the broadcast doc.
- Forces `partnerUid=null` when `matchType=singles` regardless of request.
- Creates `broadcasts/{id}` doc (status=active, denormalized owner fields).
- Updates `users/{uid}.playTab`: state → `BROADCAST_ACTIVE`, activeBroadcastId → new ID.
- Both writes in a single Firestore transaction.

### Example response (`201`)
```json
{
  "broadcast_id": "broadcast_abc",
  "sport": "tennis",
  "match_type": "singles",
  "broadcast_type": "find_opponent",
  "partner_uid": null,
  "availability": "today",
  "court_status": "have_court",
  "court_location": "Central Court, Athens",
  "status": "active",
  "expires_at": "2026-02-03T16:00:00Z",
  "created_at": "2026-02-03T08:00:00Z"
}
```

### Common error responses
- `401` missing/invalid token
- `409` user is not in DISCOVERY state (active broadcast, offer, or match exists)
- `422` validation error (expiresAt in past, missing required fields, invalid doubles combination)

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


## `GET /venues`

### Purpose
List curated venues that support a given sport, optionally filtered by area. Returns the manually
seeded venue list (15–20 Athens venues for MVP); non-curated venues are resolved via
`GET /venues/search`.

### Auth
Required (Firebase Bearer ID token).

### Query parameters
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `sport` | `tennis \| padel \| pickleball` | Yes | Sport to filter by |
| `area` | string | No | Exact area string match (e.g. `"Glyfada"`) |
| `limit` | int (1–100, default 20) | No | Max venues to return |
| `cursor` | string | No | Opaque pagination token from previous response |

### Example response (`200`)
```json
{
  "venues": [
    {
      "venueId": "venue_flisvos",
      "name": "Flisvos Padel Academy",
      "coordinates": {"lat": 37.93, "lng": 23.68},
      "area": "Palaio Faliro",
      "sports": ["padel", "tennis"],
      "courtCount": 6,
      "indoor": false,
      "placeId": "ChIJFlisvos"
    }
  ],
  "nextCursor": null
}
```

### Behavior
- Queries the `venues/{venueId}` Firestore collection using `array_contains` on `sports`.
- If `area` is provided, adds an exact-match filter on the `area` field.
- Results are ordered by `name` alphabetically.
- Pagination: pass `nextCursor` from a previous response as `cursor` to fetch the next page.
- Returns `200` with `venues: []` when no venues match (never 404).

### Common error responses
- `400` invalid cursor token
- `401` missing/invalid token
- `422` validation error (invalid `sport` value, `limit` out of range)

---


## `POST /venues/suggest`

### Purpose
Submit a user-suggested venue to a moderation queue. Suggestions are stored
in the `venueSuggestions/{autoId}` collection with `status="pending"` and are
NOT promoted to the live `venues` collection until reviewed.

### Auth
Required (Firebase Bearer ID token).

### Request body
```json
{
  "name": "My Local Club",
  "coordinates": {"lat": 37.95, "lng": 23.72},
  "sport": "padel",
  "notes": "2 outdoor courts, open until 11pm"
}
```

Validation:
- `name`: required, trimmed, non-blank, 1–200 chars after trimming
- `coordinates.lat`: required, -90 to 90
- `coordinates.lng`: required, -180 to 180
- `sport`: required, one of `tennis | padel | pickleball`
- `notes`: optional, max 500 chars

### Example response (`201`)
```json
{"suggestionId": "abc123"}
```

### Behavior
- Writes a new document to `venueSuggestions/{autoId}` with:
  - `name`, `coordinates`, `sport`, `notes` from the request
  - `suggestedBy` = authenticated UID
  - `createdAt` = server-side UTC timestamp
  - `status` = `"pending"`
- Returns the auto-generated Firestore document ID.

### Common error responses
- `401` missing/invalid token
- `422` validation error (missing/invalid fields)

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
