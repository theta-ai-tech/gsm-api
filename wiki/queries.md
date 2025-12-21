# Firestore Query Contract

This documents the exact queries we will support in C3. No Firestore calls or indexes are implemented yet.

## Q1 — Get user profile (single doc read)
- Purpose: `GET /users/{uid}`; return `PrivateUserProfile` when `requester.uid == uid`, otherwise `PublicUserProfile`.
- Path: `users/{uid}`
- Notes: single document read; no composite index needed.

## Q2 — Upcoming matches for a user (sorted)
- Purpose: Upcoming matches list (future “Upcoming” screen).
- Collection: `matches`
- Filters:
  - `participantUids` array-contains `{uid}`
  - `status == "scheduled"`
  - `scheduledAt >= now (UTC)`
- Ordering: `orderBy scheduledAt ASC`
- Pagination: cursor-based (e.g., `startAfter(last_scheduledAt, last_match_id)`).
- Result model: `Match` (full) as MVP; can project to `UserMatchSummary` later.

## Q3 — Completed matches for a user (sorted)
- Purpose: Match history list (future “History” screen).
- Collection: `matches`
- Filters:
  - `participantUids` array-contains `{uid}`
  - `status == "completed"`
- Ordering: `orderBy finishedAt DESC`
- Pagination: cursor-based (e.g., `startAfter(last_finishedAt, last_match_id)`).
- Result model: `Match` (full) as MVP; can project to `UserCompletedMatchSummary` later.

## Q4 — Matches by league (sorted)
- Purpose: League fixture list and results view.
- Collection: `matches`
- Filters:
  - `leagueId == {leagueId}`
- Variants:
  - Upcoming: `status == "scheduled"`, `orderBy scheduledAt ASC`
  - Completed: `status == "completed"`, `orderBy finishedAt DESC`
- Pagination: cursor-based (same approach as Q2/Q3).

## Q5 — Journal entries for a user (sorted + paginated)
- Purpose: Journaling list view.
- Path: `users/{uid}/journalEntries`
- Filters: none for MVP
- Ordering: `orderBy createdAt DESC`
- Pagination: cursor-based via `startAfter(createdAt, entry_id)` (or equivalent).
- Result model: `JournalEntry`.

## Firestore Field Assumptions
- `matches.participantUids` (array of uid strings)
- `matches.status` (string enum)
- `matches.scheduledAt` (timestamp)
- `matches.finishedAt` (timestamp)
- `matches.leagueId` (string or null)
- `users/{uid}/journalEntries.createdAt` (timestamp)
- Note: field names align with the camelCase used in C2 seeding/mapping.

## Expected Composite Indexes (C3.3)
- Q2 user upcoming matches: `participantUids + status + scheduledAt`
- Q3 user completed matches: `participantUids + status + finishedAt`
- Q4 league matches: `leagueId + status + scheduledAt/finishedAt`
- Exact index definitions will be finalized after repo queries are implemented (C3.2) and verified against the emulator.***
