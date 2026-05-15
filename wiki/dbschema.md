# Firestore Data Model (GSM)

Firestore is schemaless, but we keep a consistent structure using deterministic document IDs and well-known fields. This doc sketches the collections/subcollections and example shapes using the C1 models.

## Collections
- `users/{uid}`
  - Fields: uid, name, email, profileUrl, phone
  - rankings: { tennis?: {sport, pts, globalRanking}, padel?: {...}, pickleball?: {...} }
  - preferences: { area: int, levels: {tennis?, padel?, pickleball?}, sports: [sport], defaultGeo?: {lat, lng}, defaultRadiusKm?: int }
  - leaguesActive: [ {leagueId, name, sport, status, role?} ]
  - leaguesCompleted: [ {leagueId, name, sport, status, role?} ]
  - upcomingMatches: [ {matchId, sport, scheduledAt, leagueId?, courtId?, opponents: [{uid, name?}]} ]
  - completedMatches: [ {matchId, sport, finishedAt, result?, scoreText?, leagueId?} ]
  - journalRecent: [ {entryId, createdAt, title, matchId?, sport?} ]
  - cursors?: { upcomingMatches?, completedMatches?, journal? }
  - playTab?: { state (`PlayTabStateEnum`), activeBroadcastId?, activeMatchId?, activeOutgoingOfferId?, pendingIncomingOfferIds: [offerId], updatedAt? }
  - Subcollection: `journalEntries/{entryId}`
    - Fields: title, body, tags[], createdAt, matchId?, sport?, visibility (`private|friends`)

- `leagues/{leagueId}`
  - Fields: name, sport, season?, status (`active|completed|upcoming|open`), ownerUid, meta (dict)
  - region?: string — named region (e.g. "athens") for PL-L1 browser filter
  - maxPlayers?: int — hard cap for the league (PL-L1 "8/12 spots")
  - currentPlayers?: int — denormalized active member count (updated on join/leave; PL-L1 progress bar)
  - startDate?: timestamp — when play begins (PL-L1 "Starts May 1")
  - endDate?: timestamp — when the season ends (PL-L2 detail view)
  - tier?: string — display-only tier label for MVP; no join enforcement (e.g. "intermediate")
  - Subcollection: `members/{uid}` with role, status, joinedAt, stats?

- `matches/{matchId}`
  - Fields: sport, status (`scheduled|pending_confirmation|completed|disputed|cancelled`)
  - scheduledAt?, finishedAt?, leagueId?, courtId?
  - participants: [{uid, team?, role (`player|referee`), result? (`W|L|D`)}]
  - participantUids: [uid] (for array-contains queries)
  - resultByUser?: { uid: `W|L|D` }
  - score?: { sets: [{p1Games, p2Games, tiebreakScore?}], winnerUid?, retired (bool) }

- `broadcasts/{broadcastId}`
  - Fields: ownerUid, sport, availability (`today|tomorrow|weekend`), courtStatus (`have_court|need_court`), courtLocation?
  - status (`active|expired|cancelled|matched`), expiresAt, createdAt
  - location: { area?: int, geo?: {lat, lng}, radiusKm?: int } (at least one of area or geo required)
  - Cache: ownerName, ownerRanking? (`{sport, pts}`)
  - Doubles (DBL-3): matchType (`singles|doubles`, default `singles`), broadcastType (`find_opponent|find_fourth`, default `find_opponent`), partnerUid?
    - `broadcastType=find_fourth` is only valid with `matchType=doubles`.
    - `matchType=doubles` + `broadcastType=find_opponent` requires `partnerUid` (challenge as a team).
    - `matchType=doubles` + `broadcastType=find_fourth` keeps `partnerUid` optional.
    - `matchType=singles` always stores `partnerUid=null`.
    - Legacy documents written before DBL-3 are read with the defaults above.
  - One active broadcast per user at a time; offers queue against it.

- `offers/{offerId}`
  - Fields: fromUid, toUid, broadcastId?, sport, proposedTime?, courtLocation?, message?
  - status (`pending|accepted|declined|expired|cancelled`), expiresAt, createdAt
  - Cache: fromName, fromRanking? (`{sport, pts}`), toName, toRanking? (`{sport, pts}`)
  - matchId? (set on acceptance, references created match)

## Identity and IDs
- Users, leagues, matches, journal entries, broadcasts, and offers use deterministic IDs (uids or preset doc IDs) to make seeding idempotent and querying predictable.

## Emulator Seeding
- See `tools/README.md` for how the seed script populates the emulator with sample data.
