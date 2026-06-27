# Firestore Queries, Repositories & Indexes

> **Canonical reference for the data-access layer.** Merges the query contract, the
> repository mapping, and the composite-index requirements that were previously split
> across three docs. Models referenced here are defined in [`models.md`](models.md);
> full field shapes are in [`data-dictionary.md`](data-dictionary.md).

## Repositories (data-access layer)

Query contracts are implemented through small repository classes (`UsersRepo`, `MatchesRepo`,
`JournalRepo`, …). A "Repo" is the data-access layer for a domain aggregate, not a raw Firestore
collection. Repos encapsulate Firestore details (paths, filters, ordering, pagination) and return
domain models rather than raw documents. This keeps route handlers thin and lets the Firestore
schema evolve behind a stable, testable API.

| Repo method | Returns / implements |
|---|---|
| `UsersRepo.get_private_profile(uid)` | `PrivateUserProfile` (Q1, self view) |
| `UsersRepo.get_public_profile(uid)` | `PublicUserProfile` (Q1, public view) |
| `MatchesRepo.list_upcoming_for_user(uid, …)` | Q2 |
| `MatchesRepo.list_completed_for_user(uid, …)` | Q3 |
| `MatchesRepo.list_upcoming_for_league(league_id, …)` | Q4 (upcoming) |
| `MatchesRepo.list_completed_for_league(league_id, …)` | Q4 (completed) |
| `JournalRepo.list_entries(uid, …)` | Q5 |

> The repo set has grown well beyond Q1–Q5 (broadcasts, offers, leagues, scouting, stats,
> tiers, venues, notification intents, device tokens, …). The table above documents the
> original profile/match/journal query contract; see `api/app/repos/` for the full current set.

## Query contract

### Q1 — User profile (single doc read)
- **Purpose:** `GET /users/{uid}` — return `PrivateUserProfile` when `requester.uid == uid`, else `PublicUserProfile`.
- **Path:** `users/{uid}`
- **Repo:** `UsersRepo.get_public_profile`, `UsersRepo.get_private_profile`
- **Index:** single-field only (no composite index).

### Q2 — Upcoming matches for a user
- **Collection:** `matches`
- **Filters:** `participantUids` array-contains `{uid}`; `status == "scheduled"`; `scheduledAt >= now (UTC)`
- **Ordering:** `scheduledAt ASC`
- **Pagination:** cursor-based (`startAfter(last_scheduledAt, last_match_id)`)
- **Repo:** `MatchesRepo.list_upcoming_for_user`
- **Index:** composite — `participantUids` (ARRAY_CONTAINS), `status` (ASC), `scheduledAt` (ASC)

### Q3 — Completed matches for a user
- **Collection:** `matches`
- **Filters:** `participantUids` array-contains `{uid}`; `status == "completed"`
- **Ordering:** `finishedAt DESC`
- **Pagination:** cursor-based
- **Repo:** `MatchesRepo.list_completed_for_user`
- **Index:** composite — `participantUids` (ARRAY_CONTAINS), `status` (ASC), `finishedAt` (DESC)

### Q4 — Matches by league
- **Collection:** `matches`
- **Upcoming:** `leagueId == {leagueId}`, `status == "scheduled"`, `orderBy scheduledAt ASC` → `MatchesRepo.list_upcoming_for_league`
  - **Index:** `leagueId` (ASC), `status` (ASC), `scheduledAt` (ASC)
- **Completed:** `leagueId == {leagueId}`, `status == "completed"`, `orderBy finishedAt DESC` → `MatchesRepo.list_completed_for_league`
  - **Index:** `leagueId` (ASC), `status` (ASC), `finishedAt` (DESC)

### Q5 — Journal entries for a user
- **Path:** `users/{uid}/journalEntries`
- **Filters:** none
- **Ordering:** `createdAt DESC`
- **Pagination:** cursor-based via `startAfter(createdAt, entry_id)`
- **Repo:** `JournalRepo.list_entries`
- **Index:** single-field only (no composite index).

## Field assumptions
- `matches.participantUids` — array of uid strings
- `matches.status` — string enum
- `matches.scheduledAt`, `matches.finishedAt` — timestamps
- `matches.leagueId` — string or null
- `users/{uid}/journalEntries.createdAt` — timestamp

Field names use the camelCase convention shared with seeding/mapping.

## Leagues by status (source of truth)

Active vs completed leagues are derived from denormalized summaries on the user document:
- `users/{uid}.leaguesActive`: `LeagueSummary[]`
- `users/{uid}.leaguesCompleted`: `LeagueSummary[]`

This gives a fast home/profile read without cross-league joins. These summaries are maintained
by the league-member triggers (see [`../architecture/triggers.md`](../architecture/triggers.md)).
An alternative membership-query approach (collection-group queries over
`leagues/{leagueId}/members/{uid}`, or a top-level `leagueMembers` collection) remains available
if membership-based reads are needed later.

## Working with indexes locally

```bash
make emu-firestore
make seed-emu
make check-queries-emu
pytest -k firestore_queries
```

Emulator queries need no index deployment. For real dev/prod Firestore, composite indexes must be
deployed:

```bash
make deploy-indexes-dev      # deploy firestore.indexes.json to the dev project
```

- Run any time `firestore.indexes.json` changes, and before running the API against real dev Firestore.
- Indexes can take time to build. Commit changes to `firestore.indexes.json` rather than using
  console-generated index links.
- A repo query that previously failed with "requires an index" should succeed after deployment.
- Use a dedicated dev project for index deployment; never run this against prod unless intended.
