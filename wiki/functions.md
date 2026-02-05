# Functions (D-series)

This page tracks the D-series Firestore trigger work and the intended behavior for each task.

Diagrams live in `arch/`:
- `arch/match_lifecycle.md`
- `arch/league_member_triggers.md`

## D1.1 — onMatchWrite: upcoming cache qualification
Purpose: Detect match writes that should update each participant's upcoming matches cache.

### Behavior summary
- A match qualifies as "upcoming" when:
  - `status == "scheduled"`
  - `scheduledAt` is a timezone-aware UTC timestamp strictly in the future
- Ignore:
  - deletes
  - non-scheduled statuses (`completed`, `cancelled`, `pending_confirmation`, `disputed`, etc.)
  - past or missing `scheduledAt`
  - no-op updates (no change to `status`, `scheduledAt`, or `participantUids`)

### How it is called
- Intended to run inside a Firestore trigger (Cloud Functions Gen 2) on
  `matches/{matchId}` document writes (create/update).
- Not called from API server code.

### What it updates
- D1.1 adds only qualification logic; no Firestore updates occur yet.
- Later D tasks will use the qualification result to push match IDs into each participant's
  upcoming cache.

### Cache note
- The "cache" here is a denormalized list stored on `users/{uid}` in Firestore, not an in-memory
  cache. It enables a single document read instead of multiple match queries.

## D1.2 — transactional upcoming cache update
Purpose: Atomically update each participant user doc to include a scheduled match in the
upcoming cache, ordered by `scheduledAt` and capped to 10.

### Behavior summary
- Uses a transaction per user doc to update:
  - `upcomingMatches` (canonical cache for ordering)
  - `upcomingMatchIds` (derived list of IDs, for compatibility)
- Updates are idempotent, deduped, ordered by `scheduledAt` ASC, and capped.
- Writes are skipped if the computed cache is unchanged.

### Trigger flow
- D1.1 detection runs first; on qualify, D1.2 updates each participant uid.

### What happens on a qualifying write
- For each participant, a transaction updates `upcomingMatches` (ordered by `scheduledAt`, capped).
- `upcomingMatchIds` is derived from that ordered cache for compatibility.
- No-op updates are skipped when the cache would not change.

### Where it runs
- This logic is intended for Firestore triggers on `matches/{matchId}` writes.

## D1.3 — upcoming cache cap & dedupe guards
Purpose: Prove cache update behavior is robust against duplicate events and full lists.

### Behavior summary
- Insert into empty list adds the match once.
- Duplicate events do not create duplicates.
- Ordering is deterministic by `scheduledAt` ascending.
- Cache is capped at 10; adding an 11th drops the oldest by `scheduledAt`.

## D2.1 — completion transition detection
Purpose: Trigger completion migration only on the first `scheduled` → `completed` transition.

### Behavior summary
- Requires `before.status == "scheduled"` and `after.status == "completed"`.
- Requires `finishedAt` to exist and be timezone-aware.
- Ignores idempotent repeats (`completed` → `completed`) and other status changes.

## D2.2 — migrate upcoming → completed cache
Purpose: Move a completed match out of upcoming and into recent completed, per participant.

### Behavior summary
- Removes `matchId` from `upcomingMatches`.
- Inserts `matchId` into `completedMatches` ordered by `finishedAt` DESC.
- Deduped and capped at 10.
- Updates `upcomingMatchIds` and `recentCompletedMatchIds` as derived lists.

## D3.1 — league member upsert into user summaries
Purpose: Maintain user league summaries on membership create/update.

### Behavior summary
- Triggered by `leagues/{leagueId}/members/{uid}` writes when member is active and role/status changed.
- Reads league doc and member doc to compose summary `{leagueId, sport, status, name, role}`.
- Upserts into `users/{uid}.leaguesActive` or `leaguesCompleted` based on league status.
- Deduped by `leagueId`, capped at 20, and avoids no-op writes.

### What gets updated
- On active membership writes, the user doc is updated so the league appears in the correct
  section:
  - `leaguesActive` when league status is `active`
  - `leaguesCompleted` when league status is `completed` (or non-active)
  - Removed from the other list to keep them disjoint

## D3.2 — league member removal from user summaries
Purpose: Remove league summaries when membership is deleted or becomes non-active.

### Behavior summary
- Triggered by `leagues/{leagueId}/members/{uid}` deletes or status changes to `left`/`banned`.
- Removes the league entry from both `leaguesActive` and `leaguesCompleted`.
- Idempotent under retries (no-op if already removed).

## D3 — Summary & use cases
- Fast Home/Profile: user reads include league summaries without membership queries.
- Role/status changes reflect immediately via cache upsert.
- Leave/ban removes the league from cached lists to prevent stale cards.
- Trigger retries are safe: dedupe and idempotent removal keep stable state.

## D6.2 — Trigger kill switch
Purpose: stop trigger cache writes immediately without redeploying code.

### Behavior summary
- Controlled by env var: `GSM_TRIGGERS_ENABLED` (`true` by default).
- When set to `false`, trigger entry handlers exit early and perform no Firestore writes.
- Applies to:
  - match write upcoming updates (D1)
  - match completion migration (D2)
  - league member upsert/removal summaries (D3)

## D6.3 — Structured logs + counters
Purpose: make trigger behavior inspectable and incident debugging faster.

### Behavior summary
- Trigger paths emit structured JSON logs with fields:
  - `trigger`, `action`
  - `matchId` / `leagueId`
  - `uid` (per-user actions) or `uids_count` + `uids_preview` (batch context)
  - `changed`
  - `reason` (for ignores/non-qualification)
- Each trigger invocation emits aggregated summary counters:
  - `processed_count`
  - `ignored_count`
  - `writes_count`

### Typical flow
- `qualify` log (qualifies + reason)
- `ignore` log when early-exiting (disabled/missing data/not qualified)
- per-user write log (`upsert`/`migrate`/`remove`) with `changed`
- `summary` log with counters
