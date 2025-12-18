from datetime import datetime, timezone

from app.models import (
    CursorBundle,
    JournalEntry,
    JournalEntrySummary,
    League,
    LeagueMember,
    LeagueSummary,
    LeagueStatusEnum,
    LevelEnum,
    Match,
    MatchOpponentSummary,
    MatchParticipant,
    MatchResultEnum,
    MatchScore,
    MatchStatusEnum,
    ParticipantRoleEnum,
    PerSportLevels,
    PerSportRankings,
    PrivateUserProfile,
    PublicUserProfile,
    SetScore,
    SportEnum,
    SportRanking,
    UserCompletedMatchSummary,
    UserMatchSummary,
    UserPreferences,
)


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    """Helper for timezone-aware timestamps in sample data."""
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


# --- Users ---
# In-memory sample users; align uids with matches/leagues below for consistency.
USER_IGNATIOS = PrivateUserProfile(
    uid="user_ignatios",
    name="Ignatios",
    email="ignatios@example.com",
    phone="+301111111111",
    profile_url="http://example.com/ignatios.png",
    rankings=PerSportRankings(
        padel=SportRanking(sport=SportEnum.PADEL, pts=980, global_ranking=120),
        tennis=SportRanking(sport=SportEnum.TENNIS, pts=620, global_ranking=None),
    ),
    preferences=UserPreferences(
        area=101,
        levels=PerSportLevels(
            padel=LevelEnum.ADVANCED,
            tennis=LevelEnum.INTERMEDIATE,
        ),
        sports=[SportEnum.PADEL, SportEnum.TENNIS],
    ),
    leagues_active=[],
    leagues_completed=[],
    upcoming_matches=[],
    completed_matches=[],
    journal_recent=[],
    cursors=None,
)

USER_ALICE = PrivateUserProfile(
    uid="user_alice",
    name="Alice",
    email="alice@example.com",
    phone="+301122334455",
    profile_url=None,
    rankings=PerSportRankings(
        tennis=SportRanking(sport=SportEnum.TENNIS, pts=820, global_ranking=340),
    ),
    preferences=UserPreferences(
        area=202,
        levels=PerSportLevels(
            tennis=LevelEnum.ADVANCED,
        ),
        sports=[SportEnum.TENNIS],
    ),
    leagues_active=[],
    leagues_completed=[],
    upcoming_matches=[],
    completed_matches=[],
    journal_recent=[],
    cursors=None,
)

USER_BOB = PrivateUserProfile(
    uid="user_bob",
    name="Bob",
    email="bob@example.com",
    phone=None,
    profile_url="http://example.com/bob.png",
    rankings=PerSportRankings(
        padel=SportRanking(sport=SportEnum.PADEL, pts=540, global_ranking=None),
        pickleball=SportRanking(sport=SportEnum.PICKLEBALL, pts=300, global_ranking=None),
    ),
    preferences=UserPreferences(
        area=303,
        levels=PerSportLevels(
            padel=LevelEnum.INTERMEDIATE,
            pickleball=LevelEnum.BEGINNER,
        ),
        sports=[SportEnum.PADEL, SportEnum.PICKLEBALL],
    ),
    leagues_active=[],
    leagues_completed=[],
    upcoming_matches=[],
    completed_matches=[],
    journal_recent=[],
    cursors=None,
)

SAMPLE_USERS = [USER_IGNATIOS, USER_ALICE, USER_BOB]

# --- Leagues ---
# Sample leagues referencing the users above.
LEAGUE_PADEL_LOCAL = League(
    league_id="padel-local-2025",
    name="Local Padel Ladder 2025",
    sport=SportEnum.PADEL,
    season="Autumn 2025",
    status=LeagueStatusEnum.ACTIVE,
    owner_uid=USER_IGNATIOS.uid,
    meta={},
)

LEAGUE_TENNIS_LOCAL = League(
    league_id="tennis-local-2025",
    name="Local Tennis Series 2025",
    sport=SportEnum.TENNIS,
    season="Spring 2025",
    status=LeagueStatusEnum.UPCOMING,
    owner_uid=USER_ALICE.uid,
    meta=None,
)

SAMPLE_LEAGUES = [LEAGUE_PADEL_LOCAL, LEAGUE_TENNIS_LOCAL]

# --- Matches ---
# A small set of matches with varied statuses; participant_uids align to SAMPLE_USERS.
MATCH_SCHEDULED = Match(
    match_id="match_scheduled",
    sport=SportEnum.PADEL,
    status=MatchStatusEnum.SCHEDULED,
    scheduled_at=utc(2025, 1, 15, 18, 0),
    league_id=LEAGUE_PADEL_LOCAL.league_id,
    court_id="court-1",
    score=None,
    result_by_user=None,
    participants=[
        MatchParticipant(uid=USER_IGNATIOS.uid, role=ParticipantRoleEnum.PLAYER, team=1),
        MatchParticipant(uid=USER_BOB.uid, role=ParticipantRoleEnum.PLAYER, team=2),
    ],
    participant_uids=[USER_IGNATIOS.uid, USER_BOB.uid],
)

MATCH_PENDING = Match(
    match_id="match_pending",
    sport=SportEnum.TENNIS,
    status=MatchStatusEnum.PENDING_CONFIRMATION,
    scheduled_at=utc(2024, 12, 20, 17, 0),
    league_id=LEAGUE_TENNIS_LOCAL.league_id,
    score=None,
    result_by_user={
        USER_ALICE.uid: MatchResultEnum.WIN,
    },
    participants=[
        MatchParticipant(uid=USER_ALICE.uid, role=ParticipantRoleEnum.PLAYER, team=None),
        MatchParticipant(uid=USER_IGNATIOS.uid, role=ParticipantRoleEnum.PLAYER, team=None),
    ],
    participant_uids=[USER_ALICE.uid, USER_IGNATIOS.uid],
)

MATCH_COMPLETED_1 = Match(
    match_id="match_completed_1",
    sport=SportEnum.PADEL,
    status=MatchStatusEnum.COMPLETED,
    scheduled_at=utc(2024, 11, 1, 19, 0),
    finished_at=utc(2024, 11, 1, 20, 15),
    league_id=LEAGUE_PADEL_LOCAL.league_id,
    score=MatchScore(
        sets=[
            SetScore(p1_games=6, p2_games=4),
            SetScore(p1_games=7, p2_games=5, tiebreak_score="7-5"),
        ]
    ),
    result_by_user={
        USER_IGNATIOS.uid: MatchResultEnum.WIN,
        USER_BOB.uid: MatchResultEnum.LOSS,
    },
    participants=[
        MatchParticipant(uid=USER_IGNATIOS.uid, role=ParticipantRoleEnum.PLAYER, team=None),
        MatchParticipant(uid=USER_BOB.uid, role=ParticipantRoleEnum.PLAYER, team=None),
    ],
    participant_uids=[USER_IGNATIOS.uid, USER_BOB.uid],
)

MATCH_COMPLETED_2 = Match(
    match_id="match_completed_2",
    sport=SportEnum.TENNIS,
    status=MatchStatusEnum.COMPLETED,
    scheduled_at=utc(2024, 10, 10, 18, 30),
    finished_at=utc(2024, 10, 10, 19, 50),
    league_id=None,
    score=MatchScore(
        sets=[
            SetScore(p1_games=4, p2_games=6),
            SetScore(p1_games=6, p2_games=3),
            SetScore(p1_games=6, p2_games=2),
        ]
    ),
    result_by_user={
        USER_ALICE.uid: MatchResultEnum.WIN,
        USER_IGNATIOS.uid: MatchResultEnum.LOSS,
    },
    participants=[
        MatchParticipant(uid=USER_ALICE.uid, role=ParticipantRoleEnum.PLAYER, team=None),
        MatchParticipant(uid=USER_IGNATIOS.uid, role=ParticipantRoleEnum.PLAYER, team=None),
    ],
    participant_uids=[USER_ALICE.uid, USER_IGNATIOS.uid],
)

SAMPLE_MATCHES = [MATCH_SCHEDULED, MATCH_PENDING, MATCH_COMPLETED_1, MATCH_COMPLETED_2]

# --- Journal entries ---
# Basic journal entries tied to completed matches.
JOURNAL_1 = JournalEntry(
    entry_id="journal_1",
    uid=USER_IGNATIOS.uid,
    created_at=utc(2024, 11, 2, 9, 0),
    title="Padel win reflections",
    body="Worked on volleys; need to improve serve consistency.",
    tags=["padel", "volley", "serve"],
    match_id=MATCH_COMPLETED_1.match_id,
    sport=SportEnum.PADEL,
    visibility=SportEnum.PADEL.to_string()  # type: ignore[attr-defined]
)

JOURNAL_2 = JournalEntry(
    entry_id="journal_2",
    uid=USER_ALICE.uid,
    created_at=utc(2024, 10, 11, 8, 30),
    title="Tennis match recap",
    body="Backhand felt strong, footwork needs work.",
    tags=["tennis", "backhand"],
    match_id=MATCH_COMPLETED_2.match_id,
    sport=SportEnum.TENNIS,
    visibility=SportEnum.TENNIS.to_string()  # type: ignore[attr-defined]
)

SAMPLE_JOURNAL_ENTRIES = [JOURNAL_1, JOURNAL_2]
