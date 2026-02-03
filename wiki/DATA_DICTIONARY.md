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
- `journalRecent[]`: `{entryId, createdAt, title, matchId?, sport?}` (cache, cap <= 10)
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
| rankings.tennis | map | optional | sport | canonical | — | `{sport, pts, globalRanking}`. |
| rankings.padel | map | optional | sport | canonical | — | `{sport, pts, globalRanking}`. |
| rankings.pickleball | map | optional | sport | canonical | — | `{sport, pts, globalRanking}`. |
| rankings.*.sport | string | required | sport | canonical | — | Enum value. |
| rankings.*.pts | number | optional | — | canonical | — | Ranking points. |
| rankings.*.globalRanking | number | optional | — | canonical | — | Optional global rank. |
| preferences | map | optional | — | canonical | — | Private. |
| preferences.area | number | optional | — | canonical | — | Private; area code. |
| preferences.levels | map | optional | level | canonical | — | Per-sport level preferences. |
| preferences.levels.tennis | string | optional | level | canonical | — | Enum value. |
| preferences.levels.padel | string | optional | level | canonical | — | Enum value. |
| preferences.levels.pickleball | string | optional | level | canonical | — | Enum value. |
| preferences.sports | array<string> | optional | sport | canonical | — | Private; preferred sports. |
| leaguesActive | array<map> | optional | — | cache | — | Active league summaries (cap <= 20). |
| leaguesCompleted | array<map> | optional | — | cache | — | Completed league summaries (cap <= 20). |
| upcomingMatches | array<map> | optional | — | cache | — | Upcoming match summaries (cap <= 10). |
| completedMatches | array<map> | optional | — | cache | — | Completed match summaries (cap <= 10). |
| journalRecent | array<map> | optional | — | cache | — | Recent journal summaries (cap <= 10). |
| cursors | map | optional | — | cache | — | Cursor bundle for pagination. |

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
  "cursors": {"upcomingMatches": null, "completedMatches": null, "journal": null}
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
| area | number | optional | — | cache | — | From user preferences; enables geo-scoped discovery queries. |

### Required composite indexes
- Active broadcasts by area/sport: `status` (ASC), `area` (ASC), `sport` (ASC), `expiresAt` (ASC)
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
  "area": 101
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
