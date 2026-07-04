from datetime import datetime, timedelta, timezone

from app.models import (
    CursorBundle,
    DivisionConfig,
    JournalEntry,
    JournalEntrySummary,
    LeaderboardEntry,
    LeaderboardSnapshot,
    League,
    LeagueMember,
    LeagueMemberStatusEnum,
    LeagueRoleEnum,
    LeagueSummary,
    LeagueStatusEnum,
    LevelEnum,
    Match,
    MatchOpponentSummary,
    MatchParticipant,
    MatchResultEnum,
    MatchScore,
    MatchStatusEnum,
    MatchTypeEnum,
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
            pts=1020,
            global_ranking=120,
            tier=TierEnum.AMATEUR,
            registration_tier=TierEnum.AMATEUR,
            last_updated=utc(2026, 2, 20, 14, 0),
            personal_best=1020,
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

USER_DIANA = PrivateUserProfile(
    uid="user_diana",
    name="Diana",
    email="diana@example.com",
    phone=None,
    profile_url=None,
    rankings=PerSportRankings(
        padel=SportRanking(
            sport=SportEnum.PADEL,
            pts=710,
            global_ranking=None,
            tier=TierEnum.AMATEUR,
            registration_tier=TierEnum.AMATEUR,
            last_updated=utc(2020, 6, 1, 18, 0),
            personal_best=710,
            current_streak=1,
            best_streak=1,
        ),
    ),
    preferences=UserPreferences(
        area=101,
        levels=PerSportLevels(padel=LevelEnum.INTERMEDIATE),
        sports=[SportEnum.PADEL],
    ),
    leagues_active=[],
    leagues_completed=[],
    upcoming_matches=[],
    completed_matches=[],
    journal_recent=[],
    cursors=None,
    skill_dna={
        "padel": SportSkillDna(
            serve=SkillAxisData(positive=3, negative=2, score=60),
            power=SkillAxisData(positive=4, negative=1, score=80),
            net_play=SkillAxisData(positive=3, negative=2, score=60),
            stamina=SkillAxisData(positive=4, negative=1, score=80),
            mental=SkillAxisData(positive=3, negative=1, score=75),
            total_reflections=4,
            last_updated=utc(2020, 6, 1, 18, 0),
        ),
    },
)


def _padel_seed_user(uid: str, name: str, pts: int) -> PrivateUserProfile:
    return PrivateUserProfile(
        uid=uid,
        name=name,
        email=f"{uid}@example.com",
        phone=None,
        profile_url=None,
        rankings=PerSportRankings(
            padel=SportRanking(
                sport=SportEnum.PADEL,
                pts=pts,
                global_ranking=None,
                tier=TierEnum.AMATEUR,
                registration_tier=TierEnum.AMATEUR,
                last_updated=utc(2026, 3, 1, 12, 0),
                personal_best=pts,
                current_streak=0,
                best_streak=0,
            )
        ),
        preferences=UserPreferences(
            area=101,
            levels=PerSportLevels(padel=LevelEnum.INTERMEDIATE),
            sports=[SportEnum.PADEL],
        ),
        leagues_active=[],
        leagues_completed=[],
        upcoming_matches=[],
        completed_matches=[],
        journal_recent=[],
        cursors=None,
        skill_dna=None,
    )


USER_ELENA = _padel_seed_user("user_elena", "Elena", 1380)
USER_FOTIS = _padel_seed_user("user_fotis", "Fotis", 1250)
USER_GIANNIS = _padel_seed_user("user_giannis", "Giannis", 1110)
USER_HELEN = _padel_seed_user("user_helen", "Helen", 870)

SAMPLE_USERS = [
    USER_IGNATIOS,
    USER_ALICE,
    USER_BOB,
    USER_DIANA,
    USER_ELENA,
    USER_FOTIS,
    USER_GIANNIS,
    USER_HELEN,
]

# --- Broadcasts ---
# Sample active broadcasts for testing GET /me/discovery.
# Written as raw Firestore dicts (camelCase) because broadcasts are
# created by the service and stored in camelCase format.
# user_alice: HAVE_COURT padel broadcast with venue reference
_NOW = datetime.now(timezone.utc)
BROADCAST_ALICE_PADEL: dict = {
    "ownerUid": USER_ALICE.uid,
    "ownerName": USER_ALICE.name,
    "ownerRanking": None,
    "sport": "padel",
    "matchType": "singles",
    "broadcastType": "find_opponent",
    "partnerUid": None,
    "availability": "today",
    "courtStatus": "have_court",
    "courtLocation": "Glyfada Padel Club",
    "venueRef": {
        "venueId": "venue_glyfada_padel",
        "placeId": None,
        "name": "Glyfada Padel Club",
        "coordinates": {"lat": 37.8788, "lng": 23.7537},
    },
    "status": "active",
    "expiresAt": _NOW + timedelta(days=7),
    "createdAt": _NOW,
    "location": {"area": None, "geo": None, "radiusKm": None},
}

# user_bob: NEED_COURT padel broadcast with area=101 (→ "athens" via region config)
BROADCAST_BOB_PADEL: dict = {
    "ownerUid": USER_BOB.uid,
    "ownerName": USER_BOB.name,
    "ownerRanking": None,
    "sport": "padel",
    "matchType": "singles",
    "broadcastType": "find_opponent",
    "partnerUid": None,
    "availability": "weekend",
    "courtStatus": "need_court",
    "courtLocation": None,
    "venueRef": None,
    "status": "active",
    "expiresAt": _NOW + timedelta(days=7),
    "createdAt": _NOW - timedelta(minutes=5),
    "location": {"area": 101, "geo": None, "radiusKm": None},
}

SAMPLE_BROADCASTS: list[tuple[str, dict]] = [
    ("broadcast_seed_alice_padel", BROADCAST_ALICE_PADEL),
    ("broadcast_seed_bob_padel", BROADCAST_BOB_PADEL),
]

# --- Leagues ---
# Sample leagues referencing the users above.
LEAGUE_PADEL_LOCAL = League(
    league_id="padel-local-2025",
    name="Local Padel Ladder 2025",
    sport=SportEnum.PADEL,
    season="Autumn 2025",
    status=LeagueStatusEnum.ACTIVE,
    owner_uid=USER_IGNATIOS.uid,
    region="athens",
    max_players=12,
    current_players=4,
    start_date=utc(2025, 9, 1),
    end_date=utc(2025, 11, 30),
    tier="intermediate",
    meta={},
)

LEAGUE_TENNIS_LOCAL = League(
    league_id="tennis-local-2025",
    name="Local Tennis Series 2025",
    sport=SportEnum.TENNIS,
    season="Spring 2025",
    status=LeagueStatusEnum.OPEN,
    owner_uid=USER_ALICE.uid,
    region="thessaloniki",
    max_players=16,
    current_players=2,
    start_date=utc(2025, 4, 1),
    end_date=utc(2025, 6, 30),
    tier="intermediate",
    meta=None,
)

LEAGUE_TENNIS_COMPLETED = League(
    league_id="tennis-completed-2024",
    name="Tennis Series 2024",
    sport=SportEnum.TENNIS,
    season="Autumn 2024",
    status=LeagueStatusEnum.COMPLETED,
    owner_uid=USER_ALICE.uid,
    region="thessaloniki",
    max_players=8,
    current_players=2,
    start_date=utc(2024, 9, 1),
    end_date=utc(2024, 11, 30),
    tier="advanced",
    meta=None,
)

LEAGUE_PADEL_DIVISIONS_OPEN = League(
    league_id="padel-divisions-open-2026",
    name="Padel Divisions Open 2026",
    sport=SportEnum.PADEL,
    season="Spring 2026",
    status=LeagueStatusEnum.OPEN,
    owner_uid=USER_IGNATIOS.uid,
    region="athens",
    max_players=12,
    current_players=8,
    start_date=utc(2026, 4, 1),
    end_date=utc(2026, 6, 30),
    tier="intermediate",
    division_config=DivisionConfig(target_size=6, max_divisions=None),
    meta={},
)

SAMPLE_LEAGUES = [
    LEAGUE_PADEL_LOCAL,
    LEAGUE_TENNIS_LOCAL,
    LEAGUE_TENNIS_COMPLETED,
    LEAGUE_PADEL_DIVISIONS_OPEN,
]

# --- League members (leagues/{leagueId}/members/{uid}) ---
SAMPLE_LEAGUE_MEMBERS: dict[str, list[LeagueMember]] = {
    "padel-local-2025": [
        LeagueMember(
            uid=USER_IGNATIOS.uid,
            role=LeagueRoleEnum.ADMIN,
            status=LeagueMemberStatusEnum.ACTIVE,
            joined_at=utc(2025, 8, 15),
            display_name="Ignatios",
        ),
        LeagueMember(
            uid=USER_ALICE.uid,
            role=LeagueRoleEnum.PLAYER,
            status=LeagueMemberStatusEnum.ACTIVE,
            joined_at=utc(2025, 8, 20),
            display_name="Alice",
        ),
        LeagueMember(
            uid=USER_BOB.uid,
            role=LeagueRoleEnum.PLAYER,
            status=LeagueMemberStatusEnum.ACTIVE,
            joined_at=utc(2025, 8, 22),
            display_name="Bob",
        ),
        LeagueMember(
            uid=USER_DIANA.uid,
            role=LeagueRoleEnum.PLAYER,
            status=LeagueMemberStatusEnum.ACTIVE,
            joined_at=utc(2026, 1, 10),
            display_name="Diana",
        ),
    ],
    "tennis-local-2025": [
        LeagueMember(
            uid=USER_ALICE.uid,
            role=LeagueRoleEnum.ADMIN,
            status=LeagueMemberStatusEnum.ACTIVE,
            joined_at=utc(2025, 3, 15),
            display_name="Alice",
        ),
        LeagueMember(
            uid=USER_IGNATIOS.uid,
            role=LeagueRoleEnum.PLAYER,
            status=LeagueMemberStatusEnum.ACTIVE,
            joined_at=utc(2025, 3, 20),
            display_name="Ignatios",
        ),
    ],
    "tennis-completed-2024": [
        LeagueMember(
            uid=USER_ALICE.uid,
            role=LeagueRoleEnum.ADMIN,
            status=LeagueMemberStatusEnum.ACTIVE,
            joined_at=utc(2024, 8, 15),
            display_name="Alice",
        ),
        LeagueMember(
            uid=USER_IGNATIOS.uid,
            role=LeagueRoleEnum.PLAYER,
            status=LeagueMemberStatusEnum.ACTIVE,
            joined_at=utc(2024, 8, 20),
            display_name="Ignatios",
        ),
    ],
    "padel-divisions-open-2026": [
        LeagueMember(
            uid=USER_IGNATIOS.uid,
            role=LeagueRoleEnum.ADMIN,
            status=LeagueMemberStatusEnum.ACTIVE,
            joined_at=utc(2026, 3, 1),
            display_name="Ignatios",
        ),
        LeagueMember(
            uid=USER_ELENA.uid,
            role=LeagueRoleEnum.PLAYER,
            status=LeagueMemberStatusEnum.ACTIVE,
            joined_at=utc(2026, 3, 2),
            display_name="Elena",
        ),
        LeagueMember(
            uid=USER_FOTIS.uid,
            role=LeagueRoleEnum.PLAYER,
            status=LeagueMemberStatusEnum.ACTIVE,
            joined_at=utc(2026, 3, 3),
            display_name="Fotis",
        ),
        LeagueMember(
            uid=USER_GIANNIS.uid,
            role=LeagueRoleEnum.PLAYER,
            status=LeagueMemberStatusEnum.ACTIVE,
            joined_at=utc(2026, 3, 4),
            display_name="Giannis",
        ),
        LeagueMember(
            uid=USER_DIANA.uid,
            role=LeagueRoleEnum.PLAYER,
            status=LeagueMemberStatusEnum.ACTIVE,
            joined_at=utc(2026, 3, 5),
            display_name="Diana",
        ),
        LeagueMember(
            uid=USER_BOB.uid,
            role=LeagueRoleEnum.PLAYER,
            status=LeagueMemberStatusEnum.ACTIVE,
            joined_at=utc(2026, 3, 6),
            display_name="Bob",
        ),
        LeagueMember(
            uid=USER_HELEN.uid,
            role=LeagueRoleEnum.PLAYER,
            status=LeagueMemberStatusEnum.ACTIVE,
            joined_at=utc(2026, 3, 7),
            display_name="Helen",
        ),
        LeagueMember(
            uid=USER_ALICE.uid,
            role=LeagueRoleEnum.PLAYER,
            status=LeagueMemberStatusEnum.ACTIVE,
            joined_at=utc(2026, 3, 8),
            display_name="Alice",
        ),
    ],
}

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

MATCH_UPCOMING_DOUBLES = Match(
    match_id="match-upcoming-doubles",
    sport=SportEnum.PADEL,
    status=MatchStatusEnum.SCHEDULED,
    match_type=MatchTypeEnum.DOUBLES,
    scheduled_at=utc(2030, 3, 1, 10, 0),
    league_id=LEAGUE_PADEL_LOCAL.league_id,
    court_id="court-3",
    score=None,
    result_by_user=None,
    participants=[
        MatchParticipant(uid=USER_IGNATIOS.uid, role=ParticipantRoleEnum.PLAYER, team="A"),
        MatchParticipant(uid=USER_DIANA.uid, role=ParticipantRoleEnum.PLAYER, team="A"),
        MatchParticipant(uid=USER_ALICE.uid, role=ParticipantRoleEnum.PLAYER, team="B"),
        MatchParticipant(uid=USER_BOB.uid, role=ParticipantRoleEnum.PLAYER, team="B"),
    ],
    participant_uids=[USER_IGNATIOS.uid, USER_DIANA.uid, USER_ALICE.uid, USER_BOB.uid],
    participant_pair=None,
)

MATCH_COMPLETED_DOUBLES = Match(
    match_id="match-completed-doubles",
    sport=SportEnum.PADEL,
    status=MatchStatusEnum.COMPLETED,
    match_type=MatchTypeEnum.DOUBLES,
    scheduled_at=utc(2020, 6, 1, 16, 0),
    finished_at=utc(2020, 6, 1, 18, 0),
    league_id=LEAGUE_PADEL_LOCAL.league_id,
    score=MatchScore(
        sets=[
            SetScore(p1_games=6, p2_games=4),
            SetScore(p1_games=7, p2_games=5),
        ],
        winner_team="A",
    ),
    result_by_user={
        USER_IGNATIOS.uid: MatchResultEnum.WIN,
        USER_DIANA.uid: MatchResultEnum.WIN,
        USER_ALICE.uid: MatchResultEnum.LOSS,
        USER_BOB.uid: MatchResultEnum.LOSS,
    },
    participants=[
        MatchParticipant(uid=USER_IGNATIOS.uid, role=ParticipantRoleEnum.PLAYER, team="A"),
        MatchParticipant(uid=USER_DIANA.uid, role=ParticipantRoleEnum.PLAYER, team="A"),
        MatchParticipant(uid=USER_ALICE.uid, role=ParticipantRoleEnum.PLAYER, team="B"),
        MatchParticipant(uid=USER_BOB.uid, role=ParticipantRoleEnum.PLAYER, team="B"),
    ],
    participant_uids=[USER_IGNATIOS.uid, USER_DIANA.uid, USER_ALICE.uid, USER_BOB.uid],
    participant_pair=None,
)

SAMPLE_MATCHES = [
    MATCH_UPCOMING_1,
    MATCH_UPCOMING_2,
    MATCH_PENDING,
    MATCH_COMPLETED_1,
    MATCH_COMPLETED_2,
    MATCH_UPCOMING_DOUBLES,
    MATCH_COMPLETED_DOUBLES,
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
    PointHistoryEntry(
        entry_id="ph_ignatios_padel_dbl_1",
        sport=SportEnum.PADEL,
        pts=1020,
        delta=40,
        reason=PointHistoryReasonEnum.MATCH_DOUBLES_WIN,
        match_id="match-completed-doubles",
        opponent_uid=USER_ALICE.uid,
        opponent_pts_before=820,
        league_id=LEAGUE_PADEL_LOCAL.league_id,
        created_at=utc(2020, 6, 1, 18, 0),
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

POINT_HISTORY_DIANA: list[PointHistoryEntry] = [
    PointHistoryEntry(
        entry_id="ph_diana_padel_dbl_1",
        sport=SportEnum.PADEL,
        pts=710,
        delta=35,
        reason=PointHistoryReasonEnum.MATCH_DOUBLES_WIN,
        match_id="match-completed-doubles",
        opponent_uid=USER_BOB.uid,
        opponent_pts_before=540,
        league_id=LEAGUE_PADEL_LOCAL.league_id,
        created_at=utc(2020, 6, 1, 18, 0),
        tier_before=TierEnum.AMATEUR,
        tier_after=TierEnum.AMATEUR,
    ),
]

SAMPLE_POINT_HISTORY: list[tuple[str, list[PointHistoryEntry]]] = [
    (USER_IGNATIOS.uid, POINT_HISTORY_IGNATIOS),
    (USER_ALICE.uid, POINT_HISTORY_ALICE),
    (USER_BOB.uid, POINT_HISTORY_BOB),
    (USER_DIANA.uid, POINT_HISTORY_DIANA),
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

SCOUTING_DIANA = ScoutingProfile(
    uid="user_diana",
    padel=ScoutingSportData(
        weak={},
        strong={
            "power": ScoutingTagCount(count=2, last_reported=utc(2020, 6, 1)),
            "stamina": ScoutingTagCount(count=2, last_reported=utc(2020, 6, 1)),
        },
        total_reports=2,
        unique_reporters=2,
        last_updated=utc(2020, 6, 1),
    ),
)

SAMPLE_SCOUTING_PROFILES = [SCOUTING_IGNATIOS, SCOUTING_ALICE, SCOUTING_BOB, SCOUTING_DIANA]

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

# --- Demo scenario index ---
# Run `make seed-emu` to populate. Reference for what each seeded entity supports.
#
# Singles happy path:
#   match-completed-1: user_ignatios (WIN, padel, +35 pts) vs user_bob (LOSS)
#   match-completed-2: user_alice (WIN, padel) vs user_ignatios (LOSS)
#
# Doubles happy path:
#   match-completed-doubles: team A (user_ignatios + user_diana) WIN vs team B (user_alice + user_bob) LOSS
#   match-upcoming-doubles: same teams, SCHEDULED 2030-03-01, padel-local-2025
#
# Pending confirmation (score logging demo):
#   match_pending: user_alice submitted WIN (tennis), user_ignatios has not confirmed
#
# Venue browse:
#   GET /venues?sport=padel  → 16 Athens venues
#   GET /venues?sport=tennis → Athens tennis clubs
#
# Venue suggestion review:
#   venueSuggestions collection has 2 pending entries (seeded in seed_firestore.py)
#
# League browse / join:
#   GET /leagues?sport=padel&status=active → padel-local-2025 (athens, 4/12 members)
#   POST /leagues/padel-local-2025/join    → any user not yet a member can join
#
# Rankings / progression:
#   GET /me/lab/dashboard/padel as user_ignatios → 6 point history entries (incl. doubles), full skill DNA
#   GET /me/lab/dashboard/tennis as user_alice   → 3 point history entries, skill DNA
