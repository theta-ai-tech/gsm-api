# Firestore Queries and Index Mapping (C3.5)

This document maps the C3 query contract to the actual repo methods and index requirements.
See `wiki/queries.md` for the full contract details.

## Q1 — User profile doc read
- Collection/path: `users/{uid}`
- Filters: none (single doc read)
- Ordering: none
- Repo: `UsersRepo.get_public_profile`, `UsersRepo.get_private_profile`
- Index: single-field only (no composite index required)

## Q2 — Upcoming matches by user
- Collection/path: `matches`
- Filters:
  - `participantUids` array-contains `{uid}`
  - `status == "scheduled"`
  - `scheduledAt >= now`
- Ordering: `scheduledAt ASC`
- Repo: `MatchesRepo.list_upcoming_for_user`
- Index: composite in `firestore.indexes.json`
  - `participantUids` (ARRAY_CONTAINS), `status` (ASC), `scheduledAt` (ASC)

## Q3 — Completed matches by user
- Collection/path: `matches`
- Filters:
  - `participantUids` array-contains `{uid}`
  - `status == "completed"`
- Ordering: `finishedAt DESC`
- Repo: `MatchesRepo.list_completed_for_user`
- Index: composite in `firestore.indexes.json`
  - `participantUids` (ARRAY_CONTAINS), `status` (ASC), `finishedAt` (DESC)

## Q4 — Matches by league

Upcoming league matches:
- Collection/path: `matches`
- Filters:
  - `leagueId == {leagueId}`
  - `status == "scheduled"`
- Ordering: `scheduledAt ASC`
- Repo: `MatchesRepo.list_upcoming_for_league`
- Index: composite in `firestore.indexes.json`
  - `leagueId` (ASC), `status` (ASC), `scheduledAt` (ASC)

Completed league matches:
- Collection/path: `matches`
- Filters:
  - `leagueId == {leagueId}`
  - `status == "completed"`
- Ordering: `finishedAt DESC`
- Repo: `MatchesRepo.list_completed_for_league`
- Index: composite in `firestore.indexes.json`
  - `leagueId` (ASC), `status` (ASC), `finishedAt` (DESC)

## Q5 — Journal entries for user
- Collection/path: `users/{uid}/journalEntries`
- Filters: none
- Ordering: `createdAt DESC`
- Repo: `JournalRepo.list_entries`
- Index: single-field only (no composite index required)

## Leagues by Status (MVP Source of Truth)
Option A (MVP): derive “active” vs “completed” leagues from denormalized summaries stored on
the user document:
- `users/{uid}.leaguesActive`: `LeagueSummary[]`
- `users/{uid}.leaguesCompleted`: `LeagueSummary[]`

Why:
- Fast “home/profile” read without cross-league joins.
- Avoids membership query complexity for MVP.

Future alternative (Option B):
- Derive by membership docs at `leagues/{leagueId}/members/{uid}` using collection-group queries,
  or introduce a top-level `leagueMembers` collection for efficient queries.

Tests in C4 treat Option A as canonical.

## How to reproduce locally
```bash
make emu-firestore
make seed-emu
make check-queries-emu
pytest -k firestore_queries
```

## Deploy to dev
When running the API against real dev Firestore, you must deploy indexes:
```bash
make deploy-indexes-dev
```
Indexes can take time to build. Avoid using console-generated index links; prefer committing
changes to `firestore.indexes.json`.

### When to run
- Any time `firestore.indexes.json` changes.
- Before running the API against real dev Firestore (non-emulator mode).

### How to verify
- Repo queries that previously failed with “requires an index” should succeed after deployment.

### Notes
- Emulator: no deployment needed.
- Dev/prod: deployment required.
- Use a dedicated dev project for index deployment; avoid running this against prod unless intended.
