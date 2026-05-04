"""Unit tests for the DISCOVERY payload in PlayService (DBL-8)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from app.models.enums import (
    AvailabilityEnum,
    BroadcastStatusEnum,
    BroadcastTypeEnum,
    CourtStatusEnum,
    MatchTypeEnum,
    PlayTabStateEnum,
    SportEnum,
)
from app.models.play import (
    Broadcast,
    BroadcastLocation,
    DiscoveryAnnotations,
    DiscoveryPayload,
)
from app.repos.broadcasts_repo import BroadcastsRepo
from app.repos.matches_repo import MatchesRepo
from app.repos.offers_repo import OffersRepo
from app.repos.users_repo import UsersRepo
from app.services.play_service import PlayService

NOW = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
EXPIRES = NOW + timedelta(hours=2)


def _make_broadcast(
    broadcast_id: str,
    owner_uid: str,
    match_type: MatchTypeEnum = MatchTypeEnum.SINGLES,
    broadcast_type: BroadcastTypeEnum = BroadcastTypeEnum.FIND_OPPONENT,
    partner_uid: str | None = None,
) -> Broadcast:
    # doubles + find_opponent requires a partner_uid per model validation
    resolved_partner_uid = partner_uid
    if (
        match_type == MatchTypeEnum.DOUBLES
        and broadcast_type == BroadcastTypeEnum.FIND_OPPONENT
        and resolved_partner_uid is None
    ):
        resolved_partner_uid = "partner_placeholder"
    return Broadcast(
        broadcast_id=broadcast_id,
        owner_uid=owner_uid,
        owner_name=f"Player {owner_uid}",
        sport=SportEnum.TENNIS,
        match_type=match_type,
        broadcast_type=broadcast_type,
        partner_uid=resolved_partner_uid,
        availability=AvailabilityEnum.TODAY,
        court_status=CourtStatusEnum.HAVE_COURT,
        status=BroadcastStatusEnum.ACTIVE,
        expires_at=EXPIRES,
        created_at=NOW,
        location=BroadcastLocation(),
    )


@pytest.fixture
def mock_users_repo() -> Mock:
    repo = Mock(spec=UsersRepo)
    repo.get_user_doc.return_value = {"name": "Test User", "playTab": {}}
    return repo


@pytest.fixture
def mock_broadcasts_repo() -> Mock:
    return Mock(spec=BroadcastsRepo)


@pytest.fixture
def mock_offers_repo() -> Mock:
    return Mock(spec=OffersRepo)


@pytest.fixture
def mock_matches_repo() -> Mock:
    return Mock(spec=MatchesRepo)


@pytest.fixture
def play_service(
    mock_users_repo: Mock,
    mock_broadcasts_repo: Mock,
    mock_matches_repo: Mock,
    mock_offers_repo: Mock,
) -> PlayService:
    return PlayService(
        mock_users_repo,
        mock_broadcasts_repo,
        mock_matches_repo,
        mock_offers_repo,
        Mock(),
    )


def _discovery_user_doc() -> dict:
    """User doc with no active broadcast (DISCOVERY state)."""
    return {"name": "Self", "playTab": {"state": "DISCOVERY"}}


class TestDiscoveryPayload:
    def test_empty_feed_returns_discovery_payload(
        self,
        play_service: PlayService,
        mock_users_repo: Mock,
        mock_broadcasts_repo: Mock,
    ) -> None:
        mock_users_repo.get_user_doc.return_value = _discovery_user_doc()
        mock_broadcasts_repo.list_active.return_value = []

        resp = play_service.get_me_state("user_a")

        assert resp.mode == PlayTabStateEnum.DISCOVERY
        assert isinstance(resp.payload, DiscoveryPayload)
        assert resp.payload.broadcasts == []

    def test_empty_feed_annotations_are_zero(
        self,
        play_service: PlayService,
        mock_users_repo: Mock,
        mock_broadcasts_repo: Mock,
    ) -> None:
        mock_users_repo.get_user_doc.return_value = _discovery_user_doc()
        mock_broadcasts_repo.list_active.return_value = []

        resp = play_service.get_me_state("user_a")

        assert isinstance(resp.annotations, DiscoveryAnnotations)
        assert resp.annotations.nearby_count == 0
        assert resp.annotations.doubles_count == 0
        assert resp.annotations.find_fourth_count == 0

    def test_listing_cards_returns_correct_fields(
        self,
        play_service: PlayService,
        mock_users_repo: Mock,
        mock_broadcasts_repo: Mock,
    ) -> None:
        mock_users_repo.get_user_doc.return_value = _discovery_user_doc()
        bc = _make_broadcast("bc_001", "user_b")
        mock_broadcasts_repo.list_active.return_value = [bc]

        resp = play_service.get_me_state("user_a")

        assert isinstance(resp.payload, DiscoveryPayload)
        assert len(resp.payload.broadcasts) == 1
        card = resp.payload.broadcasts[0]
        assert card.broadcast_id == "bc_001"
        assert card.owner_uid == "user_b"
        assert card.match_type == MatchTypeEnum.SINGLES
        assert card.broadcast_type == BroadcastTypeEnum.FIND_OPPONENT

    def test_excludes_callers_own_broadcast(
        self,
        play_service: PlayService,
        mock_users_repo: Mock,
        mock_broadcasts_repo: Mock,
    ) -> None:
        mock_users_repo.get_user_doc.return_value = _discovery_user_doc()
        own = _make_broadcast("bc_self", "user_a")
        other = _make_broadcast("bc_other", "user_b")
        mock_broadcasts_repo.list_active.return_value = [own, other]

        resp = play_service.get_me_state("user_a")

        assert isinstance(resp.payload, DiscoveryPayload)
        ids = [c.broadcast_id for c in resp.payload.broadcasts]
        assert "bc_self" not in ids
        assert "bc_other" in ids

    def test_annotation_counts_reflect_post_filter_cards(
        self,
        play_service: PlayService,
        mock_users_repo: Mock,
        mock_broadcasts_repo: Mock,
    ) -> None:
        mock_users_repo.get_user_doc.return_value = _discovery_user_doc()
        singles_card = _make_broadcast("bc_singles", "user_b", MatchTypeEnum.SINGLES)
        doubles_card = _make_broadcast(
            "bc_doubles",
            "user_c",
            MatchTypeEnum.DOUBLES,
            BroadcastTypeEnum.FIND_OPPONENT,
        )
        fourth_card = _make_broadcast(
            "bc_fourth", "user_d", MatchTypeEnum.DOUBLES, BroadcastTypeEnum.FIND_FOURTH
        )
        mock_broadcasts_repo.list_active.return_value = [
            singles_card,
            doubles_card,
            fourth_card,
        ]

        resp = play_service.get_me_state("user_a")

        assert isinstance(resp.annotations, DiscoveryAnnotations)
        assert resp.annotations.nearby_count == 3
        assert resp.annotations.doubles_count == 2  # doubles_card + fourth_card
        assert resp.annotations.find_fourth_count == 1

    def test_match_type_doubles_filter_passed_to_repo(
        self,
        play_service: PlayService,
        mock_users_repo: Mock,
        mock_broadcasts_repo: Mock,
    ) -> None:
        mock_users_repo.get_user_doc.return_value = _discovery_user_doc()
        mock_broadcasts_repo.list_active.return_value = []

        play_service.get_me_state("user_a", match_type=MatchTypeEnum.DOUBLES)

        mock_broadcasts_repo.list_active.assert_called_once_with(
            match_type=MatchTypeEnum.DOUBLES, limit=25
        )

    def test_match_type_singles_filter_passed_to_repo(
        self,
        play_service: PlayService,
        mock_users_repo: Mock,
        mock_broadcasts_repo: Mock,
    ) -> None:
        mock_users_repo.get_user_doc.return_value = _discovery_user_doc()
        mock_broadcasts_repo.list_active.return_value = []

        play_service.get_me_state("user_a", match_type=MatchTypeEnum.SINGLES)

        mock_broadcasts_repo.list_active.assert_called_once_with(
            match_type=MatchTypeEnum.SINGLES, limit=25
        )

    def test_no_filter_passes_none_to_repo(
        self,
        play_service: PlayService,
        mock_users_repo: Mock,
        mock_broadcasts_repo: Mock,
    ) -> None:
        mock_users_repo.get_user_doc.return_value = _discovery_user_doc()
        mock_broadcasts_repo.list_active.return_value = []

        play_service.get_me_state("user_a")

        mock_broadcasts_repo.list_active.assert_called_once_with(
            match_type=None, limit=25
        )

    def test_unknown_user_returns_discovery_with_empty_feed(
        self,
        play_service: PlayService,
        mock_users_repo: Mock,
        mock_broadcasts_repo: Mock,
    ) -> None:
        mock_users_repo.get_user_doc.return_value = None

        resp = play_service.get_me_state("user_unknown")

        assert resp.mode == PlayTabStateEnum.DISCOVERY
        assert isinstance(resp.payload, DiscoveryPayload)
        assert resp.payload.broadcasts == []
        assert isinstance(resp.annotations, DiscoveryAnnotations)
        assert resp.annotations.nearby_count == 0
        # list_active should NOT be called — no user doc, short-circuit path
        mock_broadcasts_repo.list_active.assert_not_called()
