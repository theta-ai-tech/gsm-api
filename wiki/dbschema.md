# Firestore Data Model (GSM)

Firestore is schemaless, but we keep a consistent structure using deterministic document IDs and well-known fields. This doc sketches the collections/subcollections and example shapes using the C1 models.

## Collections
- `users/{uid}`
  - Fields: uid, name, email, profileUrl, phone
  - rankings: { tennis?: {sport, pts, globalRanking}, padel?: {...}, pickleball?: {...} }
  - preferences: { area: int, levels: {tennis?, padel?, pickleball?}, sports: [sport] }
  - leaguesActive: [ {leagueId, name, sport, status, role?} ]
  - leaguesCompleted: [ {leagueId, name, sport, status, role?} ]
  - upcomingMatches: [ {matchId, sport, scheduledAt, leagueId?, courtId?, opponents: [{uid, name?}]} ]
  - completedMatches: [ {matchId, sport, finishedAt, result?, scoreText?, leagueId?} ]
  - journalRecent: [ {entryId, createdAt, title, matchId?, sport?} ]
  - cursors?: { upcomingMatches?, completedMatches?, journal? }
  - Subcollection: `journalEntries/{entryId}`
    - Fields: title, body, tags[], createdAt, matchId?, sport?, visibility (`private|friends`)

- `leagues/{leagueId}`
  - Fields: name, sport, season?, status (`active|completed|upcoming`), ownerUid, meta (dict)
  - (Future) Subcollection: `members/{uid}` with role, status, joinedAt, stats?

- `matches/{matchId}`
  - Fields: sport, status (`scheduled|pending_confirmation|completed|disputed|cancelled`)
  - scheduledAt?, finishedAt?, leagueId?, courtId?
  - participants: [{uid, team?, role (`player|referee`), result? (`W|L|D`)}]
  - participantUids: [uid] (for array-contains queries)
  - resultByUser?: { uid: `W|L|D` }
  - score?: { sets: [{p1Games, p2Games, tiebreakScore?}], winnerUid?, retired (bool) }

## Identity and IDs
- Users, leagues, matches, and journal entries use deterministic IDs (uids or preset doc IDs) to make seeding idempotent and querying predictable.

## Emulator Seeding
- See `tools/README.md` for how the seed script populates the emulator with sample data.***
