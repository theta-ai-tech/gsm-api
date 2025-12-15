# Core Models & Enums (C1)

This summarizes the shared value objects, enums, and resource models introduced in the C1 epic.

## Enums
- Sports & levels: `SportEnum` (`tennis`, `padel`, `pickleball`), `LevelEnum` (`beginner`, `intermediate`, `advanced`, `pro`).
- Matches & leagues: `MatchStatusEnum` (`scheduled`, `pending_confirmation`, `completed`, `disputed`, `cancelled`), `MatchResultEnum` (`W`, `L`, `D`), `LeagueStatusEnum` (`active`, `completed`, `upcoming`), `LeagueRoleEnum` (`player`, `admin`, `captain`), `LeagueMemberStatusEnum` (`active`, `left`, `banned`), `ParticipantRoleEnum` (`player`, `referee`).
- Journal: `JournalVisibilityEnum` (`private`, `friends`).

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
