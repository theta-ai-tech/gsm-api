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
