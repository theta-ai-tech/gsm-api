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
- Allowed values: `active`, `completed`, `upcoming`

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

## Collection: users
Path: `users/{uid}`

Ownership: user-owned document; self-only updates as policy.

Purpose: canonical user profile data with denormalized summaries for fast reads.

### Public vs Private projection
- Public profile must not expose `email`, `phone`, or `preferences`.
- Private profile (self) includes those fields plus cached summary lists and cursors.

### Cache fields (denormalized summaries)
These fields are denormalized summaries for fast reads. Treat as cache with capped lengths.
- `leaguesActive[]`: `{leagueId, name, sport, status, role}` (cache, cap <= 20)
- `leaguesCompleted[]`: `{leagueId, name, sport, status, role}` (cache, cap <= 20)
- `upcomingMatches[]`: `{matchId, sport, scheduledAt, leagueId?, courtId?, opponents[]}` (cache, cap <= 10)
- `completedMatches[]`: `{matchId, sport, finishedAt, result?, scoreText?, leagueId?}` (cache, cap <= 10)
- `journalRecent[]`: `{entryId, createdAt, title, matchId?, sport?, entryType?}` (cache, cap <= 10)
- `cursors`: `{upcomingMatches?, completedMatches?, journal?}` (cache; last-seen pagination cursors)

### Fields: users/{uid}
| Field | Type | Required | Enum | Canonical|Cache | Index | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| uid | string | required | — | canonical | — | Stored in doc; should match document ID. |
| name | string | required | — | canonical | — | Public. |
| profileUrl | string (url) | optional | — | canonical | — | Public. |
| email | string | optional | — | canonical | — | Private. |
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
| preferences | map | optional | — | canonical | — | Private. |
| preferences.area | number | optional | — | canonical | — | Private; area code. |
| preferences.levels | map | optional | level | canonical | — | Per-sport level preferences. |
| preferences.levels.tennis | string | optional | level | canonical | — | Enum value. |
| preferences.levels.padel | string | optional | level | canonical | — | Enum value. |
| preferences.levels.pickleball | string | optional | level | canonical | — | Enum value. |
| preferences.sports | array<string> | optional | sport | canonical | — | Private; preferred sports. |
| preferences.defaultGeo | map | optional | — | canonical | — | Home-base coordinates for "nearby me" discovery. |
| preferences.defaultGeo.lat | number | required | — | canonical | — | Latitude (WGS84). |
| preferences.defaultGeo.lng | number | required | — | canonical | — | Longitude (WGS84). |
| preferences.defaultRadiusKm | number | optional | — | canonical | — | Default search radius in km (default 15). |
| leaguesActive | array<map> | optional | — | cache | — | Active league summaries (cap <= 20). |
| leaguesCompleted | array<map> | optional | — | cache | — | Completed league summaries (cap <= 20). |
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
    "sports": ["padel", "tennis"]
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

## Collection: leagues
Path: `leagues/{leagueId}`

### leagues/{leagueId}
```json
{
  "name": "Athens Spring Ladder",
  "sport": "tennis",
  "season": "2026-spring",
  "status": "active",
  "ownerUid": "user_admin",
  "meta": {"surface": "clay"}
}
```

## Subcollection: leagues/{leagueId}/members
Path: `leagues/{leagueId}/members/{uid}`

### leagues/{leagueId}/members/{uid}
```json
{
  "uid": "user_123",
  "role": "player",
  "status": "active",
  "joinedAt": "2026-01-15T12:00:00Z",
  "stats": {"wins": 3, "losses": 1}
}
```
| pending_confirmation | disputed | Opponent disputes submitted result. |
| completed | disputed | Result challenged after completion. |

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
| status | string | required | leagueStatus | canonical | — | League lifecycle state. |
| ownerUid | string | required | — | canonical | — | League owner uid. |
| meta | map | optional | — | canonical | — | Free-form metadata. |

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

### Common queries
- List members of a league ordered by `joinedAt` ASC.
- Check membership existence for a user: read `leagues/{leagueId}/members/{uid}`.
- User profiles cache league summaries in `users/{uid}.leaguesActive` / `leaguesCompleted`.

### leagues/{leagueId}
```json
{
  "name": "Local Padel Ladder 2025",
  "sport": "padel",
  "season": "Autumn 2025",
  "status": "active",
  "ownerUid": "user_123",
  "meta": {}
}
```

### leagues/{leagueId}/members/{uid}
```json
{
  "role": "player",
  "status": "active",
  "joinedAt": "2024-10-01T12:00:00Z",
  "stats": {}
}
```

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
