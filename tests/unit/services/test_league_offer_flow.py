"""
Unit tests for LGM-1: league_id threading through the offer → accept → match flow.

Covers:
- send_offer: leagueId written to offer_data when league_id provided
- send_offer: null leagueId when no league_id provided
- send_offer: rejects nonexistent league
- send_offer: rejects inactive league
- send_offer: rejects non-member sender
- send_offer: rejects non-member recipient
- accept_offer: league_id flows to match for singles
- accept_offer: league_id flows to match for doubles
- accept_offer: null league_id stays null in match
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from app.models.enums import (
    LeagueMemberStatusEnum,
    LeagueStatusEnum,
    MatchTypeEnum,
    OfferStatusEnum,
    SportEnum,
)
from app.models.play import Offer, SendOfferRequest
from app.repos.broadcasts_repo import BroadcastsRepo
from app.repos.leagues_repo import LeaguesRepo
from app.repos.matches_repo import MatchesRepo
from app.repos.offers_repo import OffersRepo
from app.repos.users_repo import UsersRepo
from app.services.play_service import PlayService


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_users_repo():
    return Mock(spec=UsersRepo)


@pytest.fixture
def mock_broadcasts_repo():
    repo = Mock(spec=BroadcastsRepo)
    repo.list_active.return_value = []
    return repo


@pytest.fixture
def mock_offers_repo():
    return Mock(spec=OffersRepo)


@pytest.fixture
def mock_matches_repo():
    return Mock(spec=MatchesRepo)


@pytest.fixture
def mock_firestore_client():
    return Mock()


@pytest.fixture
def mock_leagues_repo():
    return Mock(spec=LeaguesRepo)


@pytest.fixture
def play_service_with_leagues(
    mock_users_repo,
    mock_broadcasts_repo,
    mock_matches_repo,
    mock_offers_repo,
    mock_firestore_client,
    mock_leagues_repo,
):
    return PlayService(
        mock_users_repo,
        mock_broadcasts_repo,
        mock_matches_repo,
        mock_offers_repo,
        mock_firestore_client,
        leagues_repo=mock_leagues_repo,
    )


def _active_league():
    league = Mock()
    league.status = LeagueStatusEnum.ACTIVE
    return league


def _active_member():
    member = Mock()
    member.status = LeagueMemberStatusEnum.ACTIVE
    return member


def _pending_offer(
    *,
    league_id: str | None = None,
    match_type: MatchTypeEnum = MatchTypeEnum.SINGLES,
    partner_uid: str | None = None,
    source_broadcast_id: str | None = None,
) -> Offer:
    now = datetime.now(timezone.utc)
    return Offer(
        offer_id="offer_test",
        from_uid="sender_uid",
        from_name="Sender",
        from_ranking=None,
        to_uid="recipient_uid",
        to_name="Recipient",
        to_ranking=None,
        sport=SportEnum.TENNIS,
        match_type=match_type,
        partner_uid=partner_uid,
        proposed_time=now + timedelta(hours=1),
        court_location=None,
        venue_ref=None,
        source_broadcast_id=source_broadcast_id,
        league_id=league_id,
        message=None,
        status=OfferStatusEnum.PENDING,
        expires_at=now + timedelta(minutes=5),
        created_at=now - timedelta(minutes=1),
        match_id=None,
    )


def _stub_transactional(play_service_module):
    """Replace firestore.transactional with a pass-through during tests."""
    original = play_service_module.firestore.transactional

    def mock_transactional(func):
        return func

    play_service_module.firestore.transactional = mock_transactional
    return original


# ---------------------------------------------------------------------------
# send_offer tests
# ---------------------------------------------------------------------------


class TestSendOfferLeagueValidation:
    def _setup_doc_side_effect(self, mock_users_repo):
        mock_users_repo.get_user_doc.side_effect = [
            {"name": "Sender", "rankings": {}, "playTab": {"state": "DISCOVERY"}},
            {"name": "Recipient", "rankings": {}, "playTab": {"state": "DISCOVERY"}},
        ]

    def _setup_offer_ref(self, mock_firestore_client):
        mock_doc_ref = Mock()
        mock_doc_ref.id = "offer_new"
        mock_firestore_client.collection.return_value.document.return_value = (
            mock_doc_ref
        )

    def test_send_offer_with_league_id_writes_league_id_to_offer(
        self,
        play_service_with_leagues,
        mock_users_repo,
        mock_firestore_client,
        mock_leagues_repo,
    ):
        """league_id in request → leagueId written to offer_data."""
        import app.services.play_service as psm

        original = _stub_transactional(psm)
        try:
            self._setup_doc_side_effect(mock_users_repo)
            self._setup_offer_ref(mock_firestore_client)
            mock_leagues_repo.get_by_id.return_value = _active_league()
            mock_leagues_repo.get_member.return_value = _active_member()

            now = datetime.now(timezone.utc)
            request = SendOfferRequest(
                to_uid="recipient_uid",
                sport=SportEnum.TENNIS,
                proposed_time=now + timedelta(hours=2),
                league_id="league_001",
            )
            play_service_with_leagues.send_offer("sender_uid", request)

            txn = mock_firestore_client.transaction.return_value
            offer_data = txn.set.call_args.args[1]
            assert offer_data["leagueId"] == "league_001"
        finally:
            psm.firestore.transactional = original

    def test_send_offer_without_league_id_writes_null(
        self,
        play_service_with_leagues,
        mock_users_repo,
        mock_firestore_client,
    ):
        """No league_id in request → leagueId is None in offer_data."""
        import app.services.play_service as psm

        original = _stub_transactional(psm)
        try:
            self._setup_doc_side_effect(mock_users_repo)
            self._setup_offer_ref(mock_firestore_client)

            now = datetime.now(timezone.utc)
            request = SendOfferRequest(
                to_uid="recipient_uid",
                sport=SportEnum.TENNIS,
                proposed_time=now + timedelta(hours=2),
            )
            play_service_with_leagues.send_offer("sender_uid", request)

            txn = mock_firestore_client.transaction.return_value
            offer_data = txn.set.call_args.args[1]
            assert offer_data["leagueId"] is None
        finally:
            psm.firestore.transactional = original

    def test_send_offer_rejects_nonexistent_league(
        self,
        play_service_with_leagues,
        mock_users_repo,
        mock_leagues_repo,
    ):
        """league_id points to nonexistent league → ValueError."""
        self._setup_doc_side_effect(mock_users_repo)
        mock_leagues_repo.get_by_id.return_value = None

        now = datetime.now(timezone.utc)
        request = SendOfferRequest(
            to_uid="recipient_uid",
            sport=SportEnum.TENNIS,
            proposed_time=now + timedelta(hours=2),
            league_id="ghost_league",
        )
        with pytest.raises(ValueError, match="League not found"):
            play_service_with_leagues.send_offer("sender_uid", request)

    def test_send_offer_rejects_inactive_league(
        self,
        play_service_with_leagues,
        mock_users_repo,
        mock_leagues_repo,
    ):
        """league_id points to a COMPLETED league → ValueError."""
        self._setup_doc_side_effect(mock_users_repo)
        completed_league = Mock()
        completed_league.status = LeagueStatusEnum.COMPLETED
        mock_leagues_repo.get_by_id.return_value = completed_league

        now = datetime.now(timezone.utc)
        request = SendOfferRequest(
            to_uid="recipient_uid",
            sport=SportEnum.TENNIS,
            proposed_time=now + timedelta(hours=2),
            league_id="league_done",
        )
        with pytest.raises(ValueError, match="League is not active"):
            play_service_with_leagues.send_offer("sender_uid", request)

    def test_send_offer_rejects_non_member_sender(
        self,
        play_service_with_leagues,
        mock_users_repo,
        mock_leagues_repo,
    ):
        """Sender not a league member → ValueError."""
        self._setup_doc_side_effect(mock_users_repo)
        mock_leagues_repo.get_by_id.return_value = _active_league()
        # First call is for the sender — return None (not a member)
        mock_leagues_repo.get_member.return_value = None

        now = datetime.now(timezone.utc)
        request = SendOfferRequest(
            to_uid="recipient_uid",
            sport=SportEnum.TENNIS,
            proposed_time=now + timedelta(hours=2),
            league_id="league_001",
        )
        with pytest.raises(ValueError, match="Sender is not an active member"):
            play_service_with_leagues.send_offer("sender_uid", request)

    def test_send_offer_rejects_non_member_recipient(
        self,
        play_service_with_leagues,
        mock_users_repo,
        mock_leagues_repo,
    ):
        """Recipient not a league member → ValueError."""
        self._setup_doc_side_effect(mock_users_repo)
        mock_leagues_repo.get_by_id.return_value = _active_league()
        # sender is active, recipient is None
        mock_leagues_repo.get_member.side_effect = [_active_member(), None]

        now = datetime.now(timezone.utc)
        request = SendOfferRequest(
            to_uid="recipient_uid",
            sport=SportEnum.TENNIS,
            proposed_time=now + timedelta(hours=2),
            league_id="league_001",
        )
        with pytest.raises(ValueError, match="Recipient is not an active member"):
            play_service_with_leagues.send_offer("sender_uid", request)


# ---------------------------------------------------------------------------
# accept_offer tests — league_id flows to match
# ---------------------------------------------------------------------------


class TestAcceptOfferLeagueId:
    def _setup_accept(self, mock_users_repo, mock_broadcasts_repo):
        mock_users_repo.get_user_doc.side_effect = [
            {
                "name": "Recipient",
                "playTab": {
                    "state": "INCOMING_OFFER_PENDING",
                    "activeBroadcastId": None,
                    "pendingIncomingOfferIds": ["offer_test"],
                },
            },
            {
                "name": "Sender",
                "playTab": {
                    "state": "OUTGOING_OFFER_PENDING",
                    "activeOutgoingOfferId": "offer_test",
                },
            },
        ]
        mock_broadcasts_repo.get_by_id.return_value = None

    def test_accept_offer_league_id_flows_to_match_singles(
        self,
        play_service_with_leagues,
        mock_offers_repo,
        mock_users_repo,
        mock_broadcasts_repo,
        mock_firestore_client,
    ):
        """Singles: offer.league_id is written to the match doc as leagueId."""
        import app.services.play_service as psm

        original = _stub_transactional(psm)
        try:
            self._setup_accept(mock_users_repo, mock_broadcasts_repo)
            mock_offer = _pending_offer(league_id="league_singles")
            mock_offers_repo.get_by_id.return_value = mock_offer

            play_service_with_leagues.accept_offer("recipient_uid", "offer_test")

            txn = mock_firestore_client.transaction.return_value
            match_data = txn.set.call_args.args[1]
            assert match_data["leagueId"] == "league_singles"
            assert match_data["matchType"] == "singles"
        finally:
            psm.firestore.transactional = original

    def test_accept_offer_league_id_flows_to_match_doubles(
        self,
        play_service_with_leagues,
        mock_offers_repo,
        mock_users_repo,
        mock_broadcasts_repo,
        mock_firestore_client,
    ):
        """Doubles: offer.league_id is written to the match doc as leagueId."""
        import app.services.play_service as psm

        original = _stub_transactional(psm)
        try:
            now = datetime.now(timezone.utc)

            # Doubles requires 4 distinct participants and a source broadcast
            from app.models.play import Broadcast, BroadcastLocation
            from app.models.enums import (
                AvailabilityEnum,
                BroadcastStatusEnum,
                BroadcastTypeEnum,
                CourtStatusEnum,
            )

            mock_broadcast = Broadcast(
                broadcast_id="bcast_001",
                owner_uid="recipient_uid",
                owner_name="Recipient",
                sport=SportEnum.TENNIS,
                match_type=MatchTypeEnum.DOUBLES,
                broadcast_type=BroadcastTypeEnum.FIND_OPPONENT,
                partner_uid="partner_recipient",
                availability=AvailabilityEnum.TODAY,
                court_status=CourtStatusEnum.HAVE_COURT,
                status=BroadcastStatusEnum.ACTIVE,
                expires_at=now + timedelta(hours=1),
                created_at=now - timedelta(minutes=5),
                location=BroadcastLocation(area=1),
            )
            mock_broadcasts_repo.get_by_id.return_value = mock_broadcast

            mock_users_repo.get_user_doc.side_effect = [
                {
                    "name": "Recipient",
                    "playTab": {
                        "state": "INCOMING_OFFER_PENDING",
                        "activeBroadcastId": "bcast_001",
                        "pendingIncomingOfferIds": ["offer_test"],
                    },
                },
                {
                    "name": "Sender",
                    "playTab": {
                        "state": "OUTGOING_OFFER_PENDING",
                        "activeOutgoingOfferId": "offer_test",
                    },
                },
                {"name": "Partner Recipient", "playTab": {}},
                {"name": "Partner Sender", "playTab": {}},
            ]

            mock_offer = _pending_offer(
                league_id="league_doubles",
                match_type=MatchTypeEnum.DOUBLES,
                partner_uid="partner_sender",
                source_broadcast_id="bcast_001",
            )
            mock_offers_repo.get_by_id.return_value = mock_offer

            play_service_with_leagues.accept_offer("recipient_uid", "offer_test")

            txn = mock_firestore_client.transaction.return_value
            match_data = txn.set.call_args.args[1]
            assert match_data["leagueId"] == "league_doubles"
            assert match_data["matchType"] == "doubles"
        finally:
            psm.firestore.transactional = original

    def test_accept_offer_null_league_id_stays_null(
        self,
        play_service_with_leagues,
        mock_offers_repo,
        mock_users_repo,
        mock_broadcasts_repo,
        mock_firestore_client,
    ):
        """When offer has no league_id, the match doc has leagueId=None."""
        import app.services.play_service as psm

        original = _stub_transactional(psm)
        try:
            self._setup_accept(mock_users_repo, mock_broadcasts_repo)
            mock_offer = _pending_offer(league_id=None)
            mock_offers_repo.get_by_id.return_value = mock_offer

            play_service_with_leagues.accept_offer("recipient_uid", "offer_test")

            txn = mock_firestore_client.transaction.return_value
            match_data = txn.set.call_args.args[1]
            assert match_data["leagueId"] is None
        finally:
            psm.firestore.transactional = original
