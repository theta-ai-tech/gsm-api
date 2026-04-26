from datetime import datetime, timezone

from app.models import (
    CursorBundle,
    JournalEntry,
    JournalEntrySummary,
    LeaderboardEntry,
    LeaderboardSnapshot,
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
    PointHistoryEntry,
    PointHistoryReasonEnum,
    PrivateUserProfile,
    PublicUserProfile,
    RisingStarEntry,
    ScoutingProfile,
    ScoutingSportData,
    ScoutingTagCount,
    SetScore,
    SkillAxisData,
    SkillTaxonomy,
    SportEnum,
    SportRanking,
    SportSkillDna,
    TickerEvent,
    TickerEventTypeEnum,
    TierConfig,
    TierEnum,
    TierThreshold,
    JournalVisibilityEnum,
    UserCompletedMatchSummary,
    UserMatchSummary,
    UserPreferences,
)
from app.models.match import compute_participant_pair


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
    is_pro=True,
    rankings=PerSportRankings(
        padel=SportRanking(
            sport=SportEnum.PADEL,
            pts=980,
            global_ranking=120,
            tier=TierEnum.AMATEUR,
            registration_tier=TierEnum.AMATEUR,
            last_updated=utc(2026, 2, 20, 14, 0),
            personal_best=980,
            current_streak=2,
            best_streak=2,
        ),
        tennis=SportRanking(
            sport=SportEnum.TENNIS,
            pts=620,
            global_ranking=None,
            tier=TierEnum.AMATEUR,
            registration_tier=TierEnum.AMATEUR,
            last_updated=utc(2026, 2, 15, 10, 0),
            personal_best=None,
            current_streak=0,
            best_streak=0,
        ),
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
    skill_dna={
        "padel": SportSkillDna(
            serve=SkillAxisData(positive=5, negative=2, score=71),
            power=SkillAxisData(positive=4, negative=3, score=57),
            net_play=SkillAxisData(positive=6, negative=1, score=86),
            stamina=SkillAxisData(positive=3, negative=2, score=60),
            mental=SkillAxisData(positive=4, negative=1, score=80),
            total_reflections=8,
            last_updated=utc(2026, 2, 20, 14, 0),
        ),
        "tennis": SportSkillDna(
            serve=SkillAxisData(positive=3, negative=3, score=50),
            power=SkillAxisData(positive=2, negative=1, score=67),
            net_play=SkillAxisData(positive=1, negative=2, score=33),
            stamina=SkillAxisData(positive=3, negative=1, score=75),
            mental=SkillAxisData(positive=2, negative=2, score=50),
            total_reflections=5,
            last_updated=utc(2026, 2, 15, 10, 0),
        ),
    },
)

USER_ALICE = PrivateUserProfile(
    uid="user_alice",
    name="Alice",
    email="alice@example.com",
    phone="+301122334455",
    profile_url=None,
    rankings=PerSportRankings(
        tennis=SportRanking(
            sport=SportEnum.TENNIS,
            pts=820,
            global_ranking=340,
            tier=TierEnum.AMATEUR,
            registration_tier=TierEnum.AMATEUR,
            last_updated=utc(2026, 2, 18, 9, 30),
            personal_best=820,
            current_streak=3,
            best_streak=3,
        ),
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
    skill_dna={
        "tennis": SportSkillDna(
            serve=SkillAxisData(positive=6, negative=1, score=86),
            power=SkillAxisData(positive=5, negative=2, score=71),
            net_play=SkillAxisData(positive=4, negative=2, score=67),
            stamina=SkillAxisData(positive=5, negative=1, score=83),
            mental=SkillAxisData(positive=4, negative=3, score=57),
            total_reflections=7,
            last_updated=utc(2026, 2, 18, 9, 30),
        ),
    },
)

USER_BOB = PrivateUserProfile(
    uid="user_bob",
    name="Bob",
    email="bob@example.com",
    phone=None,
    profile_url="http://example.com/bob.png",
    rankings=PerSportRankings(
        padel=SportRanking(
            sport=SportEnum.PADEL,
            pts=540,
            global_ranking=None,
            tier=TierEnum.AMATEUR,
            registration_tier=TierEnum.AMATEUR,
            last_updated=utc(2026, 2, 10, 16, 0),
            personal_best=560,
            current_streak=1,
            best_streak=2,
        ),
        pickleball=SportRanking(
            sport=SportEnum.PICKLEBALL,
            pts=300,
            global_ranking=None,
            tier=TierEnum.AMATEUR,
            registration_tier=TierEnum.AMATEUR,
            last_updated=utc(2026, 1, 25, 11, 0),
            personal_best=None,
            current_streak=0,
            best_streak=0,
        ),
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
    skill_dna={
        "padel": SportSkillDna(
            serve=SkillAxisData(positive=2, negative=3, score=40),
            power=SkillAxisData(positive=3, negative=2, score=60),
            net_play=SkillAxisData(positive=2, negative=2, score=50),
            stamina=SkillAxisData(positive=1, negative=3, score=25),
            mental=SkillAxisData(positive=2, negative=1, score=67),
            total_reflections=6,
            last_updated=utc(2026, 2, 10, 16, 0),
        ),
        "pickleball": SportSkillDna(
            serve=SkillAxisData(positive=1, negative=1, score=50),
            power=SkillAxisData(positive=1, negative=0, score=100),
            net_play=SkillAxisData(positive=2, negative=1, score=67),
            stamina=SkillAxisData(positive=1, negative=1, score=50),
            mental=SkillAxisData(positive=0, negative=1, score=0),
            total_reflections=3,
            last_updated=utc(2026, 1, 25, 11, 0),
        ),
    },
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

LEAGUE_TENNIS_COMPLETED = League(
    league_id="tennis-completed-2024",
    name="Tennis Series 2024",
    sport=SportEnum.TENNIS,
    season="Autumn 2024",
    status=LeagueStatusEnum.COMPLETED,
    owner_uid=USER_ALICE.uid,
    meta=None,
)

SAMPLE_LEAGUES = [LEAGUE_PADEL_LOCAL, LEAGUE_TENNIS_LOCAL, LEAGUE_TENNIS_COMPLETED]

PRIMARY_USER_UID = USER_IGNATIOS.uid
PRIMARY_LEAGUE_ID = LEAGUE_PADEL_LOCAL.league_id

USER_IGNATIOS.leagues_active = [
    LeagueSummary(
        league_id=LEAGUE_PADEL_LOCAL.league_id,
        name=LEAGUE_PADEL_LOCAL.name,
        sport=LEAGUE_PADEL_LOCAL.sport,
        status=LEAGUE_PADEL_LOCAL.status,
        role=None,
    )
]
USER_IGNATIOS.leagues_completed = [
    LeagueSummary(
        league_id=LEAGUE_TENNIS_COMPLETED.league_id,
        name=LEAGUE_TENNIS_COMPLETED.name,
        sport=LEAGUE_TENNIS_COMPLETED.sport,
        status=LEAGUE_TENNIS_COMPLETED.status,
        role=None,
    )
]

# --- Matches ---
# A small set of matches with varied statuses; participant_uids align to SAMPLE_USERS.
MATCH_UPCOMING_1 = Match(
    match_id="match-upcoming-1",
    sport=SportEnum.PADEL,
    status=MatchStatusEnum.SCHEDULED,
    scheduled_at=utc(2030, 1, 10, 10, 0),
    league_id=LEAGUE_PADEL_LOCAL.league_id,
    court_id="court-1",
    score=None,
    result_by_user=None,
    participants=[
        MatchParticipant(uid=USER_IGNATIOS.uid, role=ParticipantRoleEnum.PLAYER, team=None),
        MatchParticipant(uid=USER_BOB.uid, role=ParticipantRoleEnum.PLAYER, team=None),
    ],
    participant_uids=[USER_IGNATIOS.uid, USER_BOB.uid],
    participant_pair=compute_participant_pair([USER_IGNATIOS.uid, USER_BOB.uid]),
)

MATCH_UPCOMING_2 = Match(
    match_id="match-upcoming-2",
    sport=SportEnum.PADEL,
    status=MatchStatusEnum.SCHEDULED,
    scheduled_at=utc(2030, 1, 15, 10, 0),
    league_id=LEAGUE_PADEL_LOCAL.league_id,
    court_id="court-2",
    score=None,
    result_by_user=None,
    participants=[
        MatchParticipant(uid=USER_IGNATIOS.uid, role=ParticipantRoleEnum.PLAYER, team=None),
        MatchParticipant(uid=USER_ALICE.uid, role=ParticipantRoleEnum.PLAYER, team=None),
    ],
    participant_uids=[USER_IGNATIOS.uid, USER_ALICE.uid],
    participant_pair=compute_participant_pair([USER_IGNATIOS.uid, USER_ALICE.uid]),
)

MATCH_PENDING = Match(
    match_id="match_pending",
    sport=SportEnum.TENNIS,
    status=MatchStatusEnum.PENDING_CONFIRMATION,
    scheduled_at=utc(2030, 2, 1, 17, 0),
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
    participant_pair=compute_participant_pair([USER_ALICE.uid, USER_IGNATIOS.uid]),
)

MATCH_COMPLETED_1 = Match(
    match_id="match-completed-1",
    sport=SportEnum.PADEL,
    status=MatchStatusEnum.COMPLETED,
    scheduled_at=utc(2020, 1, 20, 18, 0),
    finished_at=utc(2020, 1, 20, 20, 15),
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
    participant_pair=compute_participant_pair([USER_IGNATIOS.uid, USER_BOB.uid]),
)

MATCH_COMPLETED_2 = Match(
    match_id="match-completed-2",
    sport=SportEnum.PADEL,
    status=MatchStatusEnum.COMPLETED,
    scheduled_at=utc(2020, 1, 10, 18, 30),
    finished_at=utc(2020, 1, 10, 19, 50),
    league_id=LEAGUE_PADEL_LOCAL.league_id,
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
    participant_pair=compute_participant_pair([USER_ALICE.uid, USER_IGNATIOS.uid]),
)

SAMPLE_MATCHES = [
    MATCH_UPCOMING_1,
    MATCH_UPCOMING_2,
    MATCH_PENDING,
    MATCH_COMPLETED_1,
    MATCH_COMPLETED_2,
]

# --- Journal entries ---
# Basic journal entries tied to completed matches.
JOURNAL_1 = JournalEntry(
    entry_id="journal_1",
    uid=USER_IGNATIOS.uid,
    created_at=utc(2020, 1, 21, 9, 0),
    title="Padel win reflections",
    body="Worked on volleys; need to improve serve consistency.",
    tags=["padel", "volley", "serve"],
    match_id=MATCH_COMPLETED_1.match_id,
    sport=SportEnum.PADEL,
    visibility=JournalVisibilityEnum.PRIVATE,
)

JOURNAL_2 = JournalEntry(
    entry_id="journal_2",
    uid=USER_ALICE.uid,
    created_at=utc(2020, 1, 11, 8, 30),
    title="Padel match recap",
    body="Worked on positioning and volleys.",
    tags=["padel", "positioning"],
    match_id=MATCH_COMPLETED_2.match_id,
    sport=SportEnum.PADEL,
    visibility=JournalVisibilityEnum.PRIVATE,
)

SAMPLE_JOURNAL_ENTRIES = [JOURNAL_1, JOURNAL_2]

# --- Tier config ---
# --- Point history ---
# Sample point history entries per user, showing pts progression over time.
# pts = new total after the match; delta = change applied.
POINT_HISTORY_IGNATIOS: list[PointHistoryEntry] = [
    PointHistoryEntry(
        entry_id="ph_ignatios_padel_1",
        sport=SportEnum.PADEL,
        pts=835,
        delta=35,
        reason=PointHistoryReasonEnum.MATCH_WIN,
        match_id="match-completed-hist-1",
        opponent_uid=USER_BOB.uid,
        opponent_pts_before=580,
        league_id=LEAGUE_PADEL_LOCAL.league_id,
        created_at=utc(2026, 1, 5),
        tier_before=TierEnum.AMATEUR,
        tier_after=TierEnum.AMATEUR,
    ),
    PointHistoryEntry(
        entry_id="ph_ignatios_padel_2",
        sport=SportEnum.PADEL,
        pts=875,
        delta=40,
        reason=PointHistoryReasonEnum.MATCH_WIN,
        match_id="match-completed-hist-2",
        opponent_uid=USER_BOB.uid,
        opponent_pts_before=555,
        league_id=LEAGUE_PADEL_LOCAL.league_id,
        created_at=utc(2026, 1, 12),
        tier_before=TierEnum.AMATEUR,
        tier_after=TierEnum.AMATEUR,
    ),
    PointHistoryEntry(
        entry_id="ph_ignatios_padel_3",
        sport=SportEnum.PADEL,
        pts=855,
        delta=-20,
        reason=PointHistoryReasonEnum.MATCH_LOSS,
        match_id="match-completed-hist-3",
        opponent_uid=USER_ALICE.uid,
        opponent_pts_before=810,
        league_id=LEAGUE_PADEL_LOCAL.league_id,
        created_at=utc(2026, 1, 20),
        tier_before=TierEnum.AMATEUR,
        tier_after=TierEnum.AMATEUR,
    ),
    PointHistoryEntry(
        entry_id="ph_ignatios_padel_4",
        sport=SportEnum.PADEL,
        pts=900,
        delta=45,
        reason=PointHistoryReasonEnum.MATCH_WIN,
        match_id="match-completed-hist-4",
        opponent_uid=USER_BOB.uid,
        opponent_pts_before=540,
        league_id=LEAGUE_PADEL_LOCAL.league_id,
        created_at=utc(2026, 2, 5),
        tier_before=TierEnum.AMATEUR,
        tier_after=TierEnum.AMATEUR,
    ),
    PointHistoryEntry(
        entry_id="ph_ignatios_padel_5",
        sport=SportEnum.PADEL,
        pts=980,
        delta=80,
        reason=PointHistoryReasonEnum.MATCH_WIN,
        match_id="match-completed-hist-5",
        opponent_uid=USER_ALICE.uid,
        opponent_pts_before=850,
        league_id=LEAGUE_PADEL_LOCAL.league_id,
        created_at=utc(2026, 2, 20, 14, 0),
        tier_before=TierEnum.AMATEUR,
        tier_after=TierEnum.AMATEUR,
    ),
]

POINT_HISTORY_ALICE: list[PointHistoryEntry] = [
    PointHistoryEntry(
        entry_id="ph_alice_tennis_1",
        sport=SportEnum.TENNIS,
        pts=770,
        delta=30,
        reason=PointHistoryReasonEnum.MATCH_WIN,
        match_id="match-completed-hist-6",
        opponent_uid=USER_IGNATIOS.uid,
        opponent_pts_before=640,
        league_id=LEAGUE_TENNIS_LOCAL.league_id,
        created_at=utc(2026, 1, 15),
        tier_before=TierEnum.AMATEUR,
        tier_after=TierEnum.AMATEUR,
    ),
    PointHistoryEntry(
        entry_id="ph_alice_tennis_2",
        sport=SportEnum.TENNIS,
        pts=795,
        delta=25,
        reason=PointHistoryReasonEnum.MATCH_WIN,
        match_id="match-completed-hist-7",
        opponent_uid=USER_IGNATIOS.uid,
        opponent_pts_before=630,
        league_id=LEAGUE_TENNIS_LOCAL.league_id,
        created_at=utc(2026, 2, 1),
        tier_before=TierEnum.AMATEUR,
        tier_after=TierEnum.AMATEUR,
    ),
    PointHistoryEntry(
        entry_id="ph_alice_tennis_3",
        sport=SportEnum.TENNIS,
        pts=820,
        delta=25,
        reason=PointHistoryReasonEnum.MATCH_WIN,
        match_id="match-completed-hist-8",
        opponent_uid=USER_IGNATIOS.uid,
        opponent_pts_before=620,
        league_id=LEAGUE_TENNIS_LOCAL.league_id,
        created_at=utc(2026, 2, 18, 9, 30),
        tier_before=TierEnum.AMATEUR,
        tier_after=TierEnum.AMATEUR,
    ),
]

POINT_HISTORY_BOB: list[PointHistoryEntry] = [
    PointHistoryEntry(
        entry_id="ph_bob_padel_1",
        sport=SportEnum.PADEL,
        pts=520,
        delta=20,
        reason=PointHistoryReasonEnum.MATCH_WIN,
        match_id="match-completed-hist-9",
        opponent_uid=USER_IGNATIOS.uid,
        opponent_pts_before=900,
        league_id=LEAGUE_PADEL_LOCAL.league_id,
        created_at=utc(2026, 1, 10),
        tier_before=TierEnum.AMATEUR,
        tier_after=TierEnum.AMATEUR,
    ),
    PointHistoryEntry(
        entry_id="ph_bob_padel_2",
        sport=SportEnum.PADEL,
        pts=560,
        delta=40,
        reason=PointHistoryReasonEnum.MATCH_WIN,
        match_id="match-completed-hist-10",
        opponent_uid=USER_IGNATIOS.uid,
        opponent_pts_before=880,
        league_id=LEAGUE_PADEL_LOCAL.league_id,
        created_at=utc(2026, 1, 18),
        tier_before=TierEnum.AMATEUR,
        tier_after=TierEnum.AMATEUR,
    ),
    PointHistoryEntry(
        entry_id="ph_bob_padel_3",
        sport=SportEnum.PADEL,
        pts=510,
        delta=-50,
        reason=PointHistoryReasonEnum.MATCH_LOSS,
        match_id="match-completed-hist-11",
        opponent_uid=USER_IGNATIOS.uid,
        opponent_pts_before=855,
        league_id=LEAGUE_PADEL_LOCAL.league_id,
        created_at=utc(2026, 1, 25),
        tier_before=TierEnum.AMATEUR,
        tier_after=TierEnum.AMATEUR,
    ),
    PointHistoryEntry(
        entry_id="ph_bob_padel_4",
        sport=SportEnum.PADEL,
        pts=540,
        delta=30,
        reason=PointHistoryReasonEnum.MATCH_WIN,
        match_id="match-completed-hist-12",
        opponent_uid=USER_ALICE.uid,
        opponent_pts_before=800,
        league_id=LEAGUE_PADEL_LOCAL.league_id,
        created_at=utc(2026, 2, 10, 16, 0),
        tier_before=TierEnum.AMATEUR,
        tier_after=TierEnum.AMATEUR,
    ),
]

SAMPLE_POINT_HISTORY: list[tuple[str, list[PointHistoryEntry]]] = [
    (USER_IGNATIOS.uid, POINT_HISTORY_IGNATIOS),
    (USER_ALICE.uid, POINT_HISTORY_ALICE),
    (USER_BOB.uid, POINT_HISTORY_BOB),
]

# --- Skill taxonomy ---
SKILL_TAXONOMY = SkillTaxonomy(
    axes=["serve", "power", "net_play", "stamina", "mental"],
    tag_map={
        "first_serve": "serve",
        "double_faults": "serve",
        "ace": "serve",
        "forehand_winner": "power",
        "backhand_winner": "power",
        "net_approach": "net_play",
        "volley": "net_play",
        "endurance": "stamina",
        "fitness": "stamina",
        "concentration": "mental",
        "composure": "mental",
        "tiebreak": "mental",
    },
    version=1,
)

# --- Tier config ---
TIER_CONFIG = TierConfig(
    thresholds=[
        TierThreshold(
            tier=TierEnum.AMATEUR,
            min_pts=1000,
            max_pts=1999,
            label="Amateur",
            color="#8B8B8B",
        ),
        TierThreshold(
            tier=TierEnum.INTERMEDIATE,
            min_pts=2000,
            max_pts=2999,
            label="Intermediate",
            color="#00A3CC",
        ),
        TierThreshold(
            tier=TierEnum.ADVANCED,
            min_pts=3000,
            max_pts=3999,
            label="Advanced",
            color="#BFFF00",
        ),
        TierThreshold(
            tier=TierEnum.COMPETITIVE,
            min_pts=4000,
            max_pts=None,
            label="Competitive",
            color="#FF6B35",
        ),
    ],
    version=1,
    updated_at=utc(2026, 1, 1),
)

# --- Region config (config/regions) ---
# Maps area codes to named regions for leaderboard grouping.
# Area codes align with preferences.area on seeded users:
#   user_ignatios: area=101 -> athens
#   user_alice:    area=202 -> thessaloniki
#   user_bob:      area=303 -> london
REGION_MAPPING: dict[str, str] = {
    "101": "athens",
    "102": "athens",
    "201": "thessaloniki",
    "202": "thessaloniki",
    "303": "london",
}

# --- Leaderboard snapshots (leaderboards/{region}_{sport}) ---
# Pre-populated leaderboard data for testing.
# Region and pts values align with each user's preferences.area and rankings:
LEADERBOARD_ATHENS_TENNIS = LeaderboardSnapshot(
    region="athens",
    sport=SportEnum.TENNIS,
    entries=[
        LeaderboardEntry(
            uid="user_ignatios",
            name="Ignatios",
            pts=620,
            tier=TierEnum.AMATEUR,
            rank=1,
            delta7d=50,
        ),
    ],
    rising_stars=[],
    last_updated=utc(2026, 3, 1, 12, 0),
)

LEADERBOARD_ATHENS_PADEL = LeaderboardSnapshot(
    region="athens",
    sport=SportEnum.PADEL,
    entries=[
        LeaderboardEntry(
            uid="user_ignatios",
            name="Ignatios",
            pts=980,
            tier=TierEnum.AMATEUR,
            rank=1,
            delta7d=100,
        ),
    ],
    rising_stars=[],
    last_updated=utc(2026, 3, 1, 12, 0),
)

LEADERBOARD_THESSALONIKI_TENNIS = LeaderboardSnapshot(
    region="thessaloniki",
    sport=SportEnum.TENNIS,
    entries=[
        LeaderboardEntry(
            uid="user_alice",
            name="Alice",
            pts=820,
            tier=TierEnum.AMATEUR,
            rank=1,
            delta7d=30,
        ),
    ],
    rising_stars=[],
    last_updated=utc(2026, 3, 1, 12, 0),
)

SAMPLE_LEADERBOARDS = [
    LEADERBOARD_ATHENS_TENNIS,
    LEADERBOARD_ATHENS_PADEL,
    LEADERBOARD_THESSALONIKI_TENNIS,
]

# --- Tier averages (config/tierAverages) ---
# Pre-computed average Skill DNA per tier, powers the "Show Next Level" radar comparison.
# Shape: {tier: {sport: {axis: score, ...}, ...}, ...}
TIER_AVERAGES: dict[str, dict[str, dict[str, int]]] = {
    "amateur": {
        "tennis": {"serve": 40, "power": 35, "net_play": 30, "stamina": 45, "mental": 38},
        "padel": {"serve": 38, "power": 32, "net_play": 42, "stamina": 40, "mental": 35},
        "pickleball": {"serve": 42, "power": 30, "net_play": 45, "stamina": 38, "mental": 40},
    },
    "intermediate": {
        "tennis": {"serve": 58, "power": 52, "net_play": 48, "stamina": 60, "mental": 55},
        "padel": {"serve": 55, "power": 50, "net_play": 58, "stamina": 56, "mental": 52},
        "pickleball": {"serve": 56, "power": 48, "net_play": 60, "stamina": 55, "mental": 54},
    },
    "advanced": {
        "tennis": {"serve": 72, "power": 68, "net_play": 65, "stamina": 75, "mental": 70},
        "padel": {"serve": 70, "power": 65, "net_play": 73, "stamina": 72, "mental": 68},
        "pickleball": {"serve": 71, "power": 64, "net_play": 74, "stamina": 70, "mental": 69},
    },
    "competitive": {
        "tennis": {"serve": 88, "power": 85, "net_play": 82, "stamina": 90, "mental": 87},
        "padel": {"serve": 86, "power": 83, "net_play": 88, "stamina": 87, "mental": 84},
        "pickleball": {"serve": 87, "power": 82, "net_play": 89, "stamina": 86, "mental": 85},
    },
}

# --- Scouting profiles (scouting/{uid}) ---
# Pre-populated opponent-sourced scouting data for sample users.
# Tags align with the skill taxonomy axes (serve, power, net_play, stamina, mental).
SCOUTING_IGNATIOS = ScoutingProfile(
    uid="user_ignatios",
    padel=ScoutingSportData(
        weak={
            "serve": ScoutingTagCount(count=3, last_reported=utc(2026, 2, 18)),
            "stamina": ScoutingTagCount(count=2, last_reported=utc(2026, 2, 10)),
        },
        strong={
            "net_play": ScoutingTagCount(count=5, last_reported=utc(2026, 2, 20)),
            "mental": ScoutingTagCount(count=3, last_reported=utc(2026, 2, 15)),
        },
        total_reports=4,
        unique_reporters=2,
        last_updated=utc(2026, 2, 20),
    ),
    tennis=ScoutingSportData(
        weak={
            "net_play": ScoutingTagCount(count=2, last_reported=utc(2026, 2, 12)),
        },
        strong={
            "stamina": ScoutingTagCount(count=3, last_reported=utc(2026, 2, 15)),
        },
        total_reports=3,
        unique_reporters=2,
        last_updated=utc(2026, 2, 15),
    ),
)

SCOUTING_ALICE = ScoutingProfile(
    uid="user_alice",
    tennis=ScoutingSportData(
        weak={
            "mental": ScoutingTagCount(count=2, last_reported=utc(2026, 2, 16)),
        },
        strong={
            "serve": ScoutingTagCount(count=4, last_reported=utc(2026, 2, 18)),
            "power": ScoutingTagCount(count=3, last_reported=utc(2026, 2, 14)),
        },
        total_reports=3,
        unique_reporters=1,
        last_updated=utc(2026, 2, 18),
    ),
)

SCOUTING_BOB = ScoutingProfile(
    uid="user_bob",
    padel=ScoutingSportData(
        weak={
            "stamina": ScoutingTagCount(count=4, last_reported=utc(2026, 2, 8)),
            "serve": ScoutingTagCount(count=2, last_reported=utc(2026, 1, 28)),
        },
        strong={
            "power": ScoutingTagCount(count=3, last_reported=utc(2026, 2, 10)),
        },
        total_reports=3,
        unique_reporters=2,
        last_updated=utc(2026, 2, 10),
    ),
)

SAMPLE_SCOUTING_PROFILES = [SCOUTING_IGNATIOS, SCOUTING_ALICE, SCOUTING_BOB]

# --- Ticker events (ticker/{auto-id}) ---
# Sample ticker events for all Tab 4 (Local Pulse) event types.
# expiresAt is set far in the future so they remain visible in manual testing.
# Events span multiple regions (athens, thessaloniki, london) and sports.
SAMPLE_TICKER_EVENTS = [
    # --- upset events ---
    TickerEvent(
        event_id="ticker_upset_1",
        type=TickerEventTypeEnum.UPSET,
        sport=SportEnum.TENNIS,
        region="athens",
        created_at=utc(2026, 3, 1, 14, 30),
        expires_at=utc(2027, 3, 1, 14, 30),
        winner_uid="user_ignatios",
        winner_name="Ignatios",
        loser_tier=TierEnum.ADVANCED,
        delta=200,
    ),
    # --- personal_best events (3 total, different users & sports) ---
    TickerEvent(
        event_id="ticker_pb_1",
        type=TickerEventTypeEnum.PERSONAL_BEST,
        sport=SportEnum.PADEL,
        region="athens",
        created_at=utc(2026, 3, 1, 9, 0),
        expires_at=utc(2027, 3, 1, 9, 0),
        user_uid="user_ignatios",
        user_name="Ignatios",
        new_pts=1050,
        previous_best=980,
    ),
    TickerEvent(
        event_id="ticker_pb_2",
        type=TickerEventTypeEnum.PERSONAL_BEST,
        sport=SportEnum.TENNIS,
        region="thessaloniki",
        created_at=utc(2026, 3, 1, 11, 15),
        expires_at=utc(2027, 3, 1, 11, 15),
        user_uid="user_alice",
        user_name="Alice",
        new_pts=870,
        previous_best=820,
    ),
    TickerEvent(
        event_id="ticker_pb_3",
        type=TickerEventTypeEnum.PERSONAL_BEST,
        sport=SportEnum.PICKLEBALL,
        region="london",
        created_at=utc(2026, 3, 1, 8, 45),
        expires_at=utc(2027, 3, 1, 8, 45),
        user_uid="user_bob",
        user_name="Bob",
        new_pts=350,
        previous_best=300,
    ),
    # --- win_streak events (3 total, at milestone levels 3, 5, 10) ---
    TickerEvent(
        event_id="ticker_streak_1",
        type=TickerEventTypeEnum.WIN_STREAK,
        sport=SportEnum.TENNIS,
        region="athens",
        created_at=utc(2026, 3, 1, 10, 0),
        expires_at=utc(2027, 3, 1, 10, 0),
        user_uid="user_alice",
        user_name="Alice",
        streak=5,
    ),
    TickerEvent(
        event_id="ticker_streak_2",
        type=TickerEventTypeEnum.WIN_STREAK,
        sport=SportEnum.PADEL,
        region="london",
        created_at=utc(2026, 3, 1, 13, 20),
        expires_at=utc(2027, 3, 1, 13, 20),
        user_uid="user_bob",
        user_name="Bob",
        streak=3,
    ),
    TickerEvent(
        event_id="ticker_streak_3",
        type=TickerEventTypeEnum.WIN_STREAK,
        sport=SportEnum.PADEL,
        region="athens",
        created_at=utc(2026, 3, 1, 15, 0),
        expires_at=utc(2027, 3, 1, 15, 0),
        user_uid="user_ignatios",
        user_name="Ignatios",
        streak=10,
    ),
    TickerEvent(
        event_id="ticker_streak_4",
        type=TickerEventTypeEnum.WIN_STREAK,
        sport=SportEnum.TENNIS,
        region="thessaloniki",
        created_at=utc(2026, 3, 1, 17, 30),
        expires_at=utc(2027, 3, 1, 17, 30),
        user_uid="user_alice",
        user_name="Alice",
        streak=20,
    ),
    # --- tier_crossed events (2 total: one promotion, one relegation) ---
    TickerEvent(
        event_id="ticker_tier_1",
        type=TickerEventTypeEnum.TIER_CROSSED,
        sport=SportEnum.TENNIS,
        region="thessaloniki",
        created_at=utc(2026, 3, 1, 12, 0),
        expires_at=utc(2027, 3, 1, 12, 0),
        user_uid="user_alice",
        user_name="Alice",
        tier_before=TierEnum.AMATEUR,
        tier_after=TierEnum.INTERMEDIATE,
        direction="up",
    ),
    TickerEvent(
        event_id="ticker_tier_2",
        type=TickerEventTypeEnum.TIER_CROSSED,
        sport=SportEnum.PADEL,
        region="london",
        created_at=utc(2026, 3, 1, 16, 30),
        expires_at=utc(2027, 3, 1, 16, 30),
        user_uid="user_bob",
        user_name="Bob",
        tier_before=TierEnum.INTERMEDIATE,
        tier_after=TierEnum.AMATEUR,
        direction="down",
    ),
]
