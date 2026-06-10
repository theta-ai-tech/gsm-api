# API Launch Contracts — MVP

**Status: FROZEN** (as of Sprint 8, 2026-05-27)

These shapes are the mobile launch contract. They will not change unless a later issue explicitly
revises them. Any proposed change requires a new issue referencing this document.

---

## Common Types

### VenueRef

Used wherever a venue is attached to a broadcast, offer, or match.

```json
{
  "venueId": "venue_flisvos",
  "placeId": "ChIJFlisvos",
  "name": "Flisvos Padel Academy",
  "coordinates": {"lat": 37.93, "lng": 23.68}
}
```

- `venueId` — Firestore document ID from the `venues` collection; `null` for Google-only results.
- `placeId` — Google Places ID; `null` for fully curated venues without a Places match.
- `name` — display name.
- `coordinates` — `{lat, lng}` floats.

### MatchScore

Used in `verify-score` requests and in post-match state payloads.

```json
{
  "sets": [
    {"p1_games": 6, "p2_games": 4},
    {"p1_games": 6, "p2_games": 3}
  ],
  "winner_uid": "user_abc"
}
```

For doubles results `winner_uid` is an empty string `""` — use `winner_team` on the request instead.

### SportRanking

Used in offer/broadcast payloads to show opponent skill level.

```json
{"sport": "tennis", "pts": 820}
```

---

## Endpoint Index

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/me/broadcast` | Start an availability broadcast |
| `POST` | `/me/offers` | Send a challenge offer to another user |
| `POST` | `/me/offers/{offerId}/accept` | Accept an incoming offer; creates a match |
| `POST` | `/matches/{matchId}/verify-score` | Submit or confirm a match result |
| `GET` | `/me/state` | Current play-tab mode and mode-specific payload |
| `GET` | `/venues/search` | Free-text venue search (curated + Google Places) |
| `GET` | `/venues` | List curated venues for a sport |
| `POST` | `/venues/suggest` | Submit a venue to the moderation queue |
| `GET` | `/leagues` | Browse leagues with filters and cursor pagination |
| `GET` | `/leagues/{id}` | Get full league detail |
| `GET` | `/leagues/{id}/standings` | Get league standings (auth: member) |
| `GET` | `/leagues/{id}/matches` | List upcoming or completed league matches (auth: member) |
| `POST` | `/leagues/{id}/join` | Self-serve join a league |

---

## Contracts

### POST /me/broadcast

**Auth:** Required (Firebase Bearer ID token).

#### Request body

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
    "radius_km": 10.0
  }
}
```

Field rules:
- `match_type`: `"singles"` | `"doubles"`, default `"singles"`.
- `broadcast_type`: `"find_opponent"` | `"find_fourth"`, default `"find_opponent"`.
- `partner_uid`: `null` for singles; required for `doubles + find_opponent`; optional for
  `doubles + find_fourth`.
- `availability`: `"today"` | `"tomorrow"` | `"weekend"`.
- `court_status`: `"have_court"` | `"need_court"`.
- `court_location`: free-text string or `null`.
- `venue_ref`: only stored when `court_status=have_court`; ignored for `need_court`.
- `expires_at`: ISO 8601 datetime, must be in the future.
- `location.area`: integer area key or `null`.
- `location.geo`: `{lat, lng}` or `null`.
- `location.radius_km`: float or `null`.

Doubles rules:
- `find_fourth` requires `match_type=doubles`.
- `doubles + find_opponent` requires `partner_uid` to be set.
- `doubles + find_fourth` with no `partner_uid` means a solo player seeking three others — valid.

#### Response (`201`)

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

#### Doubles example — `find_fourth`

Request:

```json
{
  "sport": "padel",
  "match_type": "doubles",
  "broadcast_type": "find_fourth",
  "partner_uid": "user_partner_1",
  "availability": "today",
  "court_status": "have_court",
  "court_location": "Flisvos Padel Academy",
  "venue_ref": {
    "venueId": "venue_flisvos",
    "placeId": "ChIJFlisvos",
    "name": "Flisvos Padel Academy",
    "coordinates": {"lat": 37.93, "lng": 23.68}
  },
  "expires_at": "2026-02-03T16:00:00Z",
  "location": {"area": 102, "geo": null, "radius_km": null}
}
```

Response (`201`):

```json
{
  "broadcast_id": "broadcast_dbl_abc",
  "sport": "padel",
  "match_type": "doubles",
  "broadcast_type": "find_fourth",
  "partner_uid": "user_partner_1",
  "availability": "today",
  "court_status": "have_court",
  "court_location": "Flisvos Padel Academy",
  "status": "active",
  "expires_at": "2026-02-03T16:00:00Z",
  "created_at": "2026-02-03T08:00:00Z"
}
```

#### Key error codes

| Code | Condition |
|------|-----------|
| `401` | Missing or invalid token |
| `409` | User is not in `DISCOVERY` state (active broadcast, offer, or match exists) |
| `422` | Validation error — `expires_at` in the past, missing required fields, invalid doubles combination |

---

### POST /me/offers

**Auth:** Required.

#### Request body (SendOfferRequest)

```json
{
  "to_uid": "user_789",
  "sport": "tennis",
  "match_type": "singles",
  "partner_uid": null,
  "proposed_time": "2026-02-03T18:00:00Z",
  "court_location": "Central Court, Athens",
  "venue_ref": null,
  "source_broadcast_id": null,
  "message": "Up for a game?",
  "league_id": null
}
```

Field rules:
- `match_type`: `"singles"` | `"doubles"`, default `"singles"`.
- `partner_uid`: `null` for singles; required for doubles.
- `court_location`: optional free-text.
- `venue_ref`: optional `VenueRef` object or `null`.
- `source_broadcast_id`: optional — links to an originating broadcast.
- `message`: optional, max 300 chars.
- `league_id`: optional string or `null`. When set, the offer and resulting match are tagged as a
  league match. The referenced league must have status `active` (not `open` or `upcoming`). Both
  caller and recipient must be active members of the referenced league. The match will appear in
  league standings once completed.

#### Response (`201`, SendOfferResponse)

```json
{
  "offer_id": "offer_123",
  "to_uid": "user_789",
  "to_name": "Jamie",
  "sport": "tennis",
  "match_type": "singles",
  "partner_uid": null,
  "proposed_time": "2026-02-03T18:00:00Z",
  "status": "pending",
  "expires_at": "2026-02-03T10:10:00Z",
  "created_at": "2026-02-03T10:05:00Z"
}
```

Note: `venue_ref` and `source_broadcast_id` are stored but NOT echoed in the response (see Known
Limitations).

#### Doubles example

Request:

```json
{
  "to_uid": "user_789",
  "sport": "padel",
  "match_type": "doubles",
  "partner_uid": "user_partner_1",
  "proposed_time": "2026-02-03T18:00:00Z",
  "court_location": "Flisvos Padel Academy",
  "venue_ref": {
    "venueId": "venue_flisvos",
    "placeId": "ChIJFlisvos",
    "name": "Flisvos Padel Academy",
    "coordinates": {"lat": 37.93, "lng": 23.68}
  },
  "message": "Doubles game?",
  "league_id": null
}
```

Response (`201`):

```json
{
  "offer_id": "offer_dbl_456",
  "to_uid": "user_789",
  "to_name": "Jamie",
  "sport": "padel",
  "match_type": "doubles",
  "partner_uid": "user_partner_1",
  "proposed_time": "2026-02-03T18:00:00Z",
  "status": "pending",
  "expires_at": "2026-02-03T10:10:00Z",
  "created_at": "2026-02-03T10:05:00Z"
}
```

#### Key error codes

| Code | Condition |
|------|-----------|
| `401` | Missing or invalid token |
| `404` | Target user not found; or (when `league_id` is set) league not found |
| `409` | Sender not in valid state, or already has an active outgoing offer; or (when `league_id` is set) league not `active`, or caller/recipient is not an active league member |
| `422` | Validation error |

---

### POST /me/offers/{offerId}/accept

**Auth:** Required. Caller must be the offer recipient (`offer.to_uid`).

#### Request body

None.

#### Response (`200`, OfferActionResponse)

```json
{
  "offer_id": "offer_456",
  "status": "accepted",
  "match_id": "match_789",
  "scheduled_at": "2026-02-03T18:00:00Z"
}
```

Note: does not return full match details — only `match_id` and `scheduled_at` (see Known
Limitations). Use `GET /me/state` to retrieve the full `MATCH_SCHEDULED` payload.

#### Key error codes

| Code | Condition |
|------|-----------|
| `401` | Missing or invalid token |
| `403` | Caller is not the offer recipient |
| `404` | Offer not found |
| `409` | Offer already resolved (accepted/declined/expired) or match conflict |
| `410` | Offer expired |

---

### POST /matches/{matchId}/verify-score

**Auth:** Required. Caller must be a participant in the match.

**IMPORTANT:** This single endpoint handles both the initial result submission (first call, when
match is `scheduled`) and the opponent's confirmation step (second call, when match is
`pending_confirmation`). Earlier planning documents referred to these as
`POST /matches/{id}/result` and `POST /matches/{id}/confirm` respectively. They are implemented
as one endpoint that branches on match status.

#### Two-call flow

| Call | Match status before | Match status after | Scoring written? |
|------|--------------------|--------------------|-----------------|
| 1st (submit result) | `scheduled` | `pending_confirmation` | No — deltas are 0 |
| 2nd (agree) | `pending_confirmation` | `completed` | Yes |
| 2nd (disagree) | `pending_confirmation` | `disputed` | No |

#### Request body (VerifyScoreRequest)

Provide exactly one of `winner_uid` (singles) or `winner_team` (doubles).

**Singles:**

```json
{
  "winner_uid": "user_abc",
  "score": {
    "sets": [
      {"p1_games": 6, "p2_games": 4},
      {"p1_games": 6, "p2_games": 3}
    ],
    "winner_uid": "user_abc"
  },
  "walkover": false
}
```

**Doubles:**

```json
{
  "winner_team": "A",
  "score": {
    "sets": [
      {"p1_games": 6, "p2_games": 4},
      {"p1_games": 6, "p2_games": 3}
    ],
    "winner_uid": ""
  },
  "walkover": false
}
```

Field rules:
- `winner_uid`: set for singles; omit (or `null`) for doubles.
- `winner_team`: `"A"` or `"B"`; set for doubles; omit (or `null`) for singles.
- `score`: optional but strongly recommended. May be `null` when `walkover=true`.
- `walkover`: `true` skips ELO/points scoring — all deltas are 0, match goes straight to
  `completed` (or `pending_confirmation` depending on flow).

#### Response (VerifyScoreResponse)

**First call — match moves to `pending_confirmation` (`200`):**

```json
{
  "match_id": "match_789",
  "status": "pending_confirmation",
  "winner_uid": "user_abc",
  "loser_uid": "user_xyz",
  "winner_team": null,
  "loser_team": null,
  "winner_delta": 0,
  "loser_delta": 0,
  "winner_new_pts": 0,
  "loser_new_pts": 0,
  "scoring": null
}
```

**Second call, agreed — match moves to `completed` (`200`):**

```json
{
  "match_id": "match_789",
  "status": "completed",
  "winner_uid": "user_abc",
  "loser_uid": "user_xyz",
  "winner_team": null,
  "loser_team": null,
  "winner_delta": 35,
  "loser_delta": -20,
  "winner_new_pts": 855,
  "loser_new_pts": 780,
  "scoring": {
    "sport": "tennis",
    "your_pts_before": 820,
    "your_pts_after": 855,
    "delta": 35,
    "breakdown": {
      "base_win": 25,
      "upset_bonus": 10,
      "elo_bonus": 0,
      "penalty": 0
    },
    "tier_before": "intermediate",
    "tier_after": "intermediate",
    "tier_crossed": false
  }
}
```

**Doubles completed response:**

```json
{
  "match_id": "match_dbl_999",
  "status": "completed",
  "winner_uid": "",
  "loser_uid": "",
  "winner_team": "A",
  "loser_team": "B",
  "winner_delta": 28,
  "loser_delta": -18,
  "winner_new_pts": 848,
  "loser_new_pts": 762,
  "scoring": {
    "sport": "padel",
    "your_pts_before": 820,
    "your_pts_after": 848,
    "delta": 28,
    "breakdown": {
      "base_win": 20,
      "upset_bonus": 8,
      "elo_bonus": 0,
      "penalty": 0
    },
    "tier_before": "intermediate",
    "tier_after": "intermediate",
    "tier_crossed": false
  }
}
```

`scoring` (ScoringPayload) is only populated on a `completed` match. It is always `null` on the
first call and on `pending_confirmation` responses. `winner_delta`/`loser_delta`/`winner_new_pts`/
`loser_new_pts` are all `0` until the match completes.

#### Key error codes

| Code | Condition |
|------|-----------|
| `401` | Missing or invalid token |
| `403` | Caller is not a participant in this match |
| `404` | Match not found |
| `409` | Invalid state transition (e.g. match already `completed`, walkover on non-`scheduled` match) |
| `500` | Server misconfiguration (missing tier config) |

---

### GET /me/state

**Auth:** Required.

#### Query parameters

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `match_type` | `singles\|doubles` | No | Filters the DISCOVERY feed by broadcast type. Silently ignored in all other modes. |

#### Request body

None.

#### Response envelope (`200`)

```json
{
  "mode": "DISCOVERY",
  "server_time": "2026-02-03T10:00:00Z",
  "primary": {
    "broadcast_id": null,
    "match_id": null,
    "active_offer_ids": []
  },
  "payload": {},
  "annotations": {},
  "ui_events": []
}
```

`mode` is one of: `DISCOVERY`, `BROADCAST_ACTIVE`, `OUTGOING_OFFER_PENDING`,
`INCOMING_OFFER_PENDING`, `MATCH_SCHEDULED`, `POST_MATCH_LOG_AVAILABLE`,
`POST_MATCH_WAITING_OPPONENT`, `POST_MATCH_CONFIRM_REQUIRED`, `MATCH_DISPUTED`.

For full per-mode payload shapes see `spec/tab1-play-payloads.md`.

Doubles additions to specific modes:
- `BROADCAST_ACTIVE` payload also carries: `match_type`, `broadcast_type`, `partner_uid`,
  `partner_name`.
- `MATCH_SCHEDULED` payload also carries: `match_type: "doubles"` and
  `participants: [{uid, name, team, role}]` list with one entry per player (4 total for doubles).
- `POST_MATCH_LOG_AVAILABLE`, `POST_MATCH_WAITING_OPPONENT`, `POST_MATCH_CONFIRM_REQUIRED`
  payloads also carry `match_type: "doubles"` and `participants` when the match is a doubles
  match.

#### Key error codes

| Code | Condition |
|------|-----------|
| `401` | Missing or invalid token |

---

### GET /venues/search

**Auth:** Required.

#### Query parameters

| Param | Type | Required | Constraints |
|-------|------|----------|-------------|
| `q` | string | Yes | 1–200 chars |
| `lat` | float | No | -90 to 90 |
| `lng` | float | No | -180 to 180 |

#### Response (`200`)

```json
{
  "results": [
    {
      "venueId": "venue_flisvos",
      "placeId": "ChIJFlisvos",
      "name": "Flisvos Padel Academy",
      "coordinates": {"lat": 37.93, "lng": 23.68}
    },
    {
      "venueId": null,
      "placeId": "ChIJGoogleResult",
      "name": "Glyfada Padel Club",
      "coordinates": {"lat": 37.88, "lng": 23.74}
    }
  ]
}
```

Returns at most 5 results. Curated venues (with `venueId`) appear first; Google Places results
(with `venueId: null`) follow. Results are deduped by `placeId`.

#### Key error codes

| Code | Condition |
|------|-----------|
| `401` | Missing or invalid token |
| `422` | Validation error (`q` empty, `lat`/`lng` out of range) |
| `502` | Upstream Google Places error |
| `503` | Google Places API key not configured (emulator / dev environments) |

---

### GET /venues

**Auth:** Required.

#### Query parameters

| Param | Type | Required | Constraints |
|-------|------|----------|-------------|
| `sport` | `tennis\|padel\|pickleball` | Yes | |
| `area` | string | No | Exact area match |
| `limit` | int | No | 1–100, default 20 |
| `cursor` | string | No | Opaque pagination token |

#### Response (`200`)

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

Returns `200` with `venues: []` when no venues match (never `404`).

#### Key error codes

| Code | Condition |
|------|-----------|
| `400` | Invalid cursor token |
| `401` | Missing or invalid token |
| `422` | Validation error (invalid `sport`, `limit` out of range) |

---

### POST /venues/suggest

**Auth:** Required.

#### Request body

```json
{
  "name": "My Local Club",
  "coordinates": {"lat": 37.95, "lng": 23.72},
  "sport": "padel",
  "notes": "2 outdoor courts, open until 11pm"
}
```

Field constraints: `name` 1–200 chars; `notes` max 500 chars; `sport` one of
`tennis|padel|pickleball`; coordinates in valid range.

#### Response (`201`)

```json
{"suggestionId": "abc123"}
```

Writes to `venueSuggestions/{autoId}` with `status="pending"`. Not promoted to the live `venues`
collection until moderated.

#### Key error codes

| Code | Condition |
|------|-----------|
| `401` | Missing or invalid token |
| `422` | Validation error (missing/invalid fields) |

---

### GET /leagues

**Auth:** Required (Firebase Bearer ID token).

**Query parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `region` | string | No | Filter by region (e.g. `"athens"`) |
| `sport` | `tennis\|padel\|pickleball` | No | Filter by sport |
| `status` | `open\|active\|upcoming\|completed` | No | Filter by league status (default: `open`) |
| `limit` | int (1–50) | No | Max results per page (default: `20`) |
| `cursor` | string | No | Opaque pagination token from previous response |

**Response (`200`):**

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
      "start_date": "2025-06-01T00:00:00Z"
    }
  ],
  "next_cursor": null
}
```

`next_cursor` is `null` when there are no more pages. Treat it as opaque — do not parse. Returns
`200` with `leagues: []` when no results match (never `404`).

**Key error codes:**

| Code | Condition |
|------|-----------|
| `400` | Invalid cursor token |
| `401` | Missing or invalid token |
| `422` | Validation error (invalid `sport` or `status`, `limit` out of range) |

---

### GET /leagues/{id}

**Auth:** Required. No league membership check — any authenticated user can fetch league detail.

**Path parameter:** `id` — the league's Firestore document ID.

**Request body:** None.

**Response (`200`):**

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
  "start_date": "2025-06-01T00:00:00Z",
  "end_date": null,
  "tier": "intermediate",
  "meta": null
}
```

**Key error codes:**

| Code | Condition |
|------|-----------|
| `401` | Missing or invalid token |
| `404` | League not found |

---

### GET /leagues/{id}/standings

**Auth:** Required. Caller must be an active member of the league.

**Path parameter:** `id` — league ID.

**Request body:** None.

**Response (`200`):**

```json
{
  "league_id": "padel-local-2025",
  "standings": [
    {
      "rank": 1,
      "uid": "user_abc",
      "display_name": "user_abc",
      "wins": 5,
      "losses": 1,
      "tier_ring": null
    },
    {
      "rank": 2,
      "uid": "user_xyz",
      "display_name": "user_xyz",
      "wins": 3,
      "losses": 2,
      "tier_ring": null
    }
  ]
}
```

Sorted by wins (desc), losses (asc), net wins (desc), then name (asc). Dense ranking (tied players
share a rank; next rank is `+1`, not `+gap`).

MVP notes: `display_name` falls back to `uid` (will be fixed in issue #325); `tier_ring` is always
`null` at MVP.

**Key error codes:**

| Code | Condition |
|------|-----------|
| `401` | Missing or invalid token |
| `403` | Caller is not a member of the league |
| `404` | League not found |

---

### GET /leagues/{id}/matches

**Auth:** Required. Caller must be an active member of the league.

**Path parameter:** `id` — league ID.

**Query parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `upcoming\|completed` | No | Match filter (default: `upcoming`) |
| `limit` | int (1–50) | No | Max results per page (default: `10`) |
| `cursor` | string | No | Opaque pagination token from previous response |

**Response (`200`):**

```json
{
  "matches": [
    {
      "match_id": "match_abc",
      "league_id": "padel-local-2025",
      "sport": "padel",
      "match_type": "singles",
      "status": "scheduled",
      "scheduled_at": "2026-06-10T18:00:00Z",
      "finished_at": null
    }
  ],
  "next_cursor": null
}
```

`next_cursor` is opaque — do not parse. Returns `200` with `matches: []` when no results match.

**Key error codes:**

| Code | Condition |
|------|-----------|
| `400` | Invalid cursor token |
| `401` | Missing or invalid token |
| `403` | Caller is not a member of the league |
| `404` | League not found |

---

### POST /leagues/{id}/join

**Auth:** Required.

**Path parameter:** `id` — league ID.

**Request body:** None.

**Response (`201`, LeagueMember):**

```json
{
  "uid": "user_abc",
  "role": "player",
  "status": "active",
  "joined_at": "2026-06-01T10:00:00Z",
  "stats": null
}
```

Preconditions:
- League must exist.
- League `status` must be `open` or `upcoming`.
- Caller must not already be a member.
- League must not be at full capacity (`current_players >= max_players`, if both are set).

On success: creates `leagues/{id}/members/{uid}` document and atomically increments
`current_players` on the league document.

**Key error codes:**

| Code | Condition |
|------|-----------|
| `401` | Missing or invalid token |
| `404` | League not found |
| `409` | Already a member, league not `open`/`upcoming`, or league at full capacity |

---

## Known Limitations and Deferred Fields

1. **`POST /matches/{id}/verify-score` — dispute resolution:** When the second call disagrees the
   match moves to `disputed`, but there is no API endpoint for dispute resolution at MVP.
   Disputed matches require admin intervention via the Firebase console.

2. **`POST /me/offers` response — omitted fields:** `venue_ref` and `source_broadcast_id` are
   stored on the offer document but are NOT echoed back in the `SendOfferResponse`. The iOS client
   should not rely on reading these from the offer creation response.

3. **`POST /me/offers/{id}/accept` — partial response:** The accept response returns only
   `offer_id`, `status`, `match_id`, and `scheduled_at`. Full match participant details (names,
   rankings, venue) are not returned. Use `GET /me/state` (mode `MATCH_SCHEDULED`) to get the
   full logistics card.

4. **Offer expiry is hardcoded:** Offers expire 5 minutes after creation. This is not configurable
   per-offer at launch.

5. **`GET /venues/search` — Google Places dependency:** This endpoint requires a live Google
   Places API key. In the emulator and dev environments it returns `503 Service Unavailable`.
   The iOS client must handle `503` gracefully and fall back to `GET /venues` for curated results.

6. **Vestigial court fields in `MATCH_SCHEDULED`:** `court_id`, `court_name`, and `court_geo` in the
   `MATCH_SCHEDULED` payload are legacy fields kept for backwards compatibility. The canonical
   court/venue info is in `venue_ref`. New clients should read `venue_ref` and ignore the
   individual court fields.

7. **Doubles `find_fourth` with no `partner_uid`:** A broadcast with
   `broadcast_type=find_fourth` and `partner_uid=null` represents a solo player seeking three
   others to fill a doubles game. This is valid and supported at launch. The iOS client should
   render it as "Looking for 3 players" rather than "Looking for 1 opponent".

8. **League match creation — no dedicated endpoint:** League matches are not created via a
   dedicated endpoint. They use the standard offer flow (`POST /me/offers` with `league_id` set,
   introduced in LGM-1 / PR #333). The league must be `active` (not `open` or `upcoming`), and
   both offer sender and recipient must be active members of the league. The resulting match carries
   `league_id` and counts toward league standings once completed.
