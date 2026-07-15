from datetime import datetime, timezone

from app.models import (
    JournalVisibilityEnum,
    LeagueRoleEnum,
    LeagueStatusEnum,
    LeagueSummary,
    JournalEntry,
    Match,
    MatchParticipant,
    MatchResultEnum,
    MatchScore,
    MatchStatusEnum,
    MatchTypeEnum,
    ParticipantRoleEnum,
    PerSportLevels,
    PerSportRankings,
    PrivateUserProfile,
    SetScore,
    SportEnum,
    SportRanking,
    UserPreferences,
    LevelEnum,
    VenueStatusEnum,
    VenueSummary,
)
from app.models.common import GeoCoordinates
from tools.seed_mapping import (
    journal_entry_to_firestore_doc,
    match_to_firestore_doc,
    user_to_firestore_doc,
    venue_summary_to_firestore_doc,
)


def _utc(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


def _sample_user() -> PrivateUserProfile:
    return PrivateUserProfile(
        uid="u1",
        name="Alex",
        email="alex@example.com",
        phone=None,
        profile_url=None,
        rankings=PerSportRankings(padel=SportRanking(sport=SportEnum.PADEL, pts=100)),
        preferences=UserPreferences(
            area=1,
            levels=PerSportLevels(padel=LevelEnum.BEGINNER),
            sports=[SportEnum.PADEL],
        ),
        leagues_active=[],
        leagues_completed=[],
        upcoming_matches=[],
        completed_matches=[],
        journal_recent=[],
        cursors=None,
    )


def test_user_mapping_basic():
    doc = user_to_firestore_doc(_sample_user())
    assert doc["uid"] == "u1"
    assert doc["rankings"]["padel"]["pts"] == 100
    assert doc["preferences"]["sports"] == ["padel"]
    assert doc["preferences"]["feedOptOut"] is False


def test_user_mapping_includes_league_summary_division_id():
    user = _sample_user().model_copy(
        update={
            "leagues_active": [
                LeagueSummary(
                    league_id="league_1",
                    name="Athens League",
                    sport=SportEnum.PADEL,
                    status=LeagueStatusEnum.ACTIVE,
                    role=LeagueRoleEnum.PLAYER,
                    division_id="div-1",
                )
            ]
        }
    )

    doc = user_to_firestore_doc(user)

    assert doc["leaguesActive"][0]["divisionId"] == "div-1"


def test_match_mapping_includes_score_and_participants():
    match = Match(
        match_id="m1",
        sport=SportEnum.PADEL,
        status=MatchStatusEnum.COMPLETED,
        scheduled_at=_utc(2024, 1, 1),
        finished_at=_utc(2024, 1, 1, 1, 0),
        league_id=None,
        court_id=None,
        score=MatchScore(sets=[SetScore(p1_games=6, p2_games=4)], winner_uid="u1"),
        result_by_user={"u1": MatchResultEnum.WIN, "u2": MatchResultEnum.LOSS},
        participants=[
            MatchParticipant(uid="u1", role=ParticipantRoleEnum.PLAYER, team=None),
            MatchParticipant(uid="u2", role=ParticipantRoleEnum.PLAYER, team=None),
        ],
        participant_uids=["u1", "u2"],
    )
    doc = match_to_firestore_doc(match)
    assert doc["participants"][0]["uid"] == "u1"
    assert doc["score"]["sets"][0]["p1Games"] == 6
    assert doc["participantUids"] == ["u1", "u2"]


def test_doubles_match_mapping():
    match = Match(
        match_id="dbl1",
        sport=SportEnum.PADEL,
        status=MatchStatusEnum.COMPLETED,
        match_type=MatchTypeEnum.DOUBLES,
        participants=[
            MatchParticipant(uid="u1", role=ParticipantRoleEnum.PLAYER, team="A"),
            MatchParticipant(uid="u2", role=ParticipantRoleEnum.PLAYER, team="A"),
            MatchParticipant(uid="u3", role=ParticipantRoleEnum.PLAYER, team="B"),
            MatchParticipant(uid="u4", role=ParticipantRoleEnum.PLAYER, team="B"),
        ],
        participant_uids=["u1", "u2", "u3", "u4"],
        participant_pair=None,
        result_by_user={
            "u1": MatchResultEnum.WIN,
            "u2": MatchResultEnum.WIN,
            "u3": MatchResultEnum.LOSS,
            "u4": MatchResultEnum.LOSS,
        },
        score=MatchScore(sets=[SetScore(p1_games=6, p2_games=4)], winner_team="A"),
    )
    doc = match_to_firestore_doc(match)
    assert doc["matchType"] == "doubles"
    assert doc["participants"][0]["team"] == "A"
    assert doc["participants"][2]["team"] == "B"
    assert doc["participantPair"] is None
    assert doc["score"]["winnerTeam"] == "A"


def test_journal_mapping_basic():
    entry = JournalEntry(
        entry_id="j1",
        uid="u1",
        created_at=_utc(2024, 2, 2),
        title="Note",
        body="body",
        tags=["a"],
        match_id="m1",
        sport=SportEnum.TENNIS,
        visibility=JournalVisibilityEnum.PRIVATE,
    )
    doc = journal_entry_to_firestore_doc(entry)
    assert doc["title"] == "Note"
    assert doc["createdAt"].tzinfo is not None


def test_venue_mapping_writes_default_live_status():
    venue = VenueSummary(
        venue_id="venue_x",
        name="Test Club",
        coordinates=GeoCoordinates(lat=37.9, lng=23.7),
        area="athens",
        sports=[SportEnum.TENNIS],
    )
    doc = venue_summary_to_firestore_doc(venue)
    assert doc["status"] == "live"


def test_venue_mapping_writes_explicit_hidden_status():
    venue = VenueSummary(
        venue_id="venue_y",
        name="Not Yet Launched Club",
        coordinates=GeoCoordinates(lat=37.9, lng=23.7),
        area="lavrio",
        sports=[SportEnum.TENNIS],
        status=VenueStatusEnum.HIDDEN,
    )
    doc = venue_summary_to_firestore_doc(venue)
    assert doc["status"] == "hidden"
