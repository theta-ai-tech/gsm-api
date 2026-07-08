# Data Dictionary

## Overview
This document defines the canonical Firestore data dictionary for GSM. It records collection
structures, field conventions, and enum domains used across the API and emulator seed data.
It is versioned in repo and should be updated alongside schema/query changes.

## Conventions
- Firestore field naming: `camelCase` in documents and subdocuments.
- API/Pydantic fields: `snake_case` in models; mappers translate to/from Firestore `camelCase`.
- Timestamps: stored as Firestore timestamp values; all timestamps are UTC and timezone-aware.
  Pydantic models normalize naive datetimes to UTC where needed.
- IDs:
  - Primary IDs live in document IDs (e.g., `matches/{matchId}`, `leagues/{leagueId}`).
  - Summary lists use explicit `*Id` fields (e.g., `leagueId`, `matchId`) to reference documents.
- Canonical vs Cache:
  - Canonical fields are the source of truth and should be written by the owning aggregate.
  - Cache fields are denormalized summaries for fast reads (e.g., `users/{uid}.leaguesActive`).
  - Cache lists should be capped and treated as derived data.
- Pagination:
  - Cursor-based pagination using `startAfter` on ordered fields plus document ID as a tiebreaker.
  - Example: `orderBy scheduledAt ASC, __name__ ASC` then `startAfter(last_scheduledAt, last_id)`.

## Enums
Values below match the C1 enums in code.

### sport
- Firestore representation: string
- API/Pydantic representation: string enum
- Allowed values: `tennis`, `padel`, `pickleball`

### level
- Firestore representation: string
- API/Pydantic representation: string enum
- Allowed values: `beginner`, `intermediate`, `advanced`, `pro`

### matchStatus
- Firestore representation: string
- API/Pydantic representation: string enum
- Allowed values: `scheduled`, `pending_confirmation`, `completed`, `disputed`, `cancelled`

### leagueStatus
- Firestore representation: string
- API/Pydantic representation: string enum
- Allowed values: `active`, `completed`, `dividing`, `upcoming`, `open`
  - `open`: registration is open, play has not yet started (distinct from `upcoming` which may be pre-registration)
  - `dividing`: transient kickoff state while a league's flat member pool is being assigned to divisions

### leagueFormat
- Firestore representation: string
- API/Pydantic representation: string enum
- Allowed values: `singles`, `doubles`
  - Missing/`null` on a league doc reads as `singles` (backward compatible — every pre-doubles league keeps individual-member behavior). Never derived from the sport.

### leagueTeamStatus
- Firestore representation: string
- API/Pydantic representation: string enum
- Allowed values: `pending`, `active`, `declined`, `cancelled`
  - `pending`: captain invited a partner; no member docs, no capacity consumed
  - `active`: partner accepted; both member docs exist, 2 player slots consumed
  - `declined` / `cancelled`: terminal; set by the partner / captain respectively

### journalVisibility
- Firestore representation: string
- API/Pydantic representation: string enum
- Allowed values: `private`, `friends`

### playTabState
- Firestore representation: string (UPPER_CASE)
- API/Pydantic representation: string enum
- Allowed values: `DISCOVERY`, `BROADCAST_ACTIVE`, `OUTGOING_OFFER_PENDING`, `INCOMING_OFFER_PENDING`, `MATCH_SCHEDULED`, `POST_MATCH_LOG_AVAILABLE`, `POST_MATCH_WAITING_OPPONENT`, `POST_MATCH_CONFIRM_REQUIRED`, `MATCH_DISPUTED`

### broadcastStatus
- Firestore representation: string
- API/Pydantic representation: string enum
- Allowed values: `active`, `expired`, `cancelled`, `matched`

### availability
- Firestore representation: string
- API/Pydantic representation: string enum
- Allowed values: `today`, `tomorrow`, `weekend`

### courtStatus
- Firestore representation: string
- API/Pydantic representation: string enum
- Allowed values: `have_court`, `need_court`

### offerStatus
- Firestore representation: string
- API/Pydantic representation: string enum
- Allowed values: `pending`, `accepted`, `declined`, `expired`, `cancelled`

### tier
- Firestore representation: string
- API/Pydantic representation: string enum
- Allowed values: `amateur`, `intermediate`, `advanced`, `competitive`

### tickerEventType
- Firestore representation: string
- API/Pydantic representation: string enum
- Allowed values: `upset`, `personal_best`, `win_streak`, `tier_crossed`

## Collection: users
Path: `users/{uid}`

Ownership: user-owned document; self-only updates as policy.

Purpose: canonical user profile data with denormalized summaries for fast reads.

### Public vs Private projection
- Public profile must not expose `email`, `phone`, or `preferences`.
- Private profile (self) includes those fields plus cached summary lists and cursors.

### Cache fields (denormalized summaries)
These fields are denormalized summaries for fast reads. Treat as cache with capped lengths.
- `leaguesActive[]`: `{leagueId, name, sport, status, role, divisionId?}` (cache, cap <= 20)
- `leaguesCompleted[]`: `{leagueId, name, sport, status, role, divisionId?}` (cache, cap <= 20)
- `upcomingMatches[]`: `{matchId, sport, scheduledAt, leagueId?, courtId?, opponents[]}` (cache, cap <= 10)
- `completedMatches[]`: `{matchId, sport, finishedAt, result?, scoreText?, leagueId?}` (cache, cap <= 10)
- `journalRecent[]`: `{entryId, createdAt, title, matchId?, sport?, entryType?}` (cache, cap <= 10)
- `cursors`: `{upcomingMatches?, completedMatches?, journal?}` (cache; last-seen pagination cursors)

### Fields: users/{uid}
| Field | Type | Required | Enum | Canonical|Cache | Index | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| uid | string | required | — | canonical | — | Stored in doc; should match document ID. |
| name | string | required | — | canonical | — | Public. Set to `"Deleted Player"` on account deletion. |
| nameLower | string | optional | — | cache | index=range | Lowercased `name` for `GET /players?search=` prefix queries. Written at registration; existing users need a one-off backfill (users without it are invisible to player search). Must be rewritten if a name-edit path is ever added. |
| profileUrl | string (url) | optional | — | canonical | — | Public. Nulled on account deletion. |
| email | string | optional | — | canonical | — | Private. |
| emailLower | string | optional | — | cache | index=filter | Lowercased/stripped `email` — case-insensitive match key for the partner-invite registered-user guard (`find_uid_by_email`). Written at registration; `email` itself preserves user-entered casing and must not be used as a match key. |
| phone | string | optional | — | canonical | — | Private. |
| rankings | map | optional | — | canonical | — | Public; per-sport rankings. |
| rankings.tennis | map | optional | sport | canonical | — | `{sport, pts, globalRanking, tier?, registrationTier?, lastUpdated?}`. |
| rankings.padel | map | optional | sport | canonical | — | `{sport, pts, globalRanking, tier?, registrationTier?, lastUpdated?}`. |
| rankings.pickleball | map | optional | sport | canonical | — | `{sport, pts, globalRanking, tier?, registrationTier?, lastUpdated?}`. |
| rankings.*.sport | string | required | sport | canonical | — | Enum value. |
| rankings.*.pts | number | optional | — | canonical | — | Ranking points. |
| rankings.*.globalRanking | number | optional | — | canonical | — | Optional global rank. |
| rankings.*.tier | string | optional | tier | canonical | — | Current tier derived from pts + config/tiers. Cached. |
| rankings.*.registrationTier | string | optional | tier | canonical | — | Tier at signup. Determines point floor. Immutable. |
| rankings.*.lastUpdated | timestamp | optional | — | canonical | — | When this ranking was last modified. |
| rankings.*.personalBest | number | optional | — | canonical | — | Highest pts ever achieved in this sport. Null for legacy users. |
| rankings.*.currentStreak | number | optional | — | canonical | — | Current consecutive win count. Defaults to 0. |
| rankings.*.bestStreak | number | optional | — | canonical | — | All-time best consecutive win count. Defaults to 0. |
| preferences | map | optional | — | canonical | — | Private. |
| preferences.area | number | optional | — | canonical | — | Private; area code. |
| preferences.levels | map | optional | level | canonical | — | Per-sport level preferences. |
| preferences.levels.tennis | string | optional | level | canonical | — | Enum value. |
| preferences.levels.padel | string | optional | level | canonical | — | Enum value. |
| preferences.levels.pickleball | string | optional | level | canonical | — | Enum value. |
| preferences.sports | array<string> | optional | sport | canonical | — | Private; preferred sports. |
| preferences.feedOptOut | boolean | optional | — | canonical | false | Whether the user has opted out of appearing in the Local Pulse feed. Defaults to false (users appear in feed by default). |
| preferences.defaultGeo | map | optional | — | canonical | — | Home-base coordinates for "nearby me" discovery. |
| preferences.defaultGeo.lat | number | required | — | canonical | — | Latitude (WGS84). |
| preferences.defaultGeo.lng | number | required | — | canonical | — | Longitude (WGS84). |
| preferences.defaultRadiusKm | number | optional | — | canonical | — | Default search radius in km (default 15). |
| leaguesActive | array<map> | optional | — | cache | — | Active league summaries (cap <= 20), including optional `divisionId`. |
| leaguesCompleted | array<map> | optional | — | cache | — | Completed league summaries (cap <= 20), including optional `divisionId`. |
| upcomingMatches | array<map> | optional | — | cache | — | Upcoming match summaries (cap <= 10). |
| completedMatches | array<map> | optional | — | cache | — | Completed match summaries (cap <= 10). |
| journalRecent | array<map> | optional | — | cache | — | Recent journal summaries (cap <= 10). |
| cursors | map | optional | — | cache | — | Cursor bundle for pagination. |
| playTab | map | optional | — | cache | — | Tab 1 (Play) state cache. Managed by API transactions; triggers as backstops. |
| playTab.state | string | optional | playTabState | cache | — | Current `PlayTabStateEnum` value. Default: `DISCOVERY`. |
| playTab.activeBroadcastId | string | optional | — | cache | — | Doc ID of the user's active broadcast (null when none). |
| playTab.activeMatchId | string | optional | — | cache | — | Doc ID of the user's current match (scheduled through post-match). |
| playTab.activeOutgoingOfferId | string | optional | — | cache | — | Doc ID of the user's pending outgoing offer (null when none). |
| playTab.pendingIncomingOfferIds | array&lt;string&gt; | optional | — | cache | — | Doc IDs of pending incoming offers (empty when none). |
| playTab.updatedAt | timestamp | optional | — | cache | — | Last state transition timestamp. |
| skillDna | map | optional | — | cache | — | Per-sport radar chart cache. Keys are sport strings (e.g. `tennis`). |
| skillDna.{sport} | map | optional | — | cache | — | Axis data for one sport. |
| skillDna.{sport}.serve | map | optional | — | cache | — | `{positive, negative, score}` for the Serve axis. |
| skillDna.{sport}.power | map | optional | — | cache | — | `{positive, negative, score}` for the Power axis. |
| skillDna.{sport}.net_play | map | optional | — | cache | — | `{positive, negative, score}` for the Net Play axis. |
| skillDna.{sport}.stamina | map | optional | — | cache | — | `{positive, negative, score}` for the Stamina axis. |
| skillDna.{sport}.mental | map | optional | — | cache | — | `{positive, negative, score}` for the Mental axis. |
| skillDna.{sport}.*.positive | number | required | — | cache | — | Count of positive reflections for this axis. |
| skillDna.{sport}.*.negative | number | required | — | cache | — | Count of negative reflections for this axis. |
| skillDna.{sport}.*.score | number | required | — | cache | — | `round(positive / (positive + negative) * 100)`; shown only when positive + negative >= 3. |
| skillDna.{sport}.totalReflections | number | required | — | cache | — | Total reflection count for this sport. |
| skillDna.{sport}.lastUpdated | timestamp | optional | — | cache | — | When this sport's DNA was last recalculated. |
| deviceTokens | array&lt;map&gt; | optional | — | canonical | — | FCM/APNs device tokens for push delivery. Private; never on public profile. Shape: `[{token, platform, createdAt, lastSeenAt}]`. |
| deviceTokens[].token | string | required | — | canonical | — | FCM registration token string. Dedupe key. |
| deviceTokens[].platform | string | required | platform | canonical | — | `ios` or `android`. |
| deviceTokens[].createdAt | timestamp | required | — | canonical | — | When the token was first registered. |
| deviceTokens[].lastSeenAt | timestamp | required | — | canonical | — | Refreshed on every re-registration (token rotation). |
| isDeleted | boolean | optional | — | canonical | false | Tombstone flag set by `DELETE /me/account`. When true the doc is anonymized (see Account deletion policy). Excluded from leaderboard recompute. |
| deletedAt | timestamp | optional | — | canonical | — | When the account was deleted (tombstoned). Set alongside `isDeleted = true`. |

### Account deletion policy (anonymize-in-place)
`DELETE /me/account` (ACCT-1) does **not** cascade-delete shared data. Data erasure runs first (while the caller's token is still valid, so a mid-flow failure is idempotently retryable); the Auth identity is destroyed last. It:
- Hard-deletes the caller's own `journalEntries` and `pointHistory` subcollections and drops `deviceTokens`.
- Overwrites `users/{uid}` keeping only `uid` and `rankings`, setting `name = "Deleted Player"`, `profileUrl = null`, `isDeleted = true`, `deletedAt = now`, and stripping all PII (`email`, `phone`, `preferences`, cache fields, `skillDna`, `deviceTokens`).
- Deletes the Firebase Auth user (single destructive Auth op; `delete_user` already drops refresh tokens, so they are **not** revoked separately).

`rankings` is retained so opponents' head-to-head, point-history, rivalry, scouting, ticker and leaderboard references keep resolving and render as "Deleted Player". Match documents and opponents' point-history rows are never mutated. Tombstoned users drop out of leaderboards on the next scheduled recompute (they are skipped in `extract_users_by_region_sport`).

## Subcollection: users/{uid}/journalEntries
Path: `users/{uid}/journalEntries/{entryId}`

Ownership: owner-only (self).

Visibility: `journalVisibility` enum governs access; enforced at API layer.

Ordering: `createdAt` DESC with cursor-based pagination using `startAfter`.

### Fields: users/{uid}/journalEntries/{entryId}
| Field | Type | Required | Enum | Canonical|Cache | Index | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| title | string | required | — | canonical | — | Title text. |
| body | string | required | — | canonical | — | Entry body. |
| tags | array<string> | optional | — | canonical | — | Freeform tags. |
| createdAt | timestamp | required | — | canonical | index=order-by | UTC timestamp. |
| matchId | string | optional | — | canonical | — | Optional match reference. |
| sport | string | optional | sport | canonical | — | Optional sport enum. |
| visibility | string | required | journalVisibility | canonical | — | Access scope. |
| entryType | string | required | match/training | canonical | — | Entry mode (`match` or `training`). |
| durationMinutes | number | optional | — | canonical | — | Required when `entryType=training`. |
| trainingFocus | array<string> | optional | training focus tags | canonical | — | Training focus pills. |
| reflection | map | optional | — | canonical | — | Post-match reflection payload. |
| reflection.reflectionVersion | string | optional | — | canonical | — | Tag taxonomy version (e.g. `v1`). |
| scoreText | string | optional | — | canonical | — | Denormalised match score text. |
| result | string | optional | W/L/D | canonical | — | Denormalised result from match. |
| clientRequestId | string | optional | — | canonical | — | Client idempotency key (scoped by uid). |
| isDeleted | boolean | required | — | canonical | — | Soft-delete marker (default `false`). |
| deletedAt | timestamp | optional | — | canonical | — | Soft-delete timestamp. |

## Field Table Template
| Field | Type | Required | Enum | Canonical|Cache | Index | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| participantUids | array<string> | required | — | canonical | index=array-contains | Used for user-scoped match queries. |

## Examples
Minimal examples (timestamps shown as ISO8601 UTC strings).

### users/{uid} (public projection)
```json
{
  "uid": "user_123",
  "name": "Alex",
  "profileUrl": "https://example.com/avatar.png",
  "rankings": {
    "tennis": {"sport": "tennis", "pts": 820, "globalRanking": 340}
  },
  "leaguesActive": [
    {"leagueId": "league_1", "name": "Local Ladder", "sport": "padel", "status": "active"}
  ],
  "leaguesCompleted": []
}
```

### users/{uid} (private projection)
```json
{
  "uid": "user_123",
  "name": "Alex",
  "email": "alex@example.com",
  "phone": "+301111111111",
  "profileUrl": "https://example.com/avatar.png",
  "rankings": {
    "padel": {"sport": "padel", "pts": 980, "globalRanking": 120}
  },
  "preferences": {
    "area": 101,
    "levels": {"padel": "advanced"},
    "sports": ["padel", "tennis"],
    "feedOptOut": false
  },
  "leaguesActive": [
    {"leagueId": "league_1", "name": "Local Ladder", "sport": "padel", "status": "active"}
  ],
  "leaguesCompleted": [
    {"leagueId": "league_2", "name": "Series 2024", "sport": "tennis", "status": "completed"}
  ],
  "upcomingMatches": [
    {
      "matchId": "match_1",
      "sport": "padel",
      "scheduledAt": "2030-01-10T10:00:00Z",
      "leagueId": "league_1",
      "opponents": [{"uid": "user_456", "name": "Sam"}]
    }
  ],
  "completedMatches": [
    {
      "matchId": "match_2",
      "sport": "padel",
      "finishedAt": "2020-01-20T20:15:00Z",
      "result": "W",
      "scoreText": "6-4, 7-5",
      "leagueId": "league_1"
    }
  ],
  "journalRecent": [
    {"entryId": "journal_1", "createdAt": "2020-01-21T09:00:00Z", "title": "Padel win"}
  ],
  "cursors": {"upcomingMatches": null, "completedMatches": null, "journal": null},
  "playTab": {
    "state": "BROADCAST_ACTIVE",
    "activeBroadcastId": "broadcast_abc",
    "activeMatchId": null,
    "activeOutgoingOfferId": null,
    "pendingIncomingOfferIds": ["offer_1", "offer_2"],
    "updatedAt": "2026-02-03T08:00:00Z"
  }
}
```

### users/{uid}/journalEntries/{entryId}
```json
{
  "title": "Padel win reflections",
  "body": "Worked on volleys; need to improve serve consistency.",
  "tags": ["padel", "volley", "serve"],
  "createdAt": "2020-01-21T09:00:00Z",
  "matchId": "match_1",
  "sport": "padel",
  "visibility": "private"
}
```

### users/{uid} cache snippets
```json
{
  "upcomingMatches": [
    {
      "matchId": "match_123",
      "sport": "tennis",
      "scheduledAt": "2030-03-05T18:30:00Z",
      "leagueId": "league_spring",
      "courtId": "court_4",
      "opponents": [{"uid": "user_456", "name": "Jamie"}]
    }
  ],
  "completedMatches": [
    {
      "matchId": "match_456",
      "sport": "tennis",
      "finishedAt": "2030-02-15T20:05:00Z",
      "result": "W",
      "scoreText": "6-4 6-3",
      "leagueId": "league_winter"
    }
  ],
  "upcomingMatchIds": ["match_123"],
  "recentCompletedMatchIds": ["match_456"]
}
```

## Collection: matches
Path: `matches/{matchId}`

Purpose: scheduled and completed match records; supports user and league match queries.

### Fields: matches/{matchId}
| Field | Type | Required | Enum | Canonical|Cache | Index | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| sport | string | required | sport | canonical | — | Sport for the match. |
| status | string | required | matchStatus | canonical | index=filter | Match lifecycle state. |
| participantUids | array<string> | required | — | canonical | index=array-contains | Query driver for user-scoped match lists. |
| participantPair | string | optional | — | canonical | index=equality | Sorted pair key "uid_a_uid_b" for head-to-head queries. Null for matches with ≠ 2 participants. |
| participants | array<map> | required | — | canonical | — | Structured participant data. |
| participants[].uid | string | required | — | canonical | — | Participant UID. |
| participants[].team | number | optional | — | canonical | — | Team number for doubles, null for singles. |
| participants[].role | string | optional | — | canonical | — | Participant role (defaults to player). |
| participants[].result | string | optional | — | canonical | — | Per-participant result (W/L/D). |
| leagueId | string | optional | — | canonical | index=filter | Optional league reference. |
| divisionId | string | optional | — | canonical | index=filter | Optional division reference for division-scoped fixtures. Not used for score/stat routing. |
| courtId | string | optional | — | canonical | — | Optional court reference. |
| scheduledAt | timestamp | optional | — | canonical | index=order-by | Required for scheduled/pending/completed. |
| finishedAt | timestamp | optional | — | canonical | index=order-by | Required for completed. |
| resultByUser | map | optional | — | canonical | — | Map of uid -> W/L/D. |
| score | map | optional | — | canonical | — | Structured score object. |
| score.sets | array<map> | optional | — | canonical | — | List of set scores. |
| score.sets[].p1Games | number | optional | — | canonical | — | Games for player/team 1. |
| score.sets[].p2Games | number | optional | — | canonical | — | Games for player/team 2. |
| score.sets[].tiebreakScore | string | optional | — | canonical | — | Optional tiebreak string. |
| score.winnerUid | string | optional | — | canonical | — | Winner UID, if known. |
| score.retired | boolean | optional | — | canonical | — | True if match ended by retirement. |

### Status transitions
| From | To | Trigger |
| --- | --- | --- |
| scheduled | completed | Participants submit/confirm result. |
| scheduled | cancelled | Organizer or league admin cancels. |
| pending_confirmation | completed | Opponent confirms result. |
| pending_confirmation | disputed | Opponent disputes submitted result. |
| completed | disputed | Result challenged after completion. |

### matches/{matchId} (scheduled)
```json
{
  "sport": "padel",
  "status": "scheduled",
  "scheduledAt": "2030-03-01T19:00:00Z",
  "leagueId": "league_abc",
  "participantUids": ["user_1", "user_2"],
  "participantPair": "user_1_user_2",
  "participants": [
    {"uid": "user_1", "team": 1, "role": "player"},
    {"uid": "user_2", "team": 2, "role": "player"}
  ]
}
```

### matches/{matchId} (completed)
```json
{
  "sport": "padel",
  "status": "completed",
  "scheduledAt": "2030-02-25T19:00:00Z",
  "finishedAt": "2030-02-25T20:05:00Z",
  "leagueId": "league_abc",
  "participantUids": ["user_1", "user_2"],
  "participantPair": "user_1_user_2",
  "participants": [
    {"uid": "user_1", "team": 1, "role": "player", "result": "W"},
    {"uid": "user_2", "team": 2, "role": "player", "result": "L"}
  ],
  "resultByUser": {"user_1": "W", "user_2": "L"},
  "score": {
    "sets": [
      {"p1Games": 6, "p2Games": 4},
      {"p1Games": 6, "p2Games": 3}
    ],
    "winnerUid": "user_1",
    "retired": false
  }
}
```

### scheduledAt / finishedAt semantics
- `scheduledAt` is present for `scheduled`, `pending_confirmation`, and `completed` matches.
- `finishedAt` is required for `completed` (and `disputed` if the match has a result timestamp).
- All timestamps are stored in UTC.

### Required composite indexes
Indexes are defined in `firestore.indexes.json` and required for C3 queries:
- Upcoming matches by user: `participantUids` (array-contains), `status` (ASC), `scheduledAt` (ASC)
- Completed matches by user: `participantUids` (array-contains), `status` (ASC), `finishedAt` (DESC)
- Upcoming matches by league: `leagueId` (ASC), `status` (ASC), `scheduledAt` (ASC)
- Completed matches by league: `leagueId` (ASC), `status` (ASC), `finishedAt` (DESC)
- Upcoming matches by league division: `leagueId` (ASC), `divisionId` (ASC), `status` (ASC), `scheduledAt` (ASC)
- Completed matches by league division: `leagueId` (ASC), `divisionId` (ASC), `status` (ASC), `finishedAt` (DESC)
- Head-to-head history: `participantPair` (ASC), `finishedAt` (DESC)

### matches/{matchId}
```json
{
  "sport": "padel",
  "status": "completed",
  "scheduledAt": "2020-01-20T18:00:00Z",
  "finishedAt": "2020-01-20T20:15:00Z",
  "leagueId": "league_1",
  "participants": [
    {"uid": "user_123", "role": "player", "team": 1, "result": "W"},
    {"uid": "user_456", "role": "player", "team": 2, "result": "L"}
  ],
  "participantUids": ["user_123", "user_456"],
  "resultByUser": {"user_123": "W", "user_456": "L"},
  "score": {
    "sets": [
      {"p1Games": 6, "p2Games": 4},
      {"p1Games": 7, "p2Games": 5, "tiebreakScore": "7-5"}
    ],
    "winnerUid": "user_123",
    "retired": false
  }
}
```

## Collection: leagues
Path: `leagues/{leagueId}`

Purpose: league metadata, configuration, and lifecycle.

### Fields: leagues/{leagueId}
| Field | Type | Required | Enum | Canonical|Cache | Index | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| name | string | required | — | canonical | — | League display name. |
| sport | string | required | sport | canonical | — | Sport enum. |
| season | string | optional | — | canonical | — | Season label (e.g., "Autumn 2025"). |
| status | string | required | leagueStatus | canonical | index=filter | League lifecycle state. |
| format | string | optional | leagueFormat | canonical | — | `singles` (default when absent) or `doubles`. Drives the join flow, kickoff seeding unit, and standings row shape. |
| ownerUid | string | required | — | canonical | — | League owner uid. |
| region | string | optional | — | canonical | index=filter | Named region (e.g. "athens"). Matches region format used by leaderboards. Used by PL-L1 browser filter (`?region=athens`). |
| maxPlayers | number | optional | — | canonical | — | Hard cap on total players. Used by PL-L1 card ("8/12 spots"). |
| currentPlayers | number | optional | — | cache | — | Denormalized count of active members. Updated on join/leave. Used by PL-L1 progress bar. |
| startDate | timestamp | optional | — | canonical | — | When play begins. Displayed on PL-L1 card ("Starts May 1"). |
| endDate | timestamp | optional | — | canonical | — | When the season ends. Displayed on PL-L2 detail view. |
| dividedAt | timestamp | optional | — | canonical | — | Set by `POST /leagues/{leagueId}/kickoff` when division assignment completes. Missing before kickoff and on legacy leagues. |
| tier | string | optional | — | canonical | — | Display-only tier label for MVP (e.g. "intermediate"). No join enforcement for MVP. |
| divisionConfig | map | optional | — | canonical | — | League Divisions configuration. Missing on legacy/non-divided leagues. |
| divisionConfig.targetSize | number | optional | — | canonical | — | Target **seeding units** per division: players for singles leagues, **teams** for doubles (`6` = 6 teams = 12 players). Defaults to `6` (`DIVISION_TARGET_SIZE`). |
| divisionConfig.maxDivisions | number | optional | — | canonical | — | Optional cap for division count. Null means no explicit cap. |
| meta | map | optional | — | canonical | — | Free-form metadata. |

## Subcollection: leagues/{leagueId}/divisions
Path: `leagues/{leagueId}/divisions/{divisionId}`

Purpose: metadata-only League Divisions records created at kickoff. Members remain in the flat
`leagues/{leagueId}/members/{uid}` pool and reference their assigned division by `divisionId`;
there is no per-division members subcollection.

### Fields: leagues/{leagueId}/divisions/{divisionId}
| Field | Type | Required | Enum | Canonical|Cache | Index | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| name | string | required | — | canonical | — | Division display name (e.g., "Division 1"). |
| ordinal | number | required | — | canonical | index=order-by | Stable display/query order; `DivisionsRepo.list_for_league` orders by this field. |
| ratingRange | map | required | — | canonical | — | Descriptive rating band computed at kickoff; not an enforcement rule. |
| ratingRange.min | number | required | — | canonical | — | Lowest player rating in the division at kickoff. |
| ratingRange.max | number | required | — | canonical | — | Highest player rating in the division at kickoff. |
| currentPlayers | number | required | — | cache | — | Count of members assigned to this division. |
| status | string | required | leagueStatus | canonical | — | Uses `active` for MVP division metadata. |

## Subcollection: leagues/{leagueId}/members
Path: `leagues/{leagueId}/members/{uid}`

Purpose: membership record for a user in a league.

### Roles
`player`, `admin`, `captain`

### Membership status
`active`, `left`, `banned`

### Fields: leagues/{leagueId}/members/{uid}
| Field | Type | Required | Enum | Canonical|Cache | Index | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| role | string | required | leagueRole | canonical | — | Role in league. |
| status | string | required | leagueMemberStatus | canonical | — | Membership state. |
| joinedAt | timestamp | required | — | canonical | index=order-by | When the user joined. |
| stats | map | optional | — | canonical | — | Optional per-user league stats. |
| divisionId | string | optional | — | canonical | index=filter | Nullable until kickoff. Points to `leagues/{leagueId}/divisions/{divisionId}` after assignment. |
| teamId | string | optional | — | canonical | — | Doubles only. Points to `leagues/{leagueId}/teams/{teamId}`; written when the team is accepted. |
| partnerUid | string | optional | — | canonical | — | Doubles only. The other member of the team (cross-linked). |

### Common queries
- List members of a league ordered by `joinedAt` ASC.
- Check membership existence for a user: read `leagues/{leagueId}/members/{uid}`.
- User profiles cache league summaries in `users/{uid}.leaguesActive` / `leaguesCompleted`.

### Required composite indexes
Indexes are defined in `firestore.indexes.json` and required for browse queries:
- League browse (primary): `region` (ASC), `sport` (ASC), `status` (ASC)
- League browse + sort by start date: `region` (ASC), `sport` (ASC), `status` (ASC), `startDate` (ASC)

⚠️ **Deployment note:** These indexes must be deployed via `firebase deploy --only firestore:indexes` before `GET /leagues` (LG-7) is live in production. Index creation can take several minutes on large collections.

### leagues/{leagueId}
```json
{
  "name": "Local Padel Ladder 2025",
  "sport": "padel",
  "season": "Autumn 2025",
  "status": "open",
  "ownerUid": "user_123",
  "region": "athens",
  "maxPlayers": 12,
  "currentPlayers": 4,
  "divisionConfig": {
    "targetSize": 6,
    "maxDivisions": null
  },
  "startDate": "2026-06-01T00:00:00Z",
  "endDate": "2026-08-31T00:00:00Z",
  "tier": "intermediate",
  "meta": {}
}
```

### leagues/{leagueId}/divisions/{divisionId}
```json
{
  "name": "Division 1",
  "ordinal": 1,
  "ratingRange": {
    "min": 980,
    "max": 1420
  },
  "currentPlayers": 6,
  "status": "active"
}
```

### leagues/{leagueId}/members/{uid}
```json
{
  "uid": "user_123",
  "role": "player",
  "status": "active",
  "joinedAt": "2024-10-01T12:00:00Z",
  "stats": {},
  "divisionId": null,
  "teamId": "team-abc",
  "partnerUid": "user_456"
}
```

## Subcollection: leagues/{leagueId}/teams
Path: `leagues/{leagueId}/teams/{teamId}`

Purpose: doubles team unit for `format: doubles` leagues. Created in `pending` status by
`POST /leagues/{id}/join {partner_uid}`; becomes `active` when the invited partner accepts
(both member docs are created and `currentPlayers` +2 in the same transaction). Pending
teams consume no capacity. One `pending`/`active` team per user per league.

**Unregistered-partner variant** (`POST /leagues/{id}/join {partner_invite}`): the team is
created `active` immediately (no accept gate) and consumes 2 capacity slots at invite time.
`partnerUid` is `null`; `partnerPlaceholderUid` and `partnerInvite` hold the placeholder slot.
Both member docs (captain + placeholder) exist from the start. On registration with the
invited email the placeholder is backfilled: `partnerUid` is set, `partnerInvite` /
`partnerPlaceholderUid` are deleted, the placeholder member doc is replaced by the real one.

### Fields: leagues/{leagueId}/teams/{teamId}
| Field | Type | Required | Enum | Canonical|Cache | Index | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| status | string | required | leagueTeamStatus | canonical | index=filter | Team lifecycle. |
| captainUid | string | required | — | canonical | — | The inviter. |
| partnerUid | string | optional | — | canonical | — | The registered partner. `null` for an unclaimed placeholder team (see `partnerPlaceholderUid`). |
| partnerPlaceholderUid | string | optional | — | canonical | — | Present only for an unregistered-partner team: `"invite:" + sha256(normalized_email)[:24]`. Removed on claim. |
| partnerInvite | map | optional | — | canonical | — | Present only for an unregistered-partner team: `{name, emailNormalized, phone, invitedAt}`. `emailNormalized` is stored server-side only and **never** returned by the API. Removed on claim. |
| memberUids | array<string> | required | — | canonical | index=array-contains | Both uids (placeholder uid for an unclaimed team); used by "my teams/invites" queries. |
| name | string | optional | — | cache | — | Display name, "Captain / Partner". |
| createdAt | timestamp | required | — | canonical | — | Invite creation time. |
| acceptedAt | timestamp | optional | — | canonical | — | Set on accept (or invite time for the immediate-active placeholder team). |
| ratingAvg | number | optional | — | cache | — | Integer mean of partners' per-sport pts; the doubles division-seeding rating. Placeholder members are skipped (captain-only mean until claimed). |
| divisionId | string | optional | — | canonical | — | Stamped at kickoff (also stamped on both member docs). |

### leagues/{leagueId}/teams/{teamId}
```json
{
  "status": "active",
  "captainUid": "user_123",
  "partnerUid": "user_456",
  "memberUids": ["user_123", "user_456"],
  "name": "Alice / Bob",
  "createdAt": "2026-06-02T09:00:00Z",
  "acceptedAt": "2026-06-02T18:30:00Z",
  "divisionId": null
}
```

### Common queries
- My teams/invites in a league: `memberUids array_contains {uid}` (status filtered in app code — avoids a composite index).
- League teams by status: `status == "pending"` etc.

## Collection: partnerInvites
Path: `partnerInvites/{placeholderUid}__{leagueId}`

Purpose: top-level lookup index that maps an unregistered partner's normalized email to the
placeholder team slot it belongs to, so registration can backfill it. Created in the same
transaction as an unregistered-partner team (`POST /leagues/{id}/join {partner_invite}`). The
deterministic doc id (`{placeholderUid}__{leagueId}`) also enforces one invite per email per
league. **Consume-and-delete:** the doc (and its stored email) is deleted the moment the invite
is claimed at registration. Unclaimed docs persist until a future cleanup job removes them.

### Fields: partnerInvites/{placeholderUid}__{leagueId}
| Field | Type | Required | Enum | Canonical|Cache | Index | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| emailNormalized | string | required | — | canonical | index=filter | Lowercased/stripped invite email — the durable match key. Queried at registration; never returned by the API. |
| leagueId | string | required | — | canonical | — | League the placeholder team belongs to. |
| teamId | string | required | — | canonical | — | Target `leagues/{leagueId}/teams/{teamId}`. |
| placeholderUid | string | required | — | canonical | — | `"invite:" + sha256(emailNormalized)[:24]`. |
| captainUid | string | required | — | canonical | — | Captain to notify on claim. |
| inviteName | string | optional | — | cache | — | Display name captured at invite time. |
| phone | string | optional | — | canonical | — | Display-only; not used as a match key. |
| createdAt | timestamp | required | — | canonical | — | Invite creation time. |

### Common queries
- Backfill on registration: `partnerInvites where emailNormalized == {email}` (single-field index).

## Collection: courts
Path: `courts/{courtId}`

Purpose: tennis/padel/pickleball court directory entries.

### Fields: courts/{courtId}
| Field | Type | Required | Enum | Canonical|Cache | Index | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| name | string | required | — | canonical | — | Court display name. |
| area | number | required | — | canonical | — | Area code/region id. |
| geo | map | required | — | canonical | — | WGS84 coordinates. |
| geo.lat | number | required | — | canonical | — | Latitude (WGS84). |
| geo.lng | number | required | — | canonical | — | Longitude (WGS84). |
| bookingUrl | string (url) | optional | — | canonical | — | Optional booking link. |

### courts/{courtId}
```json
{
  "name": "Central Court",
  "area": 101,
  "geo": {"lat": 37.9838, "lng": 23.7275},
  "bookingUrl": "https://example.com/courts/central"
}
```

## Collection: broadcasts
Path: `broadcasts/{broadcastId}`

Purpose: availability broadcasts created when a user taps "I'm Ready to Play". One active broadcast per user at a time. Offers queue against an active broadcast.

### Fields: broadcasts/{broadcastId}
| Field | Type | Required | Enum | Canonical|Cache | Index | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| ownerUid | string | required | — | canonical | index=filter | Broadcaster's UID. |
| sport | string | required | sport | canonical | index=filter | Sport for the broadcast. |
| availability | string | required | availability | canonical | — | `today` / `tomorrow` / `weekend`. |
| courtStatus | string | required | courtStatus | canonical | — | `have_court` / `need_court`. |
| courtLocation | string | optional | — | canonical | — | Free-text location (when courtStatus is `have_court`). |
| status | string | required | broadcastStatus | canonical | index=filter | `active` / `expired` / `cancelled` / `matched`. |
| expiresAt | timestamp | required | — | canonical | index=order-by | Hard cut-off TTL set by user. |
| createdAt | timestamp | required | — | canonical | — | When broadcast was created. |
| ownerName | string | required | — | cache | — | Denormalized from user profile for display. |
| ownerRanking | map | optional | — | cache | — | Denormalized `{sport, pts}` from user rankings. |
| location | map | required | — | canonical | — | Geographic scope; at least one of `area` or `geo` must be set. |
| location.area | number | optional | — | canonical | index=filter | Predefined area code (coarse filter). |
| location.geo | map | optional | — | canonical | — | Jittered WGS84 coordinates (privacy-safe). |
| location.geo.lat | number | required | — | canonical | — | Latitude. |
| location.geo.lng | number | required | — | canonical | — | Longitude. |
| location.radiusKm | number | optional | — | canonical | — | Search radius in km (default 15). Only meaningful when `geo` is set. |

### Required composite indexes
- Active broadcasts by area/sport: `status` (ASC), `location.area` (ASC), `sport` (ASC), `expiresAt` (ASC)
- Active broadcasts by owner: `ownerUid` (ASC), `status` (ASC)

### Status transitions
| From | To | Trigger |
| --- | --- | --- |
| active | expired | Broadcast TTL passes (freshness reconciliation or scheduled job). |
| active | cancelled | User cancels via DELETE /me/broadcast. |
| active | matched | An offer against this broadcast is accepted. |

### broadcasts/{broadcastId} (active)
```json
{
  "ownerUid": "user_123",
  "sport": "tennis",
  "availability": "today",
  "courtStatus": "have_court",
  "courtLocation": "Central Court, Athens",
  "status": "active",
  "expiresAt": "2026-02-03T16:00:00Z",
  "createdAt": "2026-02-03T08:00:00Z",
  "ownerName": "Alex",
  "ownerRanking": {"sport": "tennis", "pts": 1200},
  "location": {
    "area": 101,
    "geo": {"lat": 37.98, "lng": 23.73},
    "radiusKm": 10
  }
}
```

## Collection: offers
Path: `offers/{offerId}`

Purpose: match proposals (challenges) sent between users. An offer may target an active broadcast or be a direct challenge. Offers have a short TTL (e.g. 5 minutes) to drive urgency.

### Fields: offers/{offerId}
| Field | Type | Required | Enum | Canonical|Cache | Index | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| fromUid | string | required | — | canonical | index=filter | Sender UID. |
| toUid | string | required | — | canonical | index=filter | Recipient UID. |
| broadcastId | string | optional | — | canonical | — | If offer targets an active broadcast. |
| sport | string | required | sport | canonical | — | Sport for the proposed match. |
| proposedTime | timestamp | optional | — | canonical | — | Suggested match time. |
| courtLocation | string | optional | — | canonical | — | Proposed court location. |
| message | string | optional | — | canonical | — | Free-text message from sender. |
| status | string | required | offerStatus | canonical | index=filter | `pending` / `accepted` / `declined` / `expired` / `cancelled`. |
| expiresAt | timestamp | required | — | canonical | index=order-by | Auto-expiry timestamp. |
| createdAt | timestamp | required | — | canonical | index=order-by | When offer was created. |
| fromName | string | required | — | cache | — | Denormalized sender name. |
| fromRanking | map | optional | — | cache | — | Denormalized `{sport, pts}` from sender. |
| toName | string | required | — | cache | — | Denormalized recipient name. |
| toRanking | map | optional | — | cache | — | Denormalized `{sport, pts}` from recipient. |
| matchId | string | optional | — | canonical | — | Set when status transitions to `accepted`; references the created match. |
| leagueId | string | optional | — | canonical | — | When set, the offer is a league challenge; both sender + recipient must be ACTIVE members of the league. Propagated to the created match on acceptance. |

### Required composite indexes
- Pending offers by recipient: `toUid` (ASC), `status` (ASC), `createdAt` (ASC)
- Pending offers by sender: `fromUid` (ASC), `status` (ASC), `createdAt` (ASC)

### Status transitions
| From | To | Trigger |
| --- | --- | --- |
| pending | accepted | Recipient accepts via POST /me/offers/{id}/accept. |
| pending | declined | Recipient declines via POST /me/offers/{id}/decline. |
| pending | cancelled | Sender withdraws via POST /me/offers/{id}/cancel. |
| pending | expired | Offer TTL passes (freshness reconciliation). |

### offers/{offerId} (pending)
```json
{
  "fromUid": "user_456",
  "toUid": "user_123",
  "broadcastId": "broadcast_abc",
  "sport": "tennis",
  "proposedTime": "2026-02-03T18:00:00Z",
  "courtLocation": "Central Court, Athens",
  "message": "Up for a game?",
  "status": "pending",
  "expiresAt": "2026-02-03T10:05:00Z",
  "createdAt": "2026-02-03T10:00:00Z",
  "fromName": "Sam",
  "fromRanking": {"sport": "tennis", "pts": 1100},
  "toName": "Alex",
  "toRanking": {"sport": "tennis", "pts": 1200},
  "matchId": null
}
```

### offers/{offerId} (accepted)
```json
{
  "fromUid": "user_456",
  "toUid": "user_123",
  "broadcastId": "broadcast_abc",
  "sport": "tennis",
  "proposedTime": "2026-02-03T18:00:00Z",
  "courtLocation": "Central Court, Athens",
  "message": "Up for a game?",
  "status": "accepted",
  "expiresAt": "2026-02-03T10:05:00Z",
  "createdAt": "2026-02-03T10:00:00Z",
  "fromName": "Sam",
  "fromRanking": {"sport": "tennis", "pts": 1100},
  "toName": "Alex",
  "toRanking": {"sport": "tennis", "pts": 1200},
  "matchId": "match_789"
}
```

## Subcollection: users/{uid}/pointHistory
Path: `users/{uid}/pointHistory/{entryId}`

Ownership: owner-only (self); written by scoring engine / admin functions.

Purpose: time-series audit log of every point change for a user. Powers the Progression Graph in Tab 3.

See [`../operations/scoring.md`](../operations/scoring.md) for how `pts` and `delta` are computed.

Ordering: `sport` filter + `createdAt` DESC with cursor-based pagination.

### pointHistoryReason
- Firestore representation: string
- API/Pydantic representation: string enum
- Allowed values: `match_win`, `match_loss`, `admin_adjustment`, `tier_rebalance`

### Fields: users/{uid}/pointHistory/{entryId}
| Field | Type | Required | Enum | Canonical\|Cache | Index | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| sport | string | required | sport | canonical | index=filter | Sport for this event. |
| pts | number | required | — | canonical | — | Point total AFTER this event. |
| delta | number | required | — | canonical | — | Points gained (positive) or lost (negative). |
| reason | string | required | pointHistoryReason | canonical | — | Cause of the point change. |
| matchId | string | conditional | — | canonical | — | Match reference; null for non-match events. |
| opponentUid | string | conditional | — | canonical | — | Opponent UID; null for non-match events. |
| opponentPtsBefore | number | conditional | — | canonical | — | Opponent pts before the match. |
| leagueId | string | optional | — | canonical | — | League reference if league match. |
| createdAt | timestamp | required | — | canonical | index=order-by | When the event occurred (UTC). |
| tierBefore | string | optional | tier | canonical | — | Tier before this event. |
| tierAfter | string | optional | tier | canonical | — | Tier after this event. |

### Required composite indexes
- Point history by user/sport: `sport` (ASC), `createdAt` (DESC)

### users/{uid}/pointHistory/{entryId}
```json
{
  "sport": "tennis",
  "pts": 2250,
  "delta": 150,
  "reason": "match_win",
  "matchId": "match_789",
  "opponentUid": "user_456",
  "opponentPtsBefore": 3100,
  "leagueId": null,
  "createdAt": "2026-03-01T14:30:00Z",
  "tierBefore": "intermediate",
  "tierAfter": "intermediate"
}
```

## Document: config/tiers
Path: `config/tiers`

Purpose: tier threshold configuration. Defines point boundaries for player tiers, allowing rebalancing without code changes.

See [`../operations/scoring.md`](../operations/scoring.md) for how a player's tier is derived from
these thresholds and how tier differences drive the upset bonus and penalty.

### Enums: tier
- Firestore representation: string
- API/Pydantic representation: string enum
- Allowed values: `amateur`, `intermediate`, `advanced`, `competitive`

### Fields: config/tiers
| Field | Type | Required | Enum | Canonical|Cache | Index | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| thresholds | array<map> | required | — | canonical | — | Ordered list of tier definitions. |
| thresholds[].tier | string | required | tier | canonical | — | Tier enum key. |
| thresholds[].minPts | number | required | — | canonical | — | Inclusive lower bound. |
| thresholds[].maxPts | number | optional | — | canonical | — | Inclusive upper bound; `null` for open-ended top tier. |
| thresholds[].label | string | required | — | canonical | — | Display label for UI. |
| thresholds[].color | string | required | — | canonical | — | Hex color for UI. |
| version | number | required | — | canonical | — | Schema version for forward compatibility. |
| updatedAt | timestamp | required | — | canonical | — | Last update timestamp. |

### config/tiers
```json
{
  "thresholds": [
    {"tier": "amateur",      "minPts": 1000, "maxPts": 1999, "label": "Amateur",      "color": "#8B8B8B"},
    {"tier": "intermediate", "minPts": 2000, "maxPts": 2999, "label": "Intermediate", "color": "#00A3CC"},
    {"tier": "advanced",     "minPts": 3000, "maxPts": 3999, "label": "Advanced",     "color": "#BFFF00"},
    {"tier": "competitive",  "minPts": 4000, "maxPts": null, "label": "Competitive",  "color": "#FF6B35"}
  ],
  "version": 1,
  "updatedAt": "2026-01-01T00:00:00Z"
}
```

## Document: config/skillTaxonomy
Path: `config/skillTaxonomy`

Purpose: maps journal reflection tags to the 5 radar axes (Serve, Power, Net Play, Stamina, Mental).
Used by the Skill DNA aggregation to score each axis from `went_well` / `went_wrong` reflection tags.
Unknown tags (not in `tagMap`) are silently ignored during aggregation.

### Fields: config/skillTaxonomy
| Field | Type | Required | Enum | Canonical\|Cache | Index | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| axes | array<string> | required | — | canonical | — | Ordered list of radar axis keys. |
| tagMap | map<string,string> | required | — | canonical | — | Maps tag string → axis string. |
| version | number | required | — | canonical | — | Schema version for forward compatibility. |

### config/skillTaxonomy
```json
{
  "axes": ["serve", "power", "net_play", "stamina", "mental"],
  "tagMap": {
    "first_serve": "serve",
    "double_faults": "serve",
    "ace": "serve",
    "forehand_winner": "power",
    "backhand_winner": "power",
    "net_approach": "net_play",
    "volley": "net_play",
    "endurance": "stamina",
    "fitness": "stamina",
    "concentration": "mental",
    "composure": "mental",
    "tiebreak": "mental"
  },
  "version": 1
}
```

## Document: config/tierAverages
Path: `config/tierAverages`

Purpose: pre-computed average Skill DNA scores per tier and sport. Powers the "Show Next Level"
comparison mode on the radar chart. Recomputed by the D7 scheduled function.

### Fields: config/tierAverages
| Field | Type | Required | Enum | Canonical\|Cache | Index | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| {tier} | map | optional | tier | canonical | — | One key per tier that has users with Skill DNA. |
| {tier}.{sport} | map | optional | sport | canonical | — | One key per sport with data in that tier. |
| {tier}.{sport}.{axis} | number | optional | — | canonical | — | Average score (0-100) for the axis. |
| updatedAt | timestamp | required | — | canonical | — | Last recomputation timestamp (UTC). |

### config/tierAverages
```json
{
  "amateur": {
    "tennis": {"serve": 40, "power": 35, "net_play": 30, "stamina": 45, "mental": 38},
    "padel": {"serve": 38, "power": 32, "net_play": 42, "stamina": 40, "mental": 35}
  },
  "intermediate": {
    "tennis": {"serve": 58, "power": 52, "net_play": 48, "stamina": 60, "mental": 55}
  },
  "updatedAt": "2026-03-01T00:00:00Z"
}
```

## Document: config/regions
Path: `config/regions`

Purpose: maps area codes to named regions for leaderboard grouping. Each user has a `preferences.area` integer; this document translates those area codes into a region string used by the leaderboard system.

### Fields: config/regions
| Field | Type | Required | Enum | Canonical\|Cache | Index | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| mapping | map<string,string> | required | — | canonical | — | Keys are area codes (as strings); values are region names. |
| version | number | required | — | canonical | — | Schema version for forward compatibility. |

### config/regions
```json
{
  "mapping": {
    "101": "athens",
    "102": "athens",
    "201": "thessaloniki",
    "202": "thessaloniki",
    "303": "london"
  },
  "version": 1
}
```

## Collection: scouting
Path: `scouting/{uid}`

Purpose: aggregated community observations about each player. Crowd-sourced intelligence for scouting reports. Reports are fully anonymous — counts only, no reporter UIDs stored.

### Privacy Model
- Reports are fully anonymous: counts only, no reporter UIDs stored.
- Users see "7 players noted weak backhand" — never who reported it.

### Fields: scouting/{uid}
| Field | Type | Required | Enum | Canonical\|Cache | Index | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| uid | string | required | — | canonical | — | Scouted player UID; matches document ID. |
| {sport} | map | optional | sport | canonical | — | One key per sport with scouting data. |
| {sport}.weak | map | optional | — | canonical | — | Map of tag string to `{count, lastReported}`. |
| {sport}.strong | map | optional | — | canonical | — | Map of tag string to `{count, lastReported}`. |
| {sport}.weak.{tag}.count | number | required | — | canonical | — | Number of reports for this weakness tag. |
| {sport}.weak.{tag}.lastReported | timestamp | required | — | canonical | — | When this tag was last reported (UTC). |
| {sport}.strong.{tag}.count | number | required | — | canonical | — | Number of reports for this strength tag. |
| {sport}.strong.{tag}.lastReported | timestamp | required | — | canonical | — | When this tag was last reported (UTC). |
| {sport}.totalReports | number | required | — | canonical | — | Total report count across all tags for this sport. |
| {sport}.uniqueReporters | number | required | — | canonical | — | Distinct reporter count for this sport. |
| {sport}.lastUpdated | timestamp | optional | — | canonical | — | When this sport's scouting data was last updated (UTC). |

### scouting/{uid}
```json
{
  "uid": "user_bob",
  "tennis": {
    "weak": {
      "backhand": {"count": 7, "lastReported": "2026-03-01T10:00:00Z"},
      "stamina_set3": {"count": 3, "lastReported": "2026-02-28T15:00:00Z"}
    },
    "strong": {
      "first_serve": {"count": 5, "lastReported": "2026-03-01T09:00:00Z"}
    },
    "totalReports": 12,
    "uniqueReporters": 8,
    "lastUpdated": "2026-03-01T10:00:00Z"
  }
}
```

## Collection: leaderboards
Path: `leaderboards/{region}_{sport}`

Purpose: pre-computed regional top-N leaderboard snapshots. Each document contains the ranked entries and rising stars for one region+sport combination. Recomputed periodically by a scheduled function.

### Fields: leaderboards/{region}_{sport}
| Field | Type | Required | Enum | Canonical\|Cache | Index | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| region | string | required | — | canonical | index=filter | Region identifier (e.g. "athens"). |
| sport | string | required | sport | canonical | index=filter | Sport enum. |
| entries | array<map> | required | — | canonical | — | Top-N ranked players. |
| entries[].uid | string | required | — | canonical | — | Player UID. |
| entries[].name | string | required | — | canonical | — | Player display name. |
| entries[].pts | number | required | — | canonical | — | Current point total. |
| entries[].tier | string | optional | tier | canonical | — | Current tier. |
| entries[].rank | number | required | — | canonical | — | Position in leaderboard (1-based). |
| entries[].delta7d | number | optional | — | canonical | — | Point change over the last 7 days. |
| risingStars | array<map> | optional | — | canonical | — | Players with highest 7-day point gain. |
| risingStars[].uid | string | required | — | canonical | — | Player UID. |
| risingStars[].name | string | required | — | canonical | — | Player display name. |
| risingStars[].pts | number | required | — | canonical | — | Current point total. |
| risingStars[].delta7d | number | required | — | canonical | — | Point change over the last 7 days. |
| risingStars[].rank | number | required | — | canonical | — | Position in overall leaderboard. |
| lastUpdated | timestamp | optional | — | canonical | — | When this snapshot was last recomputed (UTC). |

### leaderboards/{region}_{sport}
```json
{
  "region": "athens",
  "sport": "tennis",
  "entries": [
    {"uid": "user_123", "name": "Alex", "pts": 3450, "tier": "advanced", "rank": 1, "delta7d": 250}
  ],
  "risingStars": [
    {"uid": "user_789", "name": "Dana", "pts": 2100, "delta7d": 400, "rank": 15}
  ],
  "lastUpdated": "2026-03-01T12:00:00Z"
}
```

## Collection: ticker
Path: `ticker/{auto}`

Purpose: notable events feed for a region (upsets, personal bests, win streaks, tier crossings). Documents are auto-ID and have a TTL (`expiresAt`) for natural expiry.

### Fields: ticker/{auto}
| Field | Type | Required | Enum | Canonical\|Cache | Index | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| type | string | required | tickerEventType | canonical | — | Event type: upset, personal_best, win_streak, tier_crossed. |
| sport | string | required | sport | canonical | index=filter | Sport enum. |
| region | string | required | — | canonical | index=filter | Region identifier (e.g. "athens"). |
| createdAt | timestamp | required | — | canonical | index=order | When the event was created (UTC). |
| expiresAt | timestamp | required | — | canonical | — | When the event should expire (UTC). |
| winnerUid | string | optional | — | canonical | — | UID of the upset winner (upset events only). |
| winnerName | string | optional | — | canonical | — | Display name of the upset winner (upset events only). |
| loserTier | string | optional | tier | canonical | — | Tier of the opponent beaten (upset events only). |
| delta | number | optional | — | canonical | — | Point delta (upset events only). |
| userUid | string | optional | — | canonical | — | Subject of the event (personal_best, win_streak, tier_crossed). |
| userName | string | optional | — | canonical | — | Display name of the subject (first + last initial). |
| newPts | number | optional | — | canonical | — | New personal best score (personal_best events only). |
| previousBest | number | optional | — | canonical | — | Previous personal best score (personal_best events only). |
| streak | number | optional | — | canonical | — | Consecutive win count (win_streak events only). |
| tierBefore | string | optional | tier | canonical | — | Tier before the transition (tier_crossed events only). |
| tierAfter | string | optional | tier | canonical | — | Tier after the transition (tier_crossed events only). |
| direction | string | optional | — | canonical | — | Tier transition direction: "up" or "down" (tier_crossed events only). |

### ticker/{auto} (upset example)
```json
{
  "type": "upset",
  "sport": "tennis",
  "region": "athens",
  "winnerUid": "user_789",
  "winnerName": "Dana",
  "loserTier": "advanced",
  "delta": 200,
  "createdAt": "2026-03-01T14:30:00Z",
  "expiresAt": "2026-03-02T14:30:00Z"
}
```

### ticker/{auto} (personal_best example)
```json
{
  "type": "personal_best",
  "sport": "padel",
  "region": "thessaloniki",
  "userUid": "user_1",
  "userName": "Alex T.",
  "newPts": 3650,
  "previousBest": 3500,
  "createdAt": "2026-03-01T14:30:00Z",
  "expiresAt": "2026-03-02T14:30:00Z"
}
```

### ticker/{auto} (win_streak example)
```json
{
  "type": "win_streak",
  "sport": "tennis",
  "region": "athens",
  "userUid": "user_2",
  "userName": "Eve K.",
  "streak": 5,
  "createdAt": "2026-03-01T14:30:00Z",
  "expiresAt": "2026-03-02T14:30:00Z"
}
```

### ticker/{auto} (tier_crossed example)
```json
{
  "type": "tier_crossed",
  "sport": "tennis",
  "region": "athens",
  "userUid": "user_3",
  "userName": "Nick L.",
  "tierBefore": "intermediate",
  "tierAfter": "advanced",
  "direction": "up",
  "createdAt": "2026-03-01T14:30:00Z",
  "expiresAt": "2026-03-02T14:30:00Z"
}
```

---

## Collection: venueSuggestions

User-submitted venue suggestions awaiting human moderation. Documents are
written by the `POST /venues/suggest` endpoint and are NOT promoted to the
live `venues` collection until a moderator reviews and approves them.

### Fields: venueSuggestions/{autoId}

| Field | Type | Notes |
|-------|------|-------|
| `name` | string | Trimmed venue name as entered by the user (non-blank, 1–200 chars) |
| `coordinates` | map `{lat, lng}` | Lat/lng pair (lat: -90..90, lng: -180..180) |
| `sport` | string (enum) | One of `tennis`, `padel`, `pickleball` |
| `notes` | string \| null | Optional free-text notes (max 500 chars) |
| `suggestedBy` | string | UID of the user who submitted the suggestion |
| `createdAt` | timestamp | UTC submission time |
| `status` | string | Moderation state. Always `"pending"` on creation |

### Example

```json
{
  "name": "My Local Club",
  "coordinates": {"lat": 37.95, "lng": 23.72},
  "sport": "padel",
  "notes": "2 outdoor courts, open until 11pm",
  "suggestedBy": "user_ignatios",
  "createdAt": "2026-04-25T10:15:00Z",
  "status": "pending"
}
```
