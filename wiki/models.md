# Core Models & Enums (C1)

This summarizes the shared value objects, enums, and resource models introduced in the C1 epic.

## Enums
- Sports & levels: `SportEnum` (`tennis`, `padel`, `pickleball`), `LevelEnum` (`beginner`, `intermediate`, `advanced`, `pro`).
- Matches & leagues: `MatchStatusEnum` (`scheduled`, `pending_confirmation`, `completed`, `disputed`, `cancelled`), `MatchResultEnum` (`W`, `L`, `D`), `LeagueStatusEnum` (`active`, `completed`, `upcoming`), `LeagueRoleEnum` (`player`, `admin`, `captain`), `LeagueMemberStatusEnum` (`active`, `left`, `banned`), `ParticipantRoleEnum` (`player`, `referee`).
- Journal: `JournalVisibilityEnum` (`private`, `friends`).
- Home tab router: `PlayTabStateEnum` (`DISCOVERY`, `BROADCAST_ACTIVE`, `OUTGOING_OFFER_PENDING`, `INCOMING_OFFER_PENDING`, `MATCH_SCHEDULED`, `POST_MATCH_LOG_AVAILABLE`, `POST_MATCH_WAITING_OPPONENT`, `POST_MATCH_CONFIRM_REQUIRED`, `MATCH_DISPUTED`).
- Broadcasts: `BroadcastStatusEnum` (`active`, `expired`, `cancelled`, `matched`), `AvailabilityEnum` (`today`, `tomorrow`, `weekend`), `CourtStatusEnum` (`have_court`, `need_court`).
- Offers: `OfferStatusEnum` (`pending`, `accepted`, `declined`, `expired`, `cancelled`).

## Base
- `GsmBaseModel` (Pydantic): extra-forbid, populate_by_name, from_attributes, and normalizes naive datetimes to UTC.
- Re-exports `EmailStr`, `HttpUrl` for strict types.

## Common Value Objects
- Rankings/preferences: `SportRanking`, `PerSportRankings`, `PerSportLevels`, `UserPreferences`.
- Scoring: `SetScore` (non-negative games), `MatchScore` (structured score; free-text derived later).
- Summaries: `LeagueSummary`, `MatchOpponentSummary`, `UserMatchSummary`, `UserCompletedMatchSummary`, `JournalEntrySummary`, `CursorBundle`.

## Profiles
- `PublicUserProfile`: uid, name, profile URL, rankings, active/completed leagues (no email/phone/preferences).
- `PrivateUserProfile`: extends public with email, phone, preferences, upcoming/completed matches, recent journal, cursors (only for self).

## Leagues
- `League`: id, name, sport, season, status, owner_uid, optional meta.
- `LeagueMember`: uid, role, status, joined_at, optional stats.

## Matches
- `MatchParticipant`: uid, optional team number, role, optional result.
- `Match`: core match resource with sport/status, schedule/finish, league/court, structured score, per-user results, participants, and flattened `participant_uids` for Firestore array-contains queries.

## Journal
- `JournalEntry`: id, owner uid, timestamps, title/body/tags, optional match/sport, visibility.

## Play Tab (Tab 1)

Request/response models for Tab 1 PLAY endpoints:
- `CreateBroadcastRequest`, `CreateBroadcastResponse`: Create/cancel availability broadcasts
- `SendOfferRequest`, `SendOfferResponse`: Send challenge offers
- `OfferActionResponse`: Accept/decline/cancel offer responses

Core domain models:
- `Broadcast`: Full broadcast document with owner, sport, availability, court status, location (hybrid area/geo), TTL
- `Offer`: Full offer document with sender/recipient, sport, proposed time, TTL, status, optional match linkage
- `GeoLocation`, `BroadcastLocation`: Location support (area codes + lat/lng/radius)

/me/state response envelope:
- `MeStateResponse`: Top-level envelope with mode, serverTime, primary IDs, payload, annotations, uiEvents
- `MeStatePrimary`: Stable ID references (broadcastId, matchId, activeOfferIds)
- `UIEvent`: Transient notifications (offer_expired, broadcast_expired, etc.)

Mode-specific payloads (one per PlayTabStateEnum):
- `BroadcastActivePayload`: Active broadcast + queued pending offers
- `OutgoingOfferPayload`: Offer sent by user
- `IncomingOfferPayload`: Offer received by user
- `MatchScheduledPayload`: Upcoming match details with opponent, court
- `PostMatchLogAvailablePayload`, `PostMatchWaitingOpponentPayload`, `PostMatchConfirmRequiredPayload`, `MatchDisputedPayload`: Post-match flow states

Summary models:
- `PendingOfferSummary`: Lightweight offer for lists
- `OpponentSummary`: Opponent profile with name, ranking, profile URL

See `spec/tab1-play-payloads.md` for full JSON examples per mode.

For emulator seeding with these models, see `tools/README.md`.***
