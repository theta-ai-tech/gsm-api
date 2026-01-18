# Functions (D-series)

This page tracks the D-series Firestore trigger work and the intended behavior for each task.

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
