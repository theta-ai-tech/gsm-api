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

## `POST /me`

### Purpose
Create a new user profile on first onboarding. Called by the iOS onboarding wizard after
the user authenticates with Firebase.

### Auth
Required (`Authorization: Bearer <Firebase ID token>`).

### Behavior
- Derives `registrationTier` server-side from the supplied `levels` per sport using the
  `beginner→amateur / intermediate→intermediate / advanced→advanced / pro→competitive` mapping.
  The client cannot set `registrationTier` directly.
- Sets initial `pts` to `tier_config.get_floor(registrationTier)` per sport.
- Sets `playTab.state` to `DISCOVERY`.
- If `email` is present in the Firebase token, it is used; otherwise the `email` field
  in the request body is required.
- Returns `409` if a profile for `uid` already exists (idempotency guard).

### Request body
```json
{
  "name": "Alex",
  "email": "alex@example.com",
  "sports": ["padel", "tennis"],
  "levels": {"padel": "intermediate", "tennis": "beginner"},
  "area": 101,
  "profile_url": "https://example.com/avatar.png"
}
```

### Example call
```bash
curl -s -X POST \
  -H "Authorization: Bearer $ID_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Alex","sports":["padel"],"levels":{"padel":"intermediate"},"area":101}' \
  http://localhost:8000/me
```

### Example success response (`201`)
```json
{
  "uid": "user_abc123",
  "name": "Alex",
  "email": "alex@example.com",
  "profile_url": null,
  "is_pro": false,
  "rankings": {
    "padel": {"sport": "padel", "pts": 2000, "tier": "intermediate", "registration_tier": "intermediate"},
    "tennis": null,
    "pickleball": null
  },
  "preferences": {
    "area": 101,
    "levels": {"padel": "intermediate", "tennis": null, "pickleball": null},
    "sports": ["padel"],
    "feed_opt_out": false
  },
  "leagues_active": [],
  "leagues_completed": [],
  "upcoming_matches": [],
  "completed_matches": [],
  "journal_recent": [],
  "cursors": null,
  "north_star_goal": null
}
```

### Common error responses
- `401` missing/invalid token
- `409` profile already exists for this uid
- `422` email not in token and not in request body; or required field missing; or declared sport has no level

---

## `POST /me/device-tokens`

### Purpose
Register the caller's push notification device token so the backend can deliver push
notifications. Called by the iOS/Android client on login and on token rotation.

### Auth
Required (`Authorization: Bearer <Firebase ID token>`). A user may only manage their own
tokens — the token is always associated with the authenticated `uid`.

### Behavior
- Idempotent upsert into the user's `deviceTokens` array. If the token already exists, its
  `lastSeenAt` is refreshed instead of inserting a duplicate.
- New tokens are stored with `token`, `platform`, `createdAt`, and `lastSeenAt`.
- `app_version` (alias `appVersion`) is accepted for forward compatibility but is not yet
  persisted.
- Returns `404` if no user document exists for the authenticated `uid`.

### Request body
```json
{
  "token": "fcm_or_apns_token_string",
  "platform": "ios",
  "app_version": "1.4.0"
}
```
- `token` (required, non-empty string)
- `platform` (required, one of `ios` | `android`)
- `app_version` (optional; `appVersion` alias also accepted)

### Example call
```bash
curl -s -X POST \
  -H "Authorization: Bearer $ID_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"token":"tok_abc","platform":"ios","app_version":"1.4.0"}' \
  http://localhost:8000/me/device-tokens
```

### Example success response (`204`)
No content.

### Common error responses
- `401` missing/invalid token
- `404` no user profile exists for the authenticated uid
- `422` empty token or invalid platform value

---

## `DELETE /me/device-tokens`

### Purpose
Unregister the caller's push token on logout or token rotation.

### Auth
Required (`Authorization: Bearer <Firebase ID token>`). Only the authenticated user's own
tokens are affected.

### Behavior
- Removes the matching token from the user's `deviceTokens` array.
- No-op (still `204`) if the token is not present.

### Request body
```json
{
  "token": "fcm_or_apns_token_string"
}
```
- `token` (required, non-empty string)

### Example call
```bash
curl -s -X DELETE \
  -H "Authorization: Bearer $ID_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"token":"tok_abc"}' \
  http://localhost:8000/me/device-tokens
```

### Example success response (`204`)
No content.

### Common error responses
- `401` missing/invalid token
- `422` empty token

---

## `DELETE /me/account`

### Purpose
Permanently delete the caller's account (App Store in-app deletion requirement). Uses
**anonymize-in-place**: the user is removed from Firebase Auth and all their private data
is deleted, but the user document is tombstoned rather than cascade-deleted so other
players' match histories keep rendering.

### Auth
Required (`Authorization: Bearer <Firebase ID token>`). Only the authenticated caller's own
account is affected — there is no target `uid` parameter.

### Behavior
Data erasure runs **first**, identity destruction **last**, so a mid-flow failure leaves the
caller's token valid and the request safely retryable (every step is idempotent); the Auth
user is only deleted once erasure has completed.
1. **Own private data** — hard-deletes `users/{uid}/journalEntries` and
   `users/{uid}/pointHistory`; device tokens are dropped (push stops immediately).
2. **Tombstone** — overwrites `users/{uid}` keeping only `uid` and `rankings`, setting
   `name = "Deleted Player"`, `profileUrl = null`, `isDeleted = true`, `deletedAt = now`.
   All PII (email, phone, preferences, deviceTokens) is stripped.
3. **Identity** — deletes the Firebase Auth user. This is the single destructive Auth
   operation: deleting the user invalidates refresh tokens and makes the next
   `verify_id_token(check_revoked=True)` fail with `UserNotFoundError`, so a subsequent call
   with the old token is rejected. Refresh tokens are **not** revoked separately — a revoke
   that succeeded before a failed delete would sign the caller out while leaving the Auth user
   (and its PII) intact with no retry path. An already-deleted Auth user is tolerated
   (idempotent).

**No cascade:** match documents, opponents' point history, scouting, ticker and leaderboard
rows referencing the uid are left untouched. Opponents' rivalry/scouting/profile reads
against the deleted uid still return `200` rendering "Deleted Player". Tombstoned users drop
out of leaderboards on the next scheduled recompute.

User-facing deletion statement: *"Your account, profile, journal, goals, and personal data
(email, phone, devices) are permanently deleted. Your past match results remain in other
players' records but are no longer linked to your name."*

### Request body
None.

### Example call
```bash
curl -s -X DELETE \
  -H "Authorization: Bearer $ID_TOKEN" \
  http://localhost:8000/me/account
```

### Example success response (`204`)
No content.

### Common error responses
- `401` missing/invalid token

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
      "display_name": "Ignatios",
      "wins": 5,
      "losses": 1,
      "tier_ring": null
    },
    {
      "rank": 2,
      "uid": "user_sam",
      "display_name": "Sam",
      "wins": 3,
      "losses": 2,
      "tier_ring": null
    }
  ]
}
```

### Notes
- `display_name` is the value stored in the member doc at join time (from the Firebase token `name` claim). Falls back to `uid` if no display name was available when the user joined.
- `tier_ring` is always `null` for MVP.
- **Doubles leagues (`format: doubles`): a row is a team, not a player.** Entries carry
  `team_id` and `member_uids`; `display_name` is the team name ("Captain / Partner") and
  `uid` is the captain uid (stable row key). Team wins/losses are the captain's member
  stats — partners share identical league participation. Singles rows return
  `team_id: null` / `member_uids: null`. The same shape applies to division-scoped
  standings (teams filtered by their `divisionId`).

### Common error responses
- `401` missing/invalid token
- `403` caller is not a league member
- `404` league not found

---

## `POST /leagues/{league_id}/join`

### Purpose
Self-serve join flow. Branches on the league's `format`:
- **singles** (default when the field is absent): adds the authenticated user as a `player`
  member. No request body required — identical to the pre-doubles behavior.
- **doubles**: creates a **pending team invite** with a registered partner. Nobody becomes a
  member and no capacity is consumed until the partner accepts
  (`POST /leagues/{id}/teams/{teamId}/accept`).

iOS must branch on the returned `format` field of the league (browse card / detail), not on
the sport.

### Auth
Required (Firebase Bearer token).

### Path parameters
- `league_id` — string identifier of the league

### Request body
- Singles league: none (empty body or `{}`).
- Doubles league (required): `{"partner_uid": "<registered uid>"}` — find partners via
  `GET /players?search=`.

### Example call — singles (unchanged)
```bash
curl -s -X POST \
  -H "Authorization: Bearer $ID_TOKEN" \
  http://localhost:8000/leagues/padel-local-2025/join
```

### Example success response — singles (`201`, LeagueMember)
```json
{
  "uid": "user_ignatios",
  "role": "player",
  "status": "active",
  "joined_at": "2026-05-27T10:00:00+00:00",
  "stats": null,
  "display_name": "Ignatios",
  "division_id": null,
  "team_id": null,
  "partner_uid": null
}
```

### Example call — doubles team invite
```bash
curl -s -X POST \
  -H "Authorization: Bearer $ID_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"partner_uid": "user_helen"}' \
  http://localhost:8000/leagues/padel-doubles-open-2026/join
```

### Example success response — doubles (`201`, LeagueTeam)
```json
{
  "team_id": "aUt0GeNeRaTeD",
  "status": "pending",
  "captain_uid": "user_ignatios",
  "partner_uid": "user_helen",
  "member_uids": ["user_ignatios", "user_helen"],
  "name": "Ignatios / Helen",
  "created_at": "2026-06-10T15:00:00+00:00",
  "accepted_at": null,
  "rating_avg": null,
  "division_id": null
}
```

### Behavior
- **Singles** — checks performed transactionally:
  1. League must exist.
  2. League status must be `open` or `upcoming`.
  3. Caller must not already be a member.
  4. League must not be at full capacity (`currentPlayers >= maxPlayers`, if both are set).
  On success: creates `leagues/{leagueId}/members/{uid}` doc and increments `currentPlayers`
  on the league doc in one Firestore transaction.
- **Doubles** — pre-checks + transaction:
  1. League must exist, be `format: doubles`, and be `open` or `upcoming`.
  2. `partner_uid` must be present, registered, and not the caller.
  3. Neither caller nor partner already a member, nor in another `pending`/`active` team in
     this league (one team per user per league).
  On success: creates `leagues/{leagueId}/teams/{teamId}` with status `pending` and sends a
  `league_team_invite` push notification to the partner. **No member docs, no capacity
  change** — those happen on accept.

### Common error responses
- `400` `partner_uid` sent to a singles league; missing `partner_uid` on a doubles league; partner is the caller
- `401` missing/invalid token
- `404` league not found; partner uid not registered
- `409` caller/partner already a member; caller/partner already in a pending/active team; league not open/upcoming; league at full capacity

---

## `POST /leagues/{league_id}/teams/{team_id}/accept`

### Purpose
The invited partner accepts a pending doubles team. This is the moment the team becomes real:
both players become league members and capacity is consumed.

### Auth
Required. Caller must be the team's `partner_uid` (the invited player) — `403` otherwise.

### Behavior (single transaction)
- Re-checks: team still `pending`; league still `open`/`upcoming`; neither player already a
  member; capacity `currentPlayers + 2 <= maxPlayers` (when both set) — a doubles team
  consumes **2 player slots**. Exact fit succeeds; overflow gets `409`.
- Writes: team → `active` (+ `acceptedAt`); creates **both** member docs (each with `uid`,
  `teamId`, cross-linked `partnerUid`); `currentPlayers += 2`.
- Captain receives a `league_team_invite_accepted` push notification.

### Example call
```bash
curl -s -X POST \
  -H "Authorization: Bearer $ID_TOKEN" \
  http://localhost:8000/leagues/padel-doubles-open-2026/teams/team-elena-fotis/accept
```

### Response
`200` with the `LeagueTeam` (`"status": "active"`, `accepted_at` set).

### Common error responses
- `401` missing/invalid token · `403` caller is not the invited partner · `404` team not found
- `409` team not pending; league not open/upcoming; either player already a member; full capacity

---

## `POST /leagues/{league_id}/teams/{team_id}/decline`

### Purpose
The invited partner declines a pending team invite. Transactionally guarded — an invite the
partner has already accepted cannot be declined afterwards.

### Auth
Required. Caller must be the team's `partner_uid` — `403` otherwise.

### Response
`200` with the `LeagueTeam` (`"status": "declined"`). Captain receives a
`league_team_invite_declined` notification. Pending teams consume no capacity, so nothing is
freed.

### Common error responses
`401` · `403` not the partner · `404` team not found · `409` team not pending

---

## `DELETE /leagues/{league_id}/teams/{team_id}`

### Purpose
The captain cancels their own pending invite (e.g. picked the wrong partner).

### Auth
Required. Caller must be the team's `captain_uid` — `403` otherwise. Only `pending` teams can
be cancelled (`409` otherwise).

### Response
`200` with the `LeagueTeam` (`"status": "cancelled"`).

---

## `GET /leagues/{league_id}/teams`

### Purpose
List a league's doubles teams. With `mine=true`, the caller's own teams/invites — the surface
an app uses on launch to show outstanding invites (alongside the push notification).

### Auth
Required. Without `mine=true` the caller must be a league member.

### Query parameters
- `mine` (bool, default `false`) — only teams where the caller is captain or partner. Without
  an explicit `status`, defaults to actionable statuses (`pending` + `active`).
- `status` — optional explicit filter: `pending|active|declined|cancelled`.

### Example call
```bash
curl -s \
  -H "Authorization: Bearer $ID_TOKEN" \
  "http://localhost:8000/leagues/padel-doubles-open-2026/teams?mine=true"
```

### Example response (`200`)
```json
{
  "league_id": "padel-doubles-open-2026",
  "teams": [
    {
      "team_id": "team-elena-fotis",
      "status": "pending",
      "captain_uid": "user_elena",
      "partner_uid": "user_fotis",
      "member_uids": ["user_elena", "user_fotis"],
      "name": "Elena / Fotis",
      "created_at": "2026-06-10T15:00:00+00:00",
      "accepted_at": null,
      "rating_avg": null,
      "division_id": null
    }
  ]
}
```

### Common error responses
`401` · `403` non-member without `mine=true` · `404` league not found

---

## `GET /players`

### Purpose
Registered-player search for the doubles partner picker. Case-insensitive **prefix** match on
the player's name (backed by the indexed `nameLower` field — not substring search).

### Auth
Required. The calling user is excluded from results.

### Query parameters
- `search` — required name prefix (min length 1)
- `sport` — optional (`tennis|padel|pickleball`); when given, results include the player's
  `pts` for that sport
- `limit` — optional, 1–20, default 10

### Example call
```bash
curl -s \
  -H "Authorization: Bearer $ID_TOKEN" \
  "http://localhost:8000/players?search=el&sport=padel"
```

### Example response (`200`)
```json
{
  "players": [
    { "uid": "user_elena", "display_name": "Elena", "profile_url": null, "pts": 1380 }
  ]
}
```

### Common error responses
- `401` missing/invalid token
- `422` missing/empty `search`, out-of-range `limit`, invalid `sport`

### Notes
- Prefix-only: `search=len` will NOT match "Elena". Matching is on the lowercased name.
- Existing users seeded before this feature need the `nameLower` backfill (see
  `docs/data/data-dictionary.md`); new registrations write it automatically.

---

## `POST /leagues/{league_id}/kickoff`

### Purpose
Admin-only kickoff flow for League Divisions. Converts an `open` league from one flat member
pool into deterministic division metadata and stamps each active member with a `divisionId`.

### Auth
Required. The caller must be the league owner, an admin member, or a global admin.

### Behavior
- Accepts no request body.
- Transitions the league `open → dividing → active` and stamps `dividedAt`.
- Sorts active members by `users/{uid}.rankings.{sport}.pts` descending; missing profile/ranking
  data counts as `0`.
- Creates `leagues/{league_id}/divisions/{divisionId}` documents named `div-1`, `div-2`, etc.
  The highest-ranked players are assigned to `div-1`.
- Uses `divisionConfig.targetSize` when present, otherwise the default target size is `6`.
  Leagues with fewer than 5 active members stay in one division; otherwise the division count is
  `round(member_count / targetSize)`.
- Member documents are updated only when `divisionId` is unset.
- **Doubles leagues (`format: doubles`):** the seeding unit is the **team** — and so is
  `divisionConfig.targetSize` and the fewer-than-5 single-division floor: `targetSize: 6`
  means 6 teams (12 players) per division, and a doubles league with fewer than 5 active
  teams stays in one division. Author `divisionConfig` in team units for doubles leagues.
  Team rating is the integer mean of the partners' `rankings.{sport}.pts`; teams sort by
  that average and split into divisions, so teammates always share a division. `divisionId` is stamped on the
  team doc and both member docs. Division `currentPlayers` counts players (2 × teams). A
  doubles league with no `active` teams returns `409` ("no active teams") and reverts to
  `open` — `pending` invites don't count.
- Re-running kickoff after a successful kickoff is a documented no-op: the endpoint returns the
  existing divisions with `already_kicked_off: true` and does not create duplicates.

### Example call
```bash
curl -s -X POST \
  -H "Authorization: Bearer $ID_TOKEN" \
  http://localhost:8000/leagues/padel-divisions-open-2026/kickoff
```

### Example response
```json
{
  "league_id": "padel-divisions-open-2026",
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
    },
    {
      "division_id": "div-2",
      "name": "Division 2",
      "ordinal": 2,
      "rating_range": {"min": 0, "max": 1260},
      "current_players": 5,
      "status": "active"
    }
  ],
  "already_kicked_off": false
}
```

### Common error responses
- `401` missing/invalid token
- `403` authenticated user is not a league admin/owner/global admin
- `404` league does not exist
- `409` league is not open and has not already completed kickoff, or it has no active members

---

## `GET /leagues/{league_id}/divisions`

### Purpose
List the divisions created by league kickoff, ordered by `ordinal`.

### Auth
Required (Firebase Bearer token). Caller must be a member of the league.

### Path parameters
- `league_id` — string identifier of the league

### Example call
```bash
curl -s \
  -H "Authorization: Bearer $ID_TOKEN" \
  http://localhost:8000/leagues/padel-divisions-open-2026/divisions
```

### Example success response (`200`)
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
    },
    {
      "division_id": "div-2",
      "name": "Division 2",
      "ordinal": 2,
      "rating_range": {"min": 0, "max": 1260},
      "current_players": 5,
      "status": "active"
    }
  ]
}
```

### Behavior
- Reads `leagues/{league_id}/divisions` directly; there is no per-division members subcollection.
- Pre-kickoff leagues return `409` with detail `league not yet divided`.

### Common error responses
- `401` missing/invalid token
- `403` caller is not a league member
- `404` league not found
- `409` league has not completed division kickoff

---

## `GET /leagues/{league_id}/divisions/{division_id}/standings`

### Purpose
Returns the current standings for one league division. Uses the same dense-ranking rules as league
standings, but only includes members whose member doc has the requested `divisionId`.

### Auth
Required (Firebase Bearer token). Caller must be a member of the league.

### Path parameters
- `league_id` — string identifier of the league
- `division_id` — string identifier of the division

### Example call
```bash
curl -s \
  -H "Authorization: Bearer $ID_TOKEN" \
  http://localhost:8000/leagues/padel-divisions-open-2026/divisions/div-1/standings
```

### Example success response (`200`)
```json
{
  "league_id": "padel-divisions-open-2026",
  "standings": [
    {
      "rank": 1,
      "uid": "user_ignatios",
      "display_name": "Ignatios",
      "wins": 5,
      "losses": 1,
      "tier_ring": null
    },
    {
      "rank": 2,
      "uid": "user_sam",
      "display_name": "Sam",
      "wins": 3,
      "losses": 2,
      "tier_ring": null
    }
  ]
}
```

### Common error responses
- `401` missing/invalid token
- `403` caller is not a league member
- `404` league or division not found
- `409` league has not completed division kickoff

---

## `GET /leagues/{league_id}/divisions/{division_id}/matches`

### Purpose
List upcoming or completed matches for one league division. Requires league membership.

### Auth
Required (Firebase Bearer token). Caller must be a member of the league.

### Path parameters
- `league_id` — string identifier of the league
- `division_id` — string identifier of the division

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
  "http://localhost:8000/leagues/padel-divisions-open-2026/divisions/div-1/matches?type=upcoming&limit=5"
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
      "league_id": "padel-divisions-open-2026",
      "division_id": "div-1",
      "court_id": null,
      "participants": [
        {"uid": "user_ignatios", "team": null, "role": "player", "result": null},
        {"uid": "user_sam", "team": null, "role": "player", "result": null}
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
- `type=upcoming`: filters by `leagueId`, `divisionId`, `status=scheduled`; ordered by `scheduledAt` ASC.
- `type=completed`: filters by `leagueId`, `divisionId`, `status=completed`; ordered by `finishedAt` DESC.
- Cursor tokens are opaque (base64-encoded). Treat `next_cursor` as opaque — do not parse it.
- Returns `200` with `matches: []` when no matches — never `404`.

### Common error responses
- `400` invalid cursor token
- `401` missing/invalid token
- `403` caller is not a league member
- `404` league or division not found
- `409` league has not completed division kickoff

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
        {"uid": "user_ignatios", "team": null, "role": "player", "result": null},
        {"uid": "user_sam", "team": null, "role": "player", "result": null}
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

See `docs/design/tab1-play-payloads.md` for full payload examples per mode.

---

## `GET /me/discovery`

### Purpose
Returns the full browsable list of active play intents regardless of the caller's current play state. Unlike the `DISCOVERY` payload embedded in `GET /me/state` (only present when `mode == DISCOVERY`), this endpoint is always available — users in `BROADCAST_ACTIVE`, `MATCH_SCHEDULED`, or any other state can still browse intents. iOS replaces its `LivePlayService.fetchDiscoveryFeed()` mock with this endpoint.

### Auth
Required (`Authorization: Bearer <Firebase ID token>`).

### Behavior
- Calls `broadcasts.list_active(sport, match_type)` to fetch up to 25 active broadcasts ordered by `createdAt` desc.
- Excludes the caller's own broadcast.
- Enriches each card with:
  - `level`: resolved from the owner's `preferences.levels.<sport>` (one Firestore read per unique owner, deduped).
  - `areaName`: resolved from `config/regions` mapping for `need_court` broadcasts with a `location.area`. Falls back gracefully to `null` when the region config doc is absent.
  - `venueRef`: included only for `have_court` broadcasts; `null` for `need_court`.

### Example call
```bash
curl -s \
  -H "Authorization: Bearer $ID_TOKEN" \
  "http://localhost:8000/me/discovery?sport=padel"
```

### Example response (`200`)
```json
{
  "serverTime": "2026-06-24T12:00:00Z",
  "activeClubsNearby": 1,
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

### Common error responses
- `401` missing/invalid token
- `422` invalid `sport` or `match_type` query parameter value

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
  "message": "Up for a game?",
  "leagueId": null
}
```

Field rules:
- `leagueId`: optional string or `null`; when set, tags the offer and resulting match as a league
  match; the referenced league must have status `active`, and both parties must be active members.

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


## `GET /venues/search`

### Purpose
Free-text venue search combining curated Firestore venues with Google Places Autocomplete.
Returns up to 5 results for use in the "set location" flow during broadcast creation.

### Auth
Required (Firebase Bearer ID token).

### Query parameters
| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `q` | string (1–200 chars) | Yes | Search query (venue name or location text) |
| `lat` | float (-90 to 90) | No | Caller's latitude for location bias |
| `lng` | float (-180 to 180) | No | Caller's longitude for location bias |

### Behavior
- Curated venues from the `venues` Firestore collection are prefix-matched on `name` and returned first.
- Google Places Autocomplete is called with `q` (and optional lat/lng bias).
- Results are merged: curated first, then Google Places, deduped by `placeId`.
- Returns at most 5 results total.
- Curated venues have a `venueId` populated; Google-only results have `venueId: null`.

### Example call
```bash
curl -s \
  -H "Authorization: Bearer $ID_TOKEN" \
  "http://localhost:8000/venues/search?q=padel+glyfada&lat=37.87&lng=23.75"
```

### Example response (`200`)
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

### Common error responses
- `401` missing/invalid token
- `422` validation error (q empty, lat/lng out of range)
- `502` upstream Google Places error
- `503` Google Places API key not configured (emulator / dev environments)

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


## `POST /matches/{match_id}/verify-score`

### Purpose
Submit or confirm a match result. This single endpoint drives both the initial result
submission and the opponent's confirmation step.

**Note on naming:** earlier planning docs referred to these flows as `POST /matches/{id}/result`
(first call) and `POST /matches/{id}/confirm` (second call). They are implemented as a single
endpoint that handles both based on the current match status.

### Auth
Required. The caller must be a participant in the match.

### Two-call flow
| Call | Match status before | Match status after | Scoring written? |
|------|--------------------|--------------------|-----------------|
| 1st (submit result) | `scheduled` | `pending_confirmation` | No |
| 2nd (agree) | `pending_confirmation` | `completed` | Yes |
| 2nd (disagree) | `pending_confirmation` | `disputed` | No |

### Request body

**Singles match:**
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

**Doubles match:**
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

Rules:
- Provide exactly one of `winner_uid` (singles) or `winner_team` (doubles `"A"` or `"B"`).
- `score` is optional but strongly recommended.
- `walkover: true` skips scoring — all deltas are 0, `score` may be null.

### Example response — first call (`200`, match → `pending_confirmation`)
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

### Example response — second call, agreed (`200`, match → `completed`)
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

### Doubles response example — completed
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
  "scoring": { "..." : "see singles example for full shape" }
}
```

### Common error responses
- `401` missing/invalid token
- `403` caller is not a participant in this match
- `404` match not found
- `409` invalid state transition (e.g. match already completed, walkover on non-scheduled match)
- `500` server misconfiguration (missing tier config)

---


## `GET /me/clubhouse/profile`

### Purpose
Return the caller's Athlete Card & Resume for the Clubhouse (Profile) tab: identity
(`display_name`, `avatar_url`) plus an aggregated `resume` (total matches/wins, leagues
completed, and per-sport ranking cards).

### Auth
Required (`Authorization: Bearer <Firebase ID token>`). Only the caller's own profile is
returned — there is no target `uid` parameter.

### Behavior
Reads `users/{uid}` and builds the resume from the denormalized `rankings`,
`completedMatches`, and `leaguesCompleted` caches. Counts come from capped caches
(`completedMatches` max 10, `leaguesCompleted` max 20).

### Request body
None.

### Example call
```bash
curl -s -H "Authorization: Bearer $ID_TOKEN" \
  http://localhost:8000/me/clubhouse/profile
```

### Example success response (`200`)
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

### Common error responses
- `401` missing/invalid token
- `404` user not found

---


## `PATCH /me/clubhouse/profile`

### Purpose
Partial update of the caller's editable profile fields — `display_name`, `avatar_url`,
`area`, `levels` — from the Profile tab's Edit-profile screen. Returns the refreshed
`ClubhouseProfileResponse` so the client re-renders without a second `GET`.

### Auth
Required (`Authorization: Bearer <Firebase ID token>`). Only the caller's own profile is
modified.

### Behavior
- **Partial:** any subset of the four fields may be sent. A field omitted (or `null`) is left
  unchanged — `avatar_url` cannot be cleared through this endpoint (send a new URL only).
- **At least one field is required:** an empty body returns `400`.
- **`display_name`:** whitespace-stripped; max length 100. Writing it also updates the
  `nameLower` search index so player prefix search resolves the new name.
- **`avatar_url`:** must be a valid **https** URL (`http://` is rejected).
- **`area`:** validated against `config/regions`; an area not present in the mapping returns
  `422`.
- **`levels`:** merged **per-sport** — sending `{"padel": "intermediate"}` updates only padel
  and leaves other sports' levels intact. Level values must be a valid `LevelEnum`
  (`beginner`/`intermediate`/`advanced`/`pro`); sport keys must be `tennis`/`padel`/`pickleball`.
- **Never touches rankings:** editing `levels` does not modify `rankings.pts`, `rankings.tier`,
  or any `rankings.*` field.
- **No synchronous fan-out:** a name change is eventually consistent across denormalized name
  caches (historical matches, ticker, leaderboard, offers, discovery). New writes pick up the
  new name immediately; the scheduled leaderboard recompute refreshes leaderboard names.
- Unknown top-level fields are rejected with `422` (strict model).

### Request body
```json
{
  "display_name": "New Name",
  "avatar_url": "https://cdn.example.com/a.png",
  "area": 202,
  "levels": {"tennis": "advanced"}
}
```

### Example call
```bash
curl -s -X PATCH \
  -H "Authorization: Bearer $ID_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"display_name": "New Name", "area": 202}' \
  http://localhost:8000/me/clubhouse/profile
```

### Example success response (`200`)
Same shape as `GET /me/clubhouse/profile`, reflecting the applied changes.

### Common error responses
- `400` empty body (no fields provided)
- `401` missing/invalid token
- `404` user not found (including a tombstoned/deleted account)
- `422` unknown `area`, non-https `avatar_url`, invalid level/sport enum, unknown field, or
  empty `display_name`

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
