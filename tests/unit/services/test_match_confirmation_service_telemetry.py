"""
Unit tests for OBS-3 telemetry events emitted by MatchConfirmationService.

Tests cover:
- score_submitted (singles + doubles, venue_present variants)
- score_confirmed (singles + doubles)
- match_disputed (singles + doubles)
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch


from app.models.common import MatchScore, SetScore
from app.models.enums import (
    MatchStatusEnum,
    MatchTypeEnum,
    SportEnum,
    TierEnum,
)
from app.models.common import GeoCoordinates, VenueRef
from app.models.match import Match, MatchParticipant, VerifyScoreRequest
from app.models.region_config import RegionConfig
from app.models.tier import TierConfig, TierThreshold
from app.repos.matches_repo import MatchesRepo
from app.repos.point_history_repo import PointHistoryRepo
from app.repos.region_config_repo import RegionConfigRepo
from app.repos.ticker_repo import TickerRepo
from app.repos.tier_config_repo import TierConfigRepo
from app.repos.users_repo import UsersRepo
from app.services.match_confirmation_service import MatchConfirmationService

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MATCH_ID = "match_telemetry_001"

WINNER_UID = "user_winner"
LOSER_UID = "user_loser"

# Doubles UIDs: Team A = A1 + A2, Team B = B1 + B2
A1 = "user_alice"
A2 = "user_ignatios"
B1 = "user_bob"
B2 = "user_charlie"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tier_config() -> TierConfig:
    return TierConfig(
        thresholds=[
            TierThreshold(
                tier=TierEnum.AMATEUR, min_pts=1000, max_pts=1999, label="A", color="#a"
            ),
            TierThreshold(
                tier=TierEnum.INTERMEDIATE,
                min_pts=2000,
                max_pts=2999,
                label="I",
                color="#b",
            ),
            TierThreshold(
                tier=TierEnum.ADVANCED,
                min_pts=3000,
                max_pts=3999,
                label="Adv",
                color="#c",
            ),
            TierThreshold(
                tier=TierEnum.COMPETITIVE,
                min_pts=4000,
                max_pts=None,
                label="C",
                color="#d",
            ),
        ],
        version=1,
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def _singles_match(
    status: MatchStatusEnum = MatchStatusEnum.SCHEDULED,
    score: MatchScore | None = None,
    court_id: str | None = None,
    venue_ref: object = None,
    result_submitted_by: list[str] | None = None,
) -> Match:
    return Match(
        match_id=MATCH_ID,
        sport=SportEnum.TENNIS,
        status=status,
        match_type=MatchTypeEnum.SINGLES,
        participant_uids=[WINNER_UID, LOSER_UID],
        participants=[
            MatchParticipant(uid=WINNER_UID, role="player"),
            MatchParticipant(uid=LOSER_UID, role="player"),
        ],
        score=score,
        court_id=court_id,
        venue_ref=venue_ref,  # type: ignore[arg-type]
        result_submitted_by=result_submitted_by or [],
    )


def _doubles_match(
    status: MatchStatusEnum = MatchStatusEnum.SCHEDULED,
    score: MatchScore | None = None,
    court_id: str | None = None,
    venue_ref: object = None,
    result_submitted_by: list[str] | None = None,
) -> Match:
    return Match(
        match_id=MATCH_ID,
        sport=SportEnum.PADEL,
        status=status,
        match_type=MatchTypeEnum.DOUBLES,
        participant_uids=[A1, A2, B1, B2],
        participants=[
            MatchParticipant(uid=A1, team="A", role="player"),
            MatchParticipant(uid=A2, team="A", role="player"),
            MatchParticipant(uid=B1, team="B", role="player"),
            MatchParticipant(uid=B2, team="B", role="player"),
        ],
        score=score,
        court_id=court_id,
        venue_ref=venue_ref,  # type: ignore[arg-type]
        result_submitted_by=result_submitted_by or [],
    )


def _make_score(winner_uid: str = WINNER_UID) -> MatchScore:
    return MatchScore(sets=[SetScore(p1_games=6, p2_games=3)], winner_uid=winner_uid)


def _make_doubles_score(winner_team: str = "A") -> MatchScore:
    return MatchScore(sets=[SetScore(p1_games=6, p2_games=3)], winner_team=winner_team)


def _make_user_snap(
    pts: int = 1500, tier: TierEnum = TierEnum.AMATEUR, area: int = 101
) -> Mock:
    snap = Mock()
    snap.to_dict.return_value = {
        "name": "Player",
        "preferences": {"area": area},
        "rankings": {
            SportEnum.TENNIS.value: {
                "pts": pts,
                "tier": tier.value,
                "registrationTier": tier.value,
                "currentStreak": 0,
                "bestStreak": 0,
            },
            SportEnum.PADEL.value: {
                "pts": pts,
                "tier": tier.value,
                "registrationTier": tier.value,
                "currentStreak": 0,
                "bestStreak": 0,
            },
        },
    }
    return snap


def _make_service(match: Match) -> tuple[MatchConfirmationService, MagicMock]:
    mock_matches_repo = Mock(spec=MatchesRepo)
    mock_matches_repo.get_by_id.return_value = match

    mock_users_repo = Mock(spec=UsersRepo)
    mock_ph_repo = Mock(spec=PointHistoryRepo)
    mock_tier_config_repo = Mock(spec=TierConfigRepo)
    mock_tier_config_repo.get.return_value = _tier_config()
    mock_ticker_repo = Mock(spec=TickerRepo)
    mock_region_config_repo = Mock(spec=RegionConfigRepo)
    mock_region_config_repo.get.return_value = RegionConfig(
        mapping={"101": "athens"}, version=1
    )

    mock_client = MagicMock()
    mock_client.transaction.return_value = MagicMock()

    # Track doc refs per (collection, doc_id)
    doc_refs: dict[tuple[str, str], MagicMock] = {}

    def _document_factory(coll: str):
        def _factory(doc_id: str) -> MagicMock:
            key = (coll, doc_id)
            if key not in doc_refs:
                ref = MagicMock(name=f"{coll}/{doc_id}")
                if coll == "users":
                    ref.get.return_value = _make_user_snap()
                doc_refs[key] = ref
            return doc_refs[key]

        return _factory

    coll_refs: dict[str, MagicMock] = {}

    def _collection(coll: str) -> MagicMock:
        ref = coll_refs.get(coll)
        if ref is None:
            ref = MagicMock(name=f"collection/{coll}")
            ref.document.side_effect = _document_factory(coll)
            coll_refs[coll] = ref
        return ref

    mock_client.collection.side_effect = _collection

    service = MatchConfirmationService(
        mock_matches_repo,
        mock_users_repo,
        mock_ph_repo,
        mock_tier_config_repo,
        mock_client,
        ticker_repo=mock_ticker_repo,
        region_config_repo=mock_region_config_repo,
    )
    return service, mock_client


def _run_patched(
    service: MatchConfirmationService, uid: str, request: VerifyScoreRequest
):
    with patch("app.services.match_confirmation_service.firestore") as mock_fs:
        mock_fs.transactional = lambda fn: fn
        mock_fs.ArrayUnion = lambda items: {"__array_union__": items}
        return service.verify_score(uid, MATCH_ID, request)


def _events_of_type(mock_emit: Mock, event: str) -> list:
    return [c for c in mock_emit.call_args_list if c.kwargs.get("event") == event]


# ---------------------------------------------------------------------------
# Tests: score_submitted (singles)
# ---------------------------------------------------------------------------


class TestScoreSubmittedSingles:
    def test_emits_score_submitted_on_first_submission(self):
        match = _singles_match(status=MatchStatusEnum.SCHEDULED)
        service, _ = _make_service(match)

        with patch(
            "app.services.match_confirmation_service.log_analytics_event"
        ) as mock_emit:
            _run_patched(service, WINNER_UID, VerifyScoreRequest(winner_uid=WINNER_UID))

        events = _events_of_type(mock_emit, "score_submitted")
        assert len(events) == 1
        kwargs = events[0].kwargs
        assert kwargs["uid"] == WINNER_UID
        assert kwargs["sport"] == SportEnum.TENNIS.value
        assert kwargs["match_type"] == MatchTypeEnum.SINGLES.value
        assert kwargs["venue_present"] is False
        assert kwargs["match_id"] == MATCH_ID

    def test_venue_present_true_when_court_id_set(self):
        match = _singles_match(status=MatchStatusEnum.SCHEDULED, court_id="court_001")
        service, _ = _make_service(match)

        with patch(
            "app.services.match_confirmation_service.log_analytics_event"
        ) as mock_emit:
            _run_patched(service, WINNER_UID, VerifyScoreRequest(winner_uid=WINNER_UID))

        events = _events_of_type(mock_emit, "score_submitted")
        assert events[0].kwargs["venue_present"] is True

    def test_venue_present_true_when_venue_ref_set(self):
        venue_ref = VenueRef(
            venue_id="venue_001",
            name="My Court",
            coordinates=GeoCoordinates(lat=37.98, lng=23.73),
        )
        match = _singles_match(status=MatchStatusEnum.SCHEDULED, venue_ref=venue_ref)
        service, _ = _make_service(match)

        with patch(
            "app.services.match_confirmation_service.log_analytics_event"
        ) as mock_emit:
            _run_patched(service, WINNER_UID, VerifyScoreRequest(winner_uid=WINNER_UID))

        events = _events_of_type(mock_emit, "score_submitted")
        assert events[0].kwargs["venue_present"] is True


# ---------------------------------------------------------------------------
# Tests: score_confirmed (singles)
# ---------------------------------------------------------------------------


class TestScoreConfirmedSingles:
    def test_emits_score_confirmed_on_confirmation(self):
        stored_score = _make_score(winner_uid=WINNER_UID)
        match = _singles_match(
            status=MatchStatusEnum.PENDING_CONFIRMATION,
            score=stored_score,
            result_submitted_by=[WINNER_UID],
        )
        service, _ = _make_service(match)

        with patch(
            "app.services.match_confirmation_service.log_analytics_event"
        ) as mock_emit:
            _run_patched(service, LOSER_UID, VerifyScoreRequest(winner_uid=WINNER_UID))

        events = _events_of_type(mock_emit, "score_confirmed")
        assert len(events) == 1
        kwargs = events[0].kwargs
        assert kwargs["uid"] == LOSER_UID
        assert kwargs["sport"] == SportEnum.TENNIS.value
        assert kwargs["match_type"] == MatchTypeEnum.SINGLES.value
        assert kwargs["match_id"] == MATCH_ID
        assert kwargs["venue_present"] is False


# ---------------------------------------------------------------------------
# Tests: match_disputed (singles)
# ---------------------------------------------------------------------------


class TestMatchDisputedSingles:
    def test_emits_match_disputed_when_winner_disagrees(self):
        # First submitter said WINNER_UID won; second submitter says LOSER_UID won
        stored_score = _make_score(winner_uid=WINNER_UID)
        match = _singles_match(
            status=MatchStatusEnum.PENDING_CONFIRMATION,
            score=stored_score,
            result_submitted_by=[WINNER_UID],
        )
        service, _ = _make_service(match)

        with patch(
            "app.services.match_confirmation_service.log_analytics_event"
        ) as mock_emit:
            # LOSER_UID disagrees: claims LOSER_UID is the winner
            _run_patched(service, LOSER_UID, VerifyScoreRequest(winner_uid=LOSER_UID))

        events = _events_of_type(mock_emit, "match_disputed")
        assert len(events) == 1
        kwargs = events[0].kwargs
        assert kwargs["uid"] == LOSER_UID
        assert kwargs["sport"] == SportEnum.TENNIS.value
        assert kwargs["match_type"] == MatchTypeEnum.SINGLES.value
        assert kwargs["match_id"] == MATCH_ID
        assert kwargs["venue_present"] is False


# ---------------------------------------------------------------------------
# Tests: score_submitted (doubles)
# ---------------------------------------------------------------------------


class TestScoreSubmittedDoubles:
    def test_emits_score_submitted_on_first_doubles_submission(self):
        match = _doubles_match(status=MatchStatusEnum.SCHEDULED)
        service, _ = _make_service(match)

        with patch(
            "app.services.match_confirmation_service.log_analytics_event"
        ) as mock_emit:
            _run_patched(service, A1, VerifyScoreRequest(winner_team="A"))

        events = _events_of_type(mock_emit, "score_submitted")
        assert len(events) == 1
        kwargs = events[0].kwargs
        assert kwargs["uid"] == A1
        assert kwargs["sport"] == SportEnum.PADEL.value
        assert kwargs["match_type"] == MatchTypeEnum.DOUBLES.value
        assert kwargs["venue_present"] is False
        assert kwargs["match_id"] == MATCH_ID


# ---------------------------------------------------------------------------
# Tests: score_confirmed (doubles)
# ---------------------------------------------------------------------------


class TestScoreConfirmedDoubles:
    def test_emits_score_confirmed_on_doubles_confirmation(self):
        stored_score = _make_doubles_score(winner_team="A")
        match = _doubles_match(
            status=MatchStatusEnum.PENDING_CONFIRMATION,
            score=stored_score,
            result_submitted_by=[A1],
        )
        service, _ = _make_service(match)

        with patch(
            "app.services.match_confirmation_service.log_analytics_event"
        ) as mock_emit:
            # B1 is on the opposing team — valid confirmer
            _run_patched(service, B1, VerifyScoreRequest(winner_team="A"))

        events = _events_of_type(mock_emit, "score_confirmed")
        assert len(events) == 1
        kwargs = events[0].kwargs
        assert kwargs["uid"] == B1
        assert kwargs["sport"] == SportEnum.PADEL.value
        assert kwargs["match_type"] == MatchTypeEnum.DOUBLES.value
        assert kwargs["match_id"] == MATCH_ID
        assert kwargs["venue_present"] is False


# ---------------------------------------------------------------------------
# Tests: match_disputed (doubles)
# ---------------------------------------------------------------------------


class TestMatchDisputedDoubles:
    def test_emits_match_disputed_on_doubles_disagreement(self):
        stored_score = _make_doubles_score(winner_team="A")
        match = _doubles_match(
            status=MatchStatusEnum.PENDING_CONFIRMATION,
            score=stored_score,
            result_submitted_by=[A1],
        )
        service, _ = _make_service(match)

        with patch(
            "app.services.match_confirmation_service.log_analytics_event"
        ) as mock_emit:
            # B1 disagrees: claims team B won
            _run_patched(service, B1, VerifyScoreRequest(winner_team="B"))

        events = _events_of_type(mock_emit, "match_disputed")
        assert len(events) == 1
        kwargs = events[0].kwargs
        assert kwargs["uid"] == B1
        assert kwargs["sport"] == SportEnum.PADEL.value
        assert kwargs["match_type"] == MatchTypeEnum.DOUBLES.value
        assert kwargs["match_id"] == MATCH_ID
        assert kwargs["venue_present"] is False
