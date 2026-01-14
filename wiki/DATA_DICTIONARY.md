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

## Field Table Template
| Field | Type | Required | Enum | Canonical|Cache | Index | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| participantUids | array<string> | required | — | canonical | index=array-contains | Used for user-scoped match queries. |

## Examples
Placeholders for minimal JSON examples (to be filled in C5.2–C5.5).

### users/{uid}
```json
{}
```

### users/{uid}/journalEntries/{entryId}
```json
{}
```

### matches/{matchId}
```json
{}
```

### leagues/{leagueId}
```json
{}
```

### leagues/{leagueId}/members/{uid}
```json
{}
```

### courts/{courtId}
```json
{}
```
