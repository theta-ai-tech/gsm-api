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
| `GET` | `/me/discovery` | Browsable list of active intents (state-agnostic) |
| `GET` | `/venues/search` | Free-text venue search (curated + Google Places) |
| `GET` | `/venues` | List curated venues for a sport |
| `POST` | `/venues/suggest` | Submit a venue to the moderation queue |
| `GET` | `/leagues` | Browse leagues with filters and cursor pagination |
| `GET` | `/leagues/{id}` | Get full league detail |
| `GET` | `/leagues/{id}/standings` | Get league standings (auth: member) |
| `GET` | `/leagues/{id}/matches` | List upcoming or completed league matches (auth: member) |
| `GET` | `/leagues/{id}/divisions` | List kickoff-created league divisions (auth: member) |
| `GET` | `/leagues/{id}/divisions/{divisionId}/standings` | Get division standings (auth: member) |
| `GET` | `/leagues/{id}/divisions/{divisionId}/matches` | List division upcoming or completed matches (auth: member) |
| `POST` | `/leagues/{id}/join` | Self-serve join: singles self-join, or doubles team invite with a partner |
| `POST` | `/leagues/{id}/teams/{teamId}/accept` | Invited partner accepts a pending team (auth: partner) |
| `POST` | `/leagues/{id}/teams/{teamId}/decline` | Invited partner declines a pending team (auth: partner) |
| `DELETE` | `/leagues/{id}/teams/{teamId}` | Captain cancels a pending team invite (auth: captain) |
| `GET` | `/leagues/{id}/teams` | List league teams (`?mine=true` for the caller's invites/teams) |
| `GET` | `/players` | Search registered players by name prefix (partner picker) |
| `POST` | `/leagues/{id}/kickoff` | Admin kickoff: split open league members (or doubles teams) into divisions |
| `DELETE` | `/me/account` | Permanently delete the caller's account (anonymize-in-place) |
| `GET` | `/me/clubhouse/profile` | Athlete Card & Resume for the caller's Profile tab |
| `PATCH` | `/me/clubhouse/profile` | Partial update of the caller's editable profile fields |

---

## Contracts

### DELETE /me/account

**Auth:** Required (Firebase Bearer ID token). Self-only — no target `uid`.

**Request body:** None.

**Response:** `204 No Content`.

**Behavior (anonymize-in-place, no cascade):**

Data erasure runs first (while the caller's token is still valid, so a mid-flow failure is
idempotently retryable); identity destruction is last and is a single op:
1. Hard-delete `users/{uid}/journalEntries`, `users/{uid}/pointHistory`, and device tokens.
2. Tombstone `users/{uid}`: keep `uid` + `rankings`; set `name = "Deleted Player"`,
   `profileUrl = null`, `isDeleted = true`, `deletedAt = now`; strip all PII.
3. Delete the Firebase Auth user (idempotent if already gone). This is the single destructive
   Auth op — refresh tokens are **not** revoked separately; `delete_user` already drops them,
   and a separate revoke would add a revoked-but-not-deleted window.

Match, scouting, ticker, leaderboard and opponents' point-history documents are **not**
deleted or mutated. Opponents' rivalry/scouting/profile reads against the deleted uid keep
returning `200` as "Deleted Player". Tombstoned users are excluded from the next scheduled
leaderboard recompute.

**Errors:**
- `401` missing/invalid token.

---

### GET /me/clubhouse/profile

**Auth:** Required (Firebase Bearer ID token). Self-only — no target `uid`.

**Request body:** None.

**Response `200`:**

```json
{
  "uid": "user_ignatios",
  "display_name": "Ignatios C.",
  "avatar_url": "https://cdn.example.com/a.png",
  "resume": {
    "total_matches": 2,
    "total_wins": 1,
    "leagues_completed": 0,
    "sports": [
      {
        "sport": "tennis",
        "pts": 820,
        "tier": "amateur",
        "global_ranking": 340,
        "personal_best": 850,
        "current_streak": 3,
        "best_streak": 5
      }
    ]
  }
}
```

Counts derive from capped denormalized caches (`completedMatches` max 10,
`leaguesCompleted` max 20).

**Errors:**
- `401` missing/invalid token.
- `404` user not found.

---

### PATCH /me/clubhouse/profile

**Auth:** Required (Firebase Bearer ID token). Self-only — no target `uid`.

**Request body** (all fields optional; at least one required):

```json
{
  "display_name": "New Name",
  "avatar_url": "https://cdn.example.com/a.png",
  "area": 202,
  "levels": {"tennis": "advanced"}
}
```

**Field rules:**
- `display_name` — whitespace-stripped, non-empty, max length 100. Also updates the
  `nameLower` search index. Empty/whitespace-only → `422`.
- `avatar_url` — valid **https** URL; `http://` → `422`. Cannot be cleared (omit to keep).
- `area` — integer key validated against `config/regions`; unknown → `422`.
- `levels` — per-sport **merge** (`tennis`/`padel`/`pickleball` → `LevelEnum`); only the
  provided sports change, others keep their existing level. Invalid sport key or level → `422`.
- Unknown top-level fields → `422` (strict model).

**Response `200`:** identical shape to `GET /me/clubhouse/profile`, reflecting the update.

**Levels never change rankings:** editing `levels` does not touch `rankings.pts`,
`rankings.tier`, or any `rankings.*` field.

**Display-name eventual consistency:** there is **no synchronous fan-out**. Historical match
`participants[].displayName`, ticker names, leaderboard `name`, offer `from_name`/`to_name`,
and discovery `owner_name` retain the old value; new writes pick up the new name; the scheduled
leaderboard recompute refreshes leaderboard names. `avatar_url` is read live everywhere.

**Errors:**
- `400` empty body (no fields provided).
- `401` missing/invalid token.
- `404` user not found (including a tombstoned/deleted account).
- `422` unknown `area`, non-https `avatar_url`, invalid level/sport enum, unknown field, or
  empty `display_name`.

---

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
  "winner_delta": 164,
  "loser_delta": -50,
  "winner_new_pts": 2984,
  "loser_new_pts": 3050,
  "scoring": {
    "sport": "tennis",
    "your_pts_before": 2820,
    "your_pts_after": 2984,
    "delta": 164,
    "breakdown": {
      "base_win": 100,
      "upset_bonus": 50,
      "elo_bonus": 14,
      "penalty": 0
    },
    "tier_before": "intermediate",
    "tier_after": "intermediate",
    "tier_crossed": false
  }
}
```

This is an upset: an Intermediate winner (2820 pts) beats an Advanced loser (3100 pts), earning
`base 100 + upset 50 + elo floor((3100 - 2820) * 0.05) = 14`, total `+164`. The loser takes the flat
`-50` penalty (3100 → 3050, above the Advanced 3000 floor, so no clamp). See
[`../operations/scoring.md`](../operations/scoring.md) for the
full formula and worked examples.

**Doubles completed response:**

```json
{
  "match_id": "match_dbl_999",
  "status": "completed",
  "winner_uid": "",
  "loser_uid": "",
  "winner_team": "A",
  "loser_team": "B",
  "winner_delta": 0,
  "loser_delta": 0,
  "winner_new_pts": 0,
  "loser_new_pts": 0,
  "scoring": {
    "sport": "padel",
    "your_pts_before": 1900,
    "your_pts_after": 2070,
    "delta": 170,
    "breakdown": {
      "base_win": 100,
      "upset_bonus": 50,
      "elo_bonus": 20,
      "penalty": 0
    },
    "tier_before": "amateur",
    "tier_after": "intermediate",
    "tier_crossed": true
  }
}
```

Doubles is scored per-player against the **opposing pair's average pts** (integer division) and the
**highest-tier opponent**. Here the calling player (Amateur, 1900 pts) is scored against the loser
pair's average of `(2200 + 2400) // 2 = 2300` pts at Intermediate tier — an upset: `base 100 + upset
50 + elo floor((2300 - 1900) * 0.05) = 20`, total `+170`, crossing Amateur → Intermediate. See
[`../operations/scoring.md`](../operations/scoring.md) for the full per-player model and worked
example.

`scoring` (ScoringPayload) is only populated on a `completed` match. It is always `null` on the
first call and on `pending_confirmation` responses. `winner_delta`/`loser_delta`/`winner_new_pts`/
`loser_new_pts` are all `0` until the match completes; on completed doubles responses they also remain
`0` because doubles scoring is per-player and exposed through the caller-specific `scoring` payload
instead of aggregate top-level fields.

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

For full per-mode payload shapes see `docs/design/tab1-play-payloads.md`.

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

### GET /me/discovery

**Auth:** Required (Firebase Bearer ID token).

Always available regardless of the caller's current play state. A user in
`BROADCAST_ACTIVE`, `MATCH_SCHEDULED`, or any other mode can call this to browse
active intents — unlike the `DISCOVERY` payload in `GET /me/state`, which is only
present when `mode == DISCOVERY`.

#### Query parameters

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `sport` | `tennis\|padel\|pickleball` | No | Filter by sport. |
| `match_type` | `singles\|doubles` | No | Filter by singles/doubles. |

#### Request body

None.

#### Response (`200`)

```json
{
  "serverTime": "2026-06-24T12:00:00Z",
  "activeClubsNearby": 2,
  "intents": [
    {
      "toUid": "user_alice",
      "name": "Alice",
      "ranking": null,
      "level": "advanced",
      "sport": "padel",
      "matchType": "singles",
      "broadcastType": "find_opponent",
      "availability": "today",
      "courtStatus": "have_court",
      "venueRef": {
        "venueId": "venue_glyfada_padel",
        "placeId": null,
        "name": "Glyfada Padel Club",
        "coordinates": {"lat": 37.88, "lng": 23.75}
      },
      "areaName": null,
      "expiresAt": "2026-07-01T12:00:00Z",
      "createdAt": "2026-06-24T12:00:00Z",
      "broadcastId": "broadcast_seed_alice_padel"
    }
  ]
}
```

**Field notes:**
- `activeClubsNearby`: count of distinct `location.area` values across all returned broadcasts.
  Falls back to the count of intents when no broadcasts have an area set.
- `areaName`: human-readable region name (e.g. `"athens"`), resolved from `config/regions`
  mapping. Only populated for `courtStatus == "need_court"` broadcasts that carry a `location.area`.
  `null` when the broadcast has no area or the region config is unavailable.
- `venueRef`: populated only for `courtStatus == "have_court"` broadcasts. `null` for
  `need_court` broadcasts.
- `level`: self-assessed skill level from the owner's private profile preferences for the
  broadcast sport. `null` if the owner has not set a level for that sport.

#### Key error codes

| Code | Condition |
|------|-----------|
| `401` | Missing or invalid token |
| `422` | Invalid `sport` or `match_type` query parameter value |

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

**Doubles leagues (`format: "doubles"`): a standings row is a team, not a player.**
Each entry additionally carries `team_id` and `member_uids`; `display_name` is the team
name (`"Captain / Partner"`) and `uid` carries the captain uid as the stable row key.
Team wins/losses are the captain's member stats — partners always share identical league
match participation, so they are the team's record. Singles leagues return `team_id: null`
and `member_uids: null` on every row.

```json
{
  "rank": 1,
  "uid": "user_alice",
  "display_name": "Alice / Bob",
  "wins": 5,
  "losses": 1,
  "tier_ring": null,
  "team_id": "team-alice-bob",
  "member_uids": ["user_alice", "user_bob"]
}
```

The same doubles row shape applies to `GET /leagues/{id}/divisions/{divisionId}/standings`
(rows filtered to teams whose `division_id` matches).

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

### GET /leagues/{id}/divisions

**Auth:** Required. Caller must be an active member of the league.

**Path parameter:** `id` — league ID.

**Request body:** None.

**Response (`200`):**

```json
{
  "league_id": "padel-divisions-open-2026",
  "divisions": [
    {
      "division_id": "div-1",
      "name": "Division 1",
      "ordinal": 1,
      "rating_range": {"min": 1350, "max": 1800},
      "current_players": 6,
      "status": "active"
    }
  ]
}
```

Divisions are returned in `ordinal` order from `leagues/{id}/divisions`. Pre-kickoff leagues return
`409` with detail `league not yet divided`.

**Key error codes:**

| Code | Condition |
|------|-----------|
| `401` | Missing or invalid token |
| `403` | Caller is not a member of the league |
| `404` | League not found |
| `409` | League has not completed division kickoff |

---

### GET /leagues/{id}/divisions/{divisionId}/standings

**Auth:** Required. Caller must be an active member of the league.

**Path parameters:**
- `id` — league ID.
- `divisionId` — division ID.

**Request body:** None.

**Response (`200`):**

```json
{
  "league_id": "padel-divisions-open-2026",
  "standings": [
    {
      "rank": 1,
      "uid": "user_abc",
      "display_name": "user_abc",
      "wins": 5,
      "losses": 1,
      "tier_ring": null
    }
  ]
}
```

Uses the same dense-ranking rules as league standings, but only includes members whose member doc
has the requested `divisionId`.

**Key error codes:**

| Code | Condition |
|------|-----------|
| `401` | Missing or invalid token |
| `403` | Caller is not a member of the league |
| `404` | League or division not found |
| `409` | League has not completed division kickoff |

---

### GET /leagues/{id}/divisions/{divisionId}/matches

**Auth:** Required. Caller must be an active member of the league.

**Path parameters:**
- `id` — league ID.
- `divisionId` — division ID.

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
      "league_id": "padel-divisions-open-2026",
      "division_id": "div-1",
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

Upcoming matches are filtered by `matches.leagueId`, `matches.divisionId`, and `status=scheduled`,
then ordered by `scheduledAt` ascending. Completed matches use `status=completed` and
`finishedAt` descending. `next_cursor` is opaque. Returns `200` with `matches: []` when no results
match.

**Key error codes:**

| Code | Condition |
|------|-----------|
| `400` | Invalid cursor token |
| `401` | Missing or invalid token |
| `403` | Caller is not a member of the league |
| `404` | League or division not found |
| `409` | League has not completed division kickoff |

---

### POST /leagues/{id}/join

**Auth:** Required.

**Path parameter:** `id` — league ID.

Behavior branches on the league's `format` field (`"singles"` — the default when absent —
or `"doubles"`). iOS must read `format` from the league detail/browse card and must not
derive it from the sport.

#### Singles leagues (`format: "singles"`) — unchanged

**Request body:** None (an empty JSON object is also accepted).

**Response (`201`, LeagueMember):**

```json
{
  "uid": "user_abc",
  "role": "player",
  "status": "active",
  "joined_at": "2026-06-01T10:00:00Z",
  "stats": null,
  "display_name": "Alice",
  "division_id": null,
  "team_id": null,
  "partner_uid": null
}
```

Preconditions:
- League must exist.
- League `status` must be `open` or `upcoming`.
- Caller must not already be a member.
- League must not be at full capacity (`current_players >= max_players`, if both are set).

On success: creates `leagues/{id}/members/{uid}` document and atomically increments
`current_players` on the league document.

#### Doubles leagues (`format: "doubles"`) — team invite

**Request body (required):**

```json
{ "partner_uid": "user_partner" }
```

The partner must be a **registered** user (find one via `GET /players?search=`).
Consent model: **pending team until accept** — this call creates a team in `pending`
status and notifies the partner; nobody becomes a league member and **no capacity is
consumed** until the partner accepts.

**Response (`201`, LeagueTeam):**

```json
{
  "team_id": "aUt0GeNeRaTeD",
  "status": "pending",
  "captain_uid": "user_captain",
  "partner_uid": "user_partner",
  "member_uids": ["user_captain", "user_partner"],
  "name": "Cap Tain / Part Ner",
  "created_at": "2026-06-10T15:00:00Z",
  "accepted_at": null,
  "rating_avg": null,
  "division_id": null
}
```

Preconditions:
- League must exist and have `format: "doubles"`.
- League `status` must be `open` or `upcoming`.
- `partner_uid` must be present, a registered user, and different from the caller.
- Neither caller nor partner may already be a member, or in another `pending`/`active`
  team in this league (one team per user per league).

**Key error codes (both formats):**

| Code | Condition |
|------|-----------|
| `400` | `partner_uid` sent to a singles league; missing `partner_uid` on a doubles league; partner is the caller |
| `401` | Missing or invalid token |
| `404` | League not found; partner uid not a registered user |
| `409` | Caller or partner already a member; caller or partner already in a pending/active team; league not `open`/`upcoming`; league at full capacity |

iOS renders the `409` variants as the three calm states (already-in / season-underway /
full); partner-side conflicts ("partner unavailable") surface inside the partner picker.

---

### POST /leagues/{id}/teams/{teamId}/accept

**Auth:** Required; caller must be the invited partner (`partner_uid`) of the team.

**Request body:** None.

Transactionally re-checks: team still `pending`, league still `open`/`upcoming`, neither
player already a member, and capacity — a doubles team consumes **2 player slots**, so the
accept fails with `409` unless `current_players + 2 <= max_players` (when both are set).
Two pending invites racing for the last slots are resolved here: the losing accept gets
the capacity `409`.

On success: sets the team `active` (+ `accepted_at`), creates **both** member documents
(each carrying `team_id` and the cross-linked `partner_uid`), increments
`current_players` by 2, and notifies the captain.

**Response (`200`, LeagueTeam)** — same shape as above with `"status": "active"` and
`accepted_at` set.

**Key error codes:**

| Code | Condition |
|------|-----------|
| `401` | Missing or invalid token |
| `403` | Caller is not the invited partner |
| `404` | Team (or league) not found |
| `409` | Team not `pending`; league not `open`/`upcoming`; either player already a member; capacity would exceed `max_players` |

---

### POST /leagues/{id}/teams/{teamId}/decline

**Auth:** Required; caller must be the invited partner.

**Request body:** None.

Sets the team `declined` (transactionally guarded — a team the partner has already
accepted cannot be declined) and notifies the captain. Nothing to free: pending teams
consume no capacity.

**Response (`200`, LeagueTeam)** with `"status": "declined"`.

Errors: `403` not the partner · `404` team not found · `409` team not `pending`.

---

### DELETE /leagues/{id}/teams/{teamId}

**Auth:** Required; caller must be the team's captain. Only `pending` teams can be
cancelled.

**Response (`200`, LeagueTeam)** with `"status": "cancelled"`.

Errors: `403` not the captain · `404` team not found · `409` team not `pending`.

---

### GET /leagues/{id}/teams

**Auth:** Required.

**Query parameters:**
- `mine` (bool, default `false`) — when `true`, returns only teams where the caller is
  captain or partner. Without an explicit `status`, defaults to actionable statuses
  (`pending` + `active`) — this is the "outstanding invites on app launch" surface.
- `status` (optional: `pending|active|declined|cancelled`) — explicit status filter.

Without `mine=true` the caller must be a league member and gets all teams (optionally
status-filtered).

**Response (`200`):**

```json
{
  "league_id": "padel-doubles-open-2026",
  "teams": [ { "team_id": "…", "status": "pending", "captain_uid": "…",
               "partner_uid": "…", "member_uids": ["…", "…"], "name": "…",
               "created_at": "…", "accepted_at": null, "rating_avg": null,
               "division_id": null } ]
}
```

Errors: `401` · `403` (non-member without `mine=true`) · `404` league not found.

---

### GET /players

**Auth:** Required.

Player search for the doubles partner picker. **Prefix** match (case-insensitive) on the
user's name — not substring search.

**Query parameters:**
- `search` (required, min length 1) — name prefix.
- `sport` (optional: `tennis|padel|pickleball`) — when given, each result includes the
  player's `pts` for that sport.
- `limit` (optional, 1–20, default 10).

The calling user is excluded from results.

**Response (`200`):**

```json
{
  "players": [
    { "uid": "user_elena", "display_name": "Elena", "profile_url": null, "pts": 1380 }
  ]
}
```

Errors: `401` · `422` missing/empty `search`, out-of-range `limit`, or invalid `sport`.

---

### POST /leagues/{id}/kickoff

**Auth:** Required; league owner, admin member, or global admin.

**Request body:** None.

Behavior:
- Valid only for `open` leagues; success transitions `open → dividing → active` and stamps
  `dividedAt`.
- Sorts active members by `users/{uid}.rankings.{sport}.pts` descending; missing ranking data
  counts as `0`.
- Creates division docs under `leagues/{id}/divisions` and sets each member's `divisionId` only
  when unset.
- Division count is `1` for fewer than 5 active members, otherwise `round(N / targetSize)`.
  Default `targetSize` is `6`.
- **Doubles leagues:** the seeding unit is the **team**, never the individual — and
  `divisionConfig.targetSize` (and the `<5 → 1 division` floor) count teams, not players:
  `targetSize: 6` means 6 teams (12 players) per division. Team rating is the integer mean
  of the two partners' `rankings.{sport}.pts`; teams are sorted by that average and split
  into divisions, so teammates always land in the same division.
  The `divisionId` is stamped on the team doc **and** both member docs. Division
  `current_players` counts players (2 × teams), consistent with league capacity. A
  doubles league with no `active` teams gets `409` ("no active teams") and reverts to
  `open`; `pending` invites do not count.
- Re-running after success is idempotent and returns existing divisions with
  `already_kicked_off: true`.

**Response (`200`):**

```json
{
  "league_id": "league_abc",
  "division_count": 2,
  "division_ids": ["div-1", "div-2"],
  "divisions": [
    {
      "division_id": "div-1",
      "name": "Division 1",
      "ordinal": 1,
      "rating_range": {"min": 1350, "max": 1800},
      "current_players": 6,
      "status": "active"
    }
  ],
  "already_kicked_off": false
}
```

**Key error codes:**

| Code | Condition |
|------|-----------|
| `401` | Missing or invalid token |
| `403` | Caller is not a league admin/owner/global admin |
| `404` | League not found |
| `409` | League is not open and not already kicked off, or has no active members |

---

## Known Limitations and Deferred Fields

1. **`POST /matches/{id}/verify-score` — dispute resolution:** When the second call disagrees the
   match moves to `disputed`, but there is **no dispute-resolution API endpoint at MVP** — a
   deliberate scope cut (OPS-DISPUTE-1): disputes are rare in the controlled Athens beta and an
   authenticated admin mutation endpoint is out of launch scope. Operators resolve disputes by
   writing Firestore directly using the tested manual procedure in
   [`docs/operations/runbook.md`](../operations/runbook.md) §7 ("Disputed Matches — Resolution
   Runbook"): either **void** the match (`status="cancelled"` + release each participant to
   `DISCOVERY`) or **adjudicate** a winner by reopening for confirmation and reusing the audited
   scoring path. Revisit post-beta if dispute volume warrants automation.

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

9. **`PATCH /me/clubhouse/profile` — avatar cannot be cleared:** `avatar_url` uses `null`/omission
   to mean "not provided", so there is no way to clear an existing avatar through this endpoint —
   only replace it with a new https URL. Clearing an avatar is deferred. A display-name change is
   eventually consistent across denormalized name caches (no synchronous fan-out); see the
   `PATCH /me/clubhouse/profile` contract for the exact caches affected.
