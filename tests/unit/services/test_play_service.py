from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from app.models.common import GeoCoordinates, VenueRef
from app.models.enums import (
    AvailabilityEnum,
    BroadcastStatusEnum,
    CourtStatusEnum,
    OfferStatusEnum,
    PlayTabStateEnum,
    SportEnum,
)
from app.models.match import Match, MatchParticipant
from app.models.play import (
    Broadcast,
    BroadcastLocation,
    CreateBroadcastRequest,
    Offer,
    SendOfferRequest,
)
from app.repos.broadcasts_repo import BroadcastsRepo
from app.repos.matches_repo import MatchesRepo
from app.repos.offers_repo import OffersRepo
from app.repos.users_repo import UsersRepo
from app.services.play_service import PlayService


@pytest.fixture
def mock_users_repo():
    return Mock(spec=UsersRepo)


@pytest.fixture
def mock_broadcasts_repo():
    return Mock(spec=BroadcastsRepo)


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
def play_service(
    mock_users_repo,
    mock_broadcasts_repo,
    mock_matches_repo,
    mock_offers_repo,
    mock_firestore_client,
):
    return PlayService(
        mock_users_repo,
        mock_broadcasts_repo,
        mock_matches_repo,
        mock_offers_repo,
        mock_firestore_client,
    )


def _curated_venue_ref() -> VenueRef:
    return VenueRef(
        venue_id="ten_twenty_club",
        place_id=None,
        name="Ten Twenty Club",
        coordinates=GeoCoordinates(lat=37.8362, lng=23.7627),
    )


class TestGetMeState:
    def test_get_me_state_user_not_found(self, play_service, mock_users_repo):
        """Returns DISCOVERY mode when user doesn't exist"""
        mock_users_repo.get_user_doc.return_value = None

        response = play_service.get_me_state("nonexistent_user")

        assert response.mode == PlayTabStateEnum.DISCOVERY
        assert response.payload == {}

    def test_get_me_state_discovery(self, play_service, mock_users_repo):
        """Returns DISCOVERY mode with empty payload"""
        mock_users_repo.get_user_doc.return_value = {
            "name": "Alice",
            "playTab": {"state": "DISCOVERY"},
        }

        response = play_service.get_me_state("alice")

        assert response.mode == PlayTabStateEnum.DISCOVERY
        assert response.payload == {}

    def test_get_me_state_broadcast_active(
        self, play_service, mock_users_repo, mock_broadcasts_repo, mock_offers_repo
    ):
        """Returns BROADCAST_ACTIVE with BroadcastActivePayload"""
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.return_value = {
            "name": "Alice",
            "playTab": {
                "state": "BROADCAST_ACTIVE",
                "activeBroadcastId": "broadcast123",
                "pendingIncomingOfferIds": ["offer1", "offer2"],
            },
        }

        mock_broadcast = Broadcast(
            broadcast_id="broadcast123",
            owner_uid="alice",
            owner_name="Alice",
            owner_ranking=None,
            sport=SportEnum.TENNIS,
            availability=AvailabilityEnum.TODAY,
            court_status=CourtStatusEnum.HAVE_COURT,
            court_location="Central Park",
            status=BroadcastStatusEnum.ACTIVE,
            expires_at=now + timedelta(hours=2),
            created_at=now,
            location=BroadcastLocation(area=10001),
        )
        mock_broadcasts_repo.get_by_id.return_value = mock_broadcast

        mock_offer1 = Offer(
            offer_id="offer1",
            from_uid="bob",
            from_name="Bob",
            from_ranking=None,
            to_uid="alice",
            to_name="Alice",
            to_ranking=None,
            sport=SportEnum.TENNIS,
            proposed_time=now + timedelta(hours=1),
            court_location=None,
            message="Let's play!",
            status=OfferStatusEnum.PENDING,
            expires_at=now + timedelta(minutes=5),
            created_at=now,
            match_id=None,
        )
        mock_offer2 = Offer(
            offer_id="offer2",
            from_uid="charlie",
            from_name="Charlie",
            from_ranking=None,
            to_uid="alice",
            to_name="Alice",
            to_ranking=None,
            sport=SportEnum.TENNIS,
            proposed_time=now + timedelta(hours=2),
            court_location=None,
            message=None,
            status=OfferStatusEnum.PENDING,
            expires_at=now + timedelta(minutes=5),
            created_at=now,
            match_id=None,
        )
        mock_offers_repo.get_by_ids.return_value = [mock_offer1, mock_offer2]

        response = play_service.get_me_state("alice")

        assert response.mode == PlayTabStateEnum.BROADCAST_ACTIVE
        assert "broadcast_id" in response.payload
        assert "pending_offers" in response.payload
        assert len(response.payload["pending_offers"]) == 2

    def test_get_me_state_broadcast_active_no_pending_offers(
        self, play_service, mock_users_repo, mock_broadcasts_repo, mock_offers_repo
    ):
        """BROADCAST_ACTIVE with empty pendingIncomingOfferIds"""
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.return_value = {
            "name": "Alice",
            "playTab": {
                "state": "BROADCAST_ACTIVE",
                "activeBroadcastId": "broadcast123",
                "pendingIncomingOfferIds": [],
            },
        }

        mock_broadcast = Broadcast(
            broadcast_id="broadcast123",
            owner_uid="alice",
            owner_name="Alice",
            owner_ranking=None,
            sport=SportEnum.TENNIS,
            availability=AvailabilityEnum.TODAY,
            court_status=CourtStatusEnum.NEED_COURT,
            court_location=None,
            status=BroadcastStatusEnum.ACTIVE,
            expires_at=now + timedelta(hours=2),
            created_at=now,
            location=BroadcastLocation(area=10001),
        )
        mock_broadcasts_repo.get_by_id.return_value = mock_broadcast
        mock_offers_repo.get_by_ids.return_value = []

        response = play_service.get_me_state("alice")

        assert response.mode == PlayTabStateEnum.BROADCAST_ACTIVE
        assert response.payload["pending_offers"] == []

    def test_get_me_state_outgoing_offer_pending(
        self, play_service, mock_users_repo, mock_offers_repo
    ):
        """Returns OutgoingOfferPayload"""
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.return_value = {
            "name": "Alice",
            "playTab": {
                "state": "OUTGOING_OFFER_PENDING",
                "activeOutgoingOfferId": "offer123",
            },
        }

        mock_offer = Offer(
            offer_id="offer123",
            from_uid="alice",
            from_name="Alice",
            from_ranking=None,
            to_uid="bob",
            to_name="Bob",
            to_ranking=None,
            sport=SportEnum.TENNIS,
            proposed_time=now + timedelta(hours=1),
            court_location="Central Park",
            message="Challenge!",
            status=OfferStatusEnum.PENDING,
            expires_at=now + timedelta(minutes=5),
            created_at=now,
            match_id=None,
        )
        mock_offers_repo.get_by_id.return_value = mock_offer

        response = play_service.get_me_state("alice")

        assert response.mode == PlayTabStateEnum.OUTGOING_OFFER_PENDING
        assert "offer_id" in response.payload
        assert response.payload["to_uid"] == "bob"

    def test_get_me_state_incoming_offer_pending(
        self, play_service, mock_users_repo, mock_offers_repo
    ):
        """Returns IncomingOfferPayload"""
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.return_value = {
            "name": "Bob",
            "playTab": {
                "state": "INCOMING_OFFER_PENDING",
                "pendingIncomingOfferIds": ["offer123"],
            },
        }

        mock_offer = Offer(
            offer_id="offer123",
            from_uid="alice",
            from_name="Alice",
            from_ranking=None,
            to_uid="bob",
            to_name="Bob",
            to_ranking=None,
            sport=SportEnum.TENNIS,
            proposed_time=now + timedelta(hours=1),
            court_location=None,
            message="Let's play!",
            status=OfferStatusEnum.PENDING,
            expires_at=now + timedelta(minutes=5),
            created_at=now,
            match_id=None,
        )
        mock_offers_repo.get_by_id.return_value = mock_offer

        response = play_service.get_me_state("bob")

        assert response.mode == PlayTabStateEnum.INCOMING_OFFER_PENDING
        assert "offer_id" in response.payload
        assert response.payload["from_uid"] == "alice"

    def test_get_me_state_match_scheduled(
        self, play_service, mock_users_repo, mock_matches_repo
    ):
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.side_effect = [
            {
                "name": "Alice",
                "playTab": {
                    "state": "MATCH_SCHEDULED",
                    "activeMatchId": "match_offer123",
                },
            },
            {
                "name": "Bob",
                "profileUrl": "https://example.com/bob.png",
                "rankings": {
                    "tennis": {"sport": "tennis", "pts": 1200, "globalRanking": 42}
                },
            },
        ]
        mock_matches_repo.get_by_id.return_value = Match(
            match_id="match_offer123",
            sport=SportEnum.TENNIS,
            status="scheduled",
            scheduled_at=now + timedelta(hours=2),
            venue_ref=_curated_venue_ref(),
            participants=[
                MatchParticipant(uid="alice", role="player"),
                MatchParticipant(uid="bob", role="player"),
            ],
            participant_uids=["alice", "bob"],
            participant_pair="alice_bob",
        )

        response = play_service.get_me_state("alice")

        assert response.mode == PlayTabStateEnum.MATCH_SCHEDULED
        assert response.payload["match_id"] == "match_offer123"
        assert response.payload["venue_ref"]["venueId"] == "ten_twenty_club"
        assert response.payload["opponent"]["uid"] == "bob"
        assert response.payload["opponent"]["ranking"]["global_ranking"] == 42


class TestFreshnessReconciliation:
    def test_freshness_broadcast_expired(
        self, play_service, mock_users_repo, mock_broadcasts_repo
    ):
        """Broadcast expired - corrects state to DISCOVERY"""
        now = datetime.now(timezone.utc)
        past = now - timedelta(hours=1)

        mock_users_repo.get_user_doc.return_value = {
            "name": "Alice",
            "playTab": {
                "state": "BROADCAST_ACTIVE",
                "activeBroadcastId": "broadcast123",
            },
        }

        mock_broadcast = Broadcast(
            broadcast_id="broadcast123",
            owner_uid="alice",
            owner_name="Alice",
            owner_ranking=None,
            sport=SportEnum.TENNIS,
            availability=AvailabilityEnum.TODAY,
            court_status=CourtStatusEnum.HAVE_COURT,
            court_location=None,
            status=BroadcastStatusEnum.ACTIVE,
            expires_at=past,  # Expired
            created_at=past - timedelta(hours=2),
            location=BroadcastLocation(area=10001),
        )
        mock_broadcasts_repo.get_by_id.return_value = mock_broadcast

        response = play_service.get_me_state("alice")

        assert response.mode == PlayTabStateEnum.DISCOVERY
        mock_broadcasts_repo.update_status.assert_called_once_with(
            "broadcast123", BroadcastStatusEnum.EXPIRED
        )
        mock_users_repo.update_play_tab.assert_called_once()
        assert len(response.ui_events) > 0
        assert response.ui_events[0].type == "broadcast_expired"

    def test_freshness_broadcast_not_expired(
        self, play_service, mock_users_repo, mock_broadcasts_repo, mock_offers_repo
    ):
        """Broadcast not expired - stays BROADCAST_ACTIVE"""
        now = datetime.now(timezone.utc)

        mock_users_repo.get_user_doc.return_value = {
            "name": "Alice",
            "playTab": {
                "state": "BROADCAST_ACTIVE",
                "activeBroadcastId": "broadcast123",
                "pendingIncomingOfferIds": [],
            },
        }

        mock_broadcast = Broadcast(
            broadcast_id="broadcast123",
            owner_uid="alice",
            owner_name="Alice",
            owner_ranking=None,
            sport=SportEnum.TENNIS,
            availability=AvailabilityEnum.TODAY,
            court_status=CourtStatusEnum.NEED_COURT,
            court_location=None,
            status=BroadcastStatusEnum.ACTIVE,
            expires_at=now + timedelta(hours=1),  # Not expired
            created_at=now - timedelta(hours=1),
            location=BroadcastLocation(area=10001),
        )
        mock_broadcasts_repo.get_by_id.return_value = mock_broadcast
        mock_offers_repo.get_by_ids.return_value = []

        response = play_service.get_me_state("alice")

        assert response.mode == PlayTabStateEnum.BROADCAST_ACTIVE
        mock_broadcasts_repo.update_status.assert_not_called()

    def test_freshness_outgoing_offer_expired_no_broadcast(
        self, play_service, mock_users_repo, mock_offers_repo
    ):
        """Outgoing offer expired, no broadcast - corrects to DISCOVERY"""
        now = datetime.now(timezone.utc)
        past = now - timedelta(minutes=10)

        mock_users_repo.get_user_doc.return_value = {
            "name": "Alice",
            "playTab": {
                "state": "OUTGOING_OFFER_PENDING",
                "activeOutgoingOfferId": "offer123",
                "activeBroadcastId": None,
            },
        }

        mock_offer = Offer(
            offer_id="offer123",
            from_uid="alice",
            from_name="Alice",
            from_ranking=None,
            to_uid="bob",
            to_name="Bob",
            to_ranking=None,
            sport=SportEnum.TENNIS,
            proposed_time=now,
            court_location=None,
            message=None,
            status=OfferStatusEnum.PENDING,
            expires_at=past,  # Expired
            created_at=past - timedelta(minutes=5),
            match_id=None,
        )
        mock_offers_repo.get_by_id.return_value = mock_offer

        response = play_service.get_me_state("alice")

        assert response.mode == PlayTabStateEnum.DISCOVERY
        mock_offers_repo.update_status.assert_called_once_with(
            "offer123", OfferStatusEnum.EXPIRED
        )
        assert len(response.ui_events) > 0

    def test_freshness_outgoing_offer_expired_with_broadcast(
        self, play_service, mock_users_repo, mock_offers_repo, mock_broadcasts_repo
    ):
        """Outgoing offer expired, has broadcast - corrects to BROADCAST_ACTIVE"""
        now = datetime.now(timezone.utc)
        past = now - timedelta(minutes=10)

        mock_users_repo.get_user_doc.return_value = {
            "name": "Alice",
            "playTab": {
                "state": "OUTGOING_OFFER_PENDING",
                "activeOutgoingOfferId": "offer123",
                "activeBroadcastId": "broadcast123",
                "pendingIncomingOfferIds": [],
            },
        }

        mock_offer = Offer(
            offer_id="offer123",
            from_uid="alice",
            from_name="Alice",
            from_ranking=None,
            to_uid="bob",
            to_name="Bob",
            to_ranking=None,
            sport=SportEnum.TENNIS,
            proposed_time=now,
            court_location=None,
            message=None,
            status=OfferStatusEnum.PENDING,
            expires_at=past,  # Expired
            created_at=past - timedelta(minutes=5),
            match_id=None,
        )
        mock_offers_repo.get_by_id.return_value = mock_offer

        mock_broadcast = Broadcast(
            broadcast_id="broadcast123",
            owner_uid="alice",
            owner_name="Alice",
            owner_ranking=None,
            sport=SportEnum.TENNIS,
            availability=AvailabilityEnum.TODAY,
            court_status=CourtStatusEnum.NEED_COURT,
            court_location=None,
            status=BroadcastStatusEnum.ACTIVE,
            expires_at=now + timedelta(hours=1),
            created_at=now - timedelta(hours=1),
            location=BroadcastLocation(area=10001),
        )
        mock_broadcasts_repo.get_by_id.return_value = mock_broadcast
        mock_offers_repo.get_by_ids.return_value = []

        response = play_service.get_me_state("alice")

        assert response.mode == PlayTabStateEnum.BROADCAST_ACTIVE
        mock_offers_repo.update_status.assert_called_once_with(
            "offer123", OfferStatusEnum.EXPIRED
        )

    def test_freshness_incoming_offer_expired(
        self, play_service, mock_users_repo, mock_offers_repo
    ):
        """Incoming offer expired - corrects to DISCOVERY"""
        now = datetime.now(timezone.utc)
        past = now - timedelta(minutes=10)

        mock_users_repo.get_user_doc.return_value = {
            "name": "Bob",
            "playTab": {
                "state": "INCOMING_OFFER_PENDING",
                "pendingIncomingOfferIds": ["offer123"],
            },
        }

        mock_offer = Offer(
            offer_id="offer123",
            from_uid="alice",
            from_name="Alice",
            from_ranking=None,
            to_uid="bob",
            to_name="Bob",
            to_ranking=None,
            sport=SportEnum.TENNIS,
            proposed_time=now,
            court_location=None,
            message=None,
            status=OfferStatusEnum.PENDING,
            expires_at=past,  # Expired
            created_at=past - timedelta(minutes=5),
            match_id=None,
        )
        mock_offers_repo.get_by_id.return_value = mock_offer

        response = play_service.get_me_state("bob")

        assert response.mode == PlayTabStateEnum.DISCOVERY
        mock_offers_repo.update_status.assert_called_once_with(
            "offer123", OfferStatusEnum.EXPIRED
        )


class TestCreateBroadcast:
    def test_create_broadcast_success(
        self, play_service, mock_users_repo, mock_firestore_client
    ):
        """User in DISCOVERY - successfully creates broadcast"""
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.return_value = {
            "name": "Alice",
            "rankings": {"tennis": {"sport": "tennis", "pts": 1200}},
            "playTab": {"state": "DISCOVERY"},
        }

        mock_transaction = Mock()
        mock_firestore_client.transaction.return_value = mock_transaction

        # Mock the transaction function
        def transactional_decorator(func):
            def wrapper(txn):
                return func(txn)

            return wrapper

        mock_firestore_client.transaction.return_value = mock_transaction

        # Mock document ref
        mock_doc_ref = Mock()
        mock_doc_ref.id = "broadcast123"
        mock_firestore_client.collection.return_value.document.return_value = (
            mock_doc_ref
        )

        # Patch the transactional decorator
        import app.services.play_service as play_service_module

        original_transactional = play_service_module.firestore.transactional

        def mock_transactional(func):
            return func

        play_service_module.firestore.transactional = mock_transactional

        try:
            request = CreateBroadcastRequest(
                sport=SportEnum.TENNIS,
                availability=AvailabilityEnum.TODAY,
                court_status=CourtStatusEnum.HAVE_COURT,
                court_location="Central Park",
                expires_at=now + timedelta(hours=2),
                location=BroadcastLocation(area=10001),
            )

            response = play_service.create_broadcast("alice", request)

            assert response.broadcast_id == "broadcast123"
            assert response.sport == SportEnum.TENNIS
            assert response.status == BroadcastStatusEnum.ACTIVE
        finally:
            play_service_module.firestore.transactional = original_transactional

    def test_create_broadcast_user_not_found(self, play_service, mock_users_repo):
        """Users repo returns None - raises ValueError"""
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.return_value = None

        request = CreateBroadcastRequest(
            sport=SportEnum.TENNIS,
            availability=AvailabilityEnum.TODAY,
            court_status=CourtStatusEnum.NEED_COURT,
            court_location=None,
            expires_at=now + timedelta(hours=2),
            location=BroadcastLocation(area=10001),
        )

        with pytest.raises(ValueError, match="User not found"):
            play_service.create_broadcast("nonexistent", request)

    def test_create_broadcast_invalid_state_broadcast_active(
        self, play_service, mock_users_repo
    ):
        """User already in BROADCAST_ACTIVE - raises ValueError"""
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.return_value = {
            "name": "Alice",
            "playTab": {"state": "BROADCAST_ACTIVE"},
        }

        request = CreateBroadcastRequest(
            sport=SportEnum.TENNIS,
            availability=AvailabilityEnum.TODAY,
            court_status=CourtStatusEnum.NEED_COURT,
            court_location=None,
            expires_at=now + timedelta(hours=2),
            location=BroadcastLocation(area=10001),
        )

        with pytest.raises(ValueError, match="Cannot create broadcast"):
            play_service.create_broadcast("alice", request)

    def test_create_broadcast_expires_at_in_past(self, play_service, mock_users_repo):
        """expiresAt in past - raises ValueError"""
        now = datetime.now(timezone.utc)
        past = now - timedelta(hours=1)

        mock_users_repo.get_user_doc.return_value = {
            "name": "Alice",
            "playTab": {"state": "DISCOVERY"},
        }

        request = CreateBroadcastRequest(
            sport=SportEnum.TENNIS,
            availability=AvailabilityEnum.TODAY,
            court_status=CourtStatusEnum.NEED_COURT,
            court_location=None,
            expires_at=past,
            location=BroadcastLocation(area=10001),
        )

        with pytest.raises(ValueError, match="expiresAt must be in the future"):
            play_service.create_broadcast("alice", request)

    def test_create_broadcast_denormalized_fields(
        self, play_service, mock_users_repo, mock_firestore_client
    ):
        """Broadcast includes ownerName and ownerRanking from user doc"""
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.return_value = {
            "name": "Alice",
            "rankings": {
                "tennis": {"sport": "tennis", "pts": 1200, "globalRanking": 42}
            },
            "playTab": {"state": "DISCOVERY"},
        }

        mock_doc_ref = Mock()
        mock_doc_ref.id = "broadcast123"
        mock_firestore_client.collection.return_value.document.return_value = (
            mock_doc_ref
        )

        import app.services.play_service as play_service_module

        original_transactional = play_service_module.firestore.transactional

        def mock_transactional(func):
            return func

        play_service_module.firestore.transactional = mock_transactional

        try:
            request = CreateBroadcastRequest(
                sport=SportEnum.TENNIS,
                availability=AvailabilityEnum.TODAY,
                court_status=CourtStatusEnum.NEED_COURT,
                court_location=None,
                venue_ref=_curated_venue_ref(),
                expires_at=now + timedelta(hours=2),
                location=BroadcastLocation(area=10001),
            )

            response = play_service.create_broadcast("alice", request)

            assert response.broadcast_id == "broadcast123"
            mock_transaction = mock_firestore_client.transaction.return_value
            broadcast_data = mock_transaction.set.call_args.args[1]
            assert broadcast_data["ownerName"] == "Alice"
            assert broadcast_data["ownerRanking"]["pts"] == 1200
            assert broadcast_data["venueRef"]["venueId"] == "ten_twenty_club"
        finally:
            play_service_module.firestore.transactional = original_transactional


class TestSendOffer:
    def test_send_offer_discovery_to_discovery(
        self, play_service, mock_users_repo, mock_firestore_client
    ):
        """Sender and recipient both in DISCOVERY"""
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.side_effect = [
            {"name": "Alice", "rankings": {}, "playTab": {"state": "DISCOVERY"}},
            {"name": "Bob", "rankings": {}, "playTab": {"state": "DISCOVERY"}},
        ]

        mock_doc_ref = Mock()
        mock_doc_ref.id = "offer123"
        mock_firestore_client.collection.return_value.document.return_value = (
            mock_doc_ref
        )

        import app.services.play_service as play_service_module

        original_transactional = play_service_module.firestore.transactional

        def mock_transactional(func):
            return func

        play_service_module.firestore.transactional = mock_transactional

        try:
            request = SendOfferRequest(
                to_uid="bob",
                sport=SportEnum.TENNIS,
                proposed_time=now + timedelta(hours=2),
                court_location="Central Park",
                message="Let's play!",
            )

            response = play_service.send_offer("alice", request)

            assert response.offer_id == "offer123"
            assert response.to_uid == "bob"
            assert response.status == OfferStatusEnum.PENDING
        finally:
            play_service_module.firestore.transactional = original_transactional

    def test_send_offer_persists_venue_ref(
        self, play_service, mock_users_repo, mock_firestore_client
    ):
        """Offer docs persist the requested venueRef for deterministic acceptance."""
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.side_effect = [
            {"name": "Alice", "rankings": {}, "playTab": {"state": "DISCOVERY"}},
            {"name": "Bob", "rankings": {}, "playTab": {"state": "DISCOVERY"}},
        ]

        mock_doc_ref = Mock()
        mock_doc_ref.id = "offer123"
        mock_firestore_client.collection.return_value.document.return_value = (
            mock_doc_ref
        )

        import app.services.play_service as play_service_module

        original_transactional = play_service_module.firestore.transactional

        def mock_transactional(func):
            return func

        play_service_module.firestore.transactional = mock_transactional

        try:
            request = SendOfferRequest(
                to_uid="bob",
                sport=SportEnum.TENNIS,
                proposed_time=now + timedelta(hours=2),
                venue_ref=_curated_venue_ref(),
            )

            play_service.send_offer("alice", request)

            mock_transaction = mock_firestore_client.transaction.return_value
            offer_data = mock_transaction.set.call_args.args[1]
            assert offer_data["venueRef"]["venueId"] == "ten_twenty_club"
            assert offer_data["venueRef"]["name"] == "Ten Twenty Club"
        finally:
            play_service_module.firestore.transactional = original_transactional

    def test_send_offer_persists_source_broadcast_id(
        self, play_service, mock_users_repo, mock_firestore_client
    ):
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.side_effect = [
            {"name": "Alice", "rankings": {}, "playTab": {"state": "DISCOVERY"}},
            {
                "name": "Bob",
                "rankings": {},
                "playTab": {
                    "state": "BROADCAST_ACTIVE",
                    "activeBroadcastId": "broadcast123",
                    "pendingIncomingOfferIds": [],
                },
            },
        ]

        mock_doc_ref = Mock()
        mock_doc_ref.id = "offer123"
        mock_firestore_client.collection.return_value.document.return_value = (
            mock_doc_ref
        )

        import app.services.play_service as play_service_module

        original_transactional = play_service_module.firestore.transactional

        def mock_transactional(func):
            return func

        play_service_module.firestore.transactional = mock_transactional

        try:
            request = SendOfferRequest(
                to_uid="bob",
                sport=SportEnum.TENNIS,
                proposed_time=now + timedelta(hours=2),
                source_broadcast_id="broadcast123",
            )

            play_service.send_offer("alice", request)

            mock_transaction = mock_firestore_client.transaction.return_value
            offer_data = mock_transaction.set.call_args.args[1]
            assert offer_data["sourceBroadcastId"] == "broadcast123"
        finally:
            play_service_module.firestore.transactional = original_transactional

    def test_send_offer_sender_not_found(self, play_service, mock_users_repo):
        """Sender doesn't exist - raises ValueError"""
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.return_value = None

        request = SendOfferRequest(
            to_uid="bob",
            sport=SportEnum.TENNIS,
            proposed_time=now + timedelta(hours=2),
            court_location=None,
            message=None,
        )

        with pytest.raises(ValueError, match="Sender not found"):
            play_service.send_offer("alice", request)

    def test_send_offer_recipient_not_found(self, play_service, mock_users_repo):
        """Recipient doesn't exist - raises ValueError"""
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.side_effect = [
            {"name": "Alice", "playTab": {"state": "DISCOVERY"}},
            None,
        ]

        request = SendOfferRequest(
            to_uid="nonexistent",
            sport=SportEnum.TENNIS,
            proposed_time=now + timedelta(hours=2),
            court_location=None,
            message=None,
        )

        with pytest.raises(ValueError, match="Recipient not found"):
            play_service.send_offer("alice", request)

    def test_send_offer_sender_already_has_outgoing(
        self, play_service, mock_users_repo
    ):
        """Sender already has active outgoing offer - raises ValueError"""
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.return_value = {
            "name": "Alice",
            "playTab": {
                "state": "OUTGOING_OFFER_PENDING",
                "activeOutgoingOfferId": "existing_offer",
            },
        }

        request = SendOfferRequest(
            to_uid="bob",
            sport=SportEnum.TENNIS,
            proposed_time=now + timedelta(hours=2),
            court_location=None,
            message=None,
        )

        with pytest.raises(ValueError, match="already has an active outgoing offer"):
            play_service.send_offer("alice", request)


class TestAcceptOffer:
    def test_accept_offer_success(
        self,
        play_service,
        mock_offers_repo,
        mock_users_repo,
        mock_broadcasts_repo,
        mock_firestore_client,
    ):
        """Accept pending offer - creates match"""
        now = datetime.now(timezone.utc)

        mock_offer = Offer(
            offer_id="offer123",
            from_uid="alice",
            from_name="Alice",
            from_ranking=None,
            to_uid="bob",
            to_name="Bob",
            to_ranking=None,
            sport=SportEnum.TENNIS,
            proposed_time=now + timedelta(hours=1),
            court_location=None,
            venue_ref=_curated_venue_ref(),
            source_broadcast_id=None,
            message=None,
            status=OfferStatusEnum.PENDING,
            expires_at=now + timedelta(minutes=5),
            created_at=now - timedelta(minutes=1),
            match_id=None,
        )
        mock_offers_repo.get_by_id.return_value = mock_offer

        mock_users_repo.get_user_doc.side_effect = [
            {
                "name": "Bob",
                "playTab": {
                    "state": "INCOMING_OFFER_PENDING",
                    "activeBroadcastId": "broadcast123",
                    "pendingIncomingOfferIds": ["offer123"],
                },
            },
            {
                "name": "Alice",
                "playTab": {
                    "state": "OUTGOING_OFFER_PENDING",
                    "activeOutgoingOfferId": "offer123",
                },
            },
        ]

        import app.services.play_service as play_service_module

        original_transactional = play_service_module.firestore.transactional

        def mock_transactional(func):
            return func

        play_service_module.firestore.transactional = mock_transactional

        try:
            mock_transaction = mock_firestore_client.transaction.return_value
            response = play_service.accept_offer("bob", "offer123")

            assert response.offer_id == "offer123"
            assert response.status == OfferStatusEnum.ACCEPTED
            assert response.match_id is not None
            assert mock_transaction.set.call_count == 1
            match_data = mock_transaction.set.call_args.args[1]
            assert match_data["venueRef"]["venueId"] == "ten_twenty_club"
            mock_broadcasts_repo.get_by_id.assert_not_called()
        finally:
            play_service_module.firestore.transactional = original_transactional

    def test_accept_offer_uses_source_broadcast_venue(
        self,
        play_service,
        mock_offers_repo,
        mock_users_repo,
        mock_broadcasts_repo,
        mock_firestore_client,
    ):
        now = datetime.now(timezone.utc)

        mock_offer = Offer(
            offer_id="offer123",
            from_uid="alice",
            from_name="Alice",
            from_ranking=None,
            to_uid="bob",
            to_name="Bob",
            to_ranking=None,
            sport=SportEnum.TENNIS,
            proposed_time=now + timedelta(hours=1),
            court_location=None,
            venue_ref=None,
            source_broadcast_id="broadcast123",
            message=None,
            status=OfferStatusEnum.PENDING,
            expires_at=now + timedelta(minutes=5),
            created_at=now - timedelta(minutes=1),
            match_id=None,
        )
        mock_offers_repo.get_by_id.return_value = mock_offer
        mock_broadcasts_repo.get_by_id.return_value = Broadcast(
            broadcast_id="broadcast123",
            owner_uid="bob",
            owner_name="Bob",
            owner_ranking=None,
            sport=SportEnum.TENNIS,
            availability=AvailabilityEnum.TODAY,
            court_status=CourtStatusEnum.HAVE_COURT,
            court_location="Ten Twenty Club",
            venue_ref=_curated_venue_ref(),
            status=BroadcastStatusEnum.ACTIVE,
            expires_at=now + timedelta(hours=2),
            created_at=now - timedelta(minutes=5),
            location=BroadcastLocation(area=10001),
        )

        mock_users_repo.get_user_doc.side_effect = [
            {
                "name": "Bob",
                "playTab": {
                    "state": "INCOMING_OFFER_PENDING",
                    "activeBroadcastId": "broadcast123",
                    "pendingIncomingOfferIds": ["offer123"],
                },
            },
            {
                "name": "Alice",
                "playTab": {
                    "state": "OUTGOING_OFFER_PENDING",
                    "activeOutgoingOfferId": "offer123",
                },
            },
        ]

        import app.services.play_service as play_service_module

        original_transactional = play_service_module.firestore.transactional

        def mock_transactional(func):
            return func

        play_service_module.firestore.transactional = mock_transactional

        try:
            mock_transaction = mock_firestore_client.transaction.return_value
            play_service.accept_offer("bob", "offer123")

            match_data = mock_transaction.set.call_args.args[1]
            assert match_data["venueRef"]["venueId"] == "ten_twenty_club"
            mock_broadcasts_repo.get_by_id.assert_called_once_with("broadcast123")
        finally:
            play_service_module.firestore.transactional = original_transactional

    def test_accept_offer_ignores_unrelated_active_broadcast_venue(
        self,
        play_service,
        mock_offers_repo,
        mock_users_repo,
        mock_broadcasts_repo,
        mock_firestore_client,
    ):
        """Accepting a direct offer must use the offer venue, not any ambient broadcast."""
        now = datetime.now(timezone.utc)

        direct_offer_venue = VenueRef(
            venue_id="byron_clay",
            place_id=None,
            name="Byron Clay Courts",
            coordinates=GeoCoordinates(lat=37.9838, lng=23.7275),
        )
        mock_offer = Offer(
            offer_id="offer123",
            from_uid="alice",
            from_name="Alice",
            from_ranking=None,
            to_uid="bob",
            to_name="Bob",
            to_ranking=None,
            sport=SportEnum.TENNIS,
            proposed_time=now + timedelta(hours=1),
            court_location=None,
            venue_ref=direct_offer_venue,
            source_broadcast_id=None,
            message=None,
            status=OfferStatusEnum.PENDING,
            expires_at=now + timedelta(minutes=5),
            created_at=now - timedelta(minutes=1),
            match_id=None,
        )
        mock_offers_repo.get_by_id.return_value = mock_offer

        mock_users_repo.get_user_doc.side_effect = [
            {
                "name": "Bob",
                "playTab": {
                    "state": "INCOMING_OFFER_PENDING",
                    "activeBroadcastId": "broadcast123",
                    "pendingIncomingOfferIds": ["offer123"],
                },
            },
            {
                "name": "Alice",
                "playTab": {
                    "state": "OUTGOING_OFFER_PENDING",
                    "activeOutgoingOfferId": "offer123",
                },
            },
        ]

        import app.services.play_service as play_service_module

        original_transactional = play_service_module.firestore.transactional

        def mock_transactional(func):
            return func

        play_service_module.firestore.transactional = mock_transactional

        try:
            mock_transaction = mock_firestore_client.transaction.return_value
            play_service.accept_offer("bob", "offer123")

            match_data = mock_transaction.set.call_args.args[1]
            assert match_data["venueRef"]["venueId"] == "byron_clay"
            assert match_data["venueRef"]["name"] == "Byron Clay Courts"
            mock_broadcasts_repo.get_by_id.assert_not_called()
        finally:
            play_service_module.firestore.transactional = original_transactional

    def test_accept_offer_not_found(self, play_service, mock_offers_repo):
        """Offer doesn't exist - raises ValueError"""
        mock_offers_repo.get_by_id.return_value = None

        with pytest.raises(ValueError, match="Offer not found"):
            play_service.accept_offer("bob", "nonexistent")

    def test_accept_offer_not_recipient(self, play_service, mock_offers_repo):
        """Caller is not the recipient - raises ValueError"""
        now = datetime.now(timezone.utc)

        mock_offer = Offer(
            offer_id="offer123",
            from_uid="alice",
            from_name="Alice",
            from_ranking=None,
            to_uid="bob",
            to_name="Bob",
            to_ranking=None,
            sport=SportEnum.TENNIS,
            proposed_time=now + timedelta(hours=1),
            court_location=None,
            message=None,
            status=OfferStatusEnum.PENDING,
            expires_at=now + timedelta(minutes=5),
            created_at=now,
            match_id=None,
        )
        mock_offers_repo.get_by_id.return_value = mock_offer

        with pytest.raises(ValueError, match="not the recipient"):
            play_service.accept_offer("charlie", "offer123")

    def test_accept_offer_expired(self, play_service, mock_offers_repo):
        """Offer has expired - raises ValueError"""
        now = datetime.now(timezone.utc)
        past = now - timedelta(minutes=10)

        mock_offer = Offer(
            offer_id="offer123",
            from_uid="alice",
            from_name="Alice",
            from_ranking=None,
            to_uid="bob",
            to_name="Bob",
            to_ranking=None,
            sport=SportEnum.TENNIS,
            proposed_time=now + timedelta(hours=1),
            court_location=None,
            message=None,
            status=OfferStatusEnum.PENDING,
            expires_at=past,  # Expired
            created_at=past - timedelta(minutes=5),
            match_id=None,
        )
        mock_offers_repo.get_by_id.return_value = mock_offer

        with pytest.raises(ValueError, match="expired"):
            play_service.accept_offer("bob", "offer123")


class TestDeclineOffer:
    def test_decline_offer_success(
        self, play_service, mock_offers_repo, mock_users_repo, mock_firestore_client
    ):
        """Decline pending offer"""
        now = datetime.now(timezone.utc)

        mock_offer = Offer(
            offer_id="offer123",
            from_uid="alice",
            from_name="Alice",
            from_ranking=None,
            to_uid="bob",
            to_name="Bob",
            to_ranking=None,
            sport=SportEnum.TENNIS,
            proposed_time=now + timedelta(hours=1),
            court_location=None,
            message=None,
            status=OfferStatusEnum.PENDING,
            expires_at=now + timedelta(minutes=5),
            created_at=now,
            match_id=None,
        )
        mock_offers_repo.get_by_id.return_value = mock_offer

        mock_users_repo.get_user_doc.side_effect = [
            {
                "name": "Bob",
                "playTab": {
                    "state": "INCOMING_OFFER_PENDING",
                    "pendingIncomingOfferIds": ["offer123"],
                },
            },
            {
                "name": "Alice",
                "playTab": {
                    "state": "OUTGOING_OFFER_PENDING",
                    "activeOutgoingOfferId": "offer123",
                },
            },
        ]

        import app.services.play_service as play_service_module

        original_transactional = play_service_module.firestore.transactional

        def mock_transactional(func):
            return func

        play_service_module.firestore.transactional = mock_transactional

        try:
            response = play_service.decline_offer("bob", "offer123")

            assert response.offer_id == "offer123"
            assert response.status == OfferStatusEnum.DECLINED
        finally:
            play_service_module.firestore.transactional = original_transactional

    def test_decline_offer_not_recipient(self, play_service, mock_offers_repo):
        """Caller is not the recipient - raises ValueError"""
        now = datetime.now(timezone.utc)

        mock_offer = Offer(
            offer_id="offer123",
            from_uid="alice",
            from_name="Alice",
            from_ranking=None,
            to_uid="bob",
            to_name="Bob",
            to_ranking=None,
            sport=SportEnum.TENNIS,
            proposed_time=now + timedelta(hours=1),
            court_location=None,
            message=None,
            status=OfferStatusEnum.PENDING,
            expires_at=now + timedelta(minutes=5),
            created_at=now,
            match_id=None,
        )
        mock_offers_repo.get_by_id.return_value = mock_offer

        with pytest.raises(ValueError, match="not the recipient"):
            play_service.decline_offer("charlie", "offer123")


class TestCancelOffer:
    def test_cancel_offer_success(
        self, play_service, mock_offers_repo, mock_users_repo, mock_firestore_client
    ):
        """Cancel outgoing offer"""
        now = datetime.now(timezone.utc)

        mock_offer = Offer(
            offer_id="offer123",
            from_uid="alice",
            from_name="Alice",
            from_ranking=None,
            to_uid="bob",
            to_name="Bob",
            to_ranking=None,
            sport=SportEnum.TENNIS,
            proposed_time=now + timedelta(hours=1),
            court_location=None,
            message=None,
            status=OfferStatusEnum.PENDING,
            expires_at=now + timedelta(minutes=5),
            created_at=now,
            match_id=None,
        )
        mock_offers_repo.get_by_id.return_value = mock_offer

        mock_users_repo.get_user_doc.side_effect = [
            {
                "name": "Alice",
                "playTab": {
                    "state": "OUTGOING_OFFER_PENDING",
                    "activeOutgoingOfferId": "offer123",
                },
            },
            {
                "name": "Bob",
                "playTab": {
                    "state": "INCOMING_OFFER_PENDING",
                    "pendingIncomingOfferIds": ["offer123"],
                },
            },
        ]

        import app.services.play_service as play_service_module

        original_transactional = play_service_module.firestore.transactional

        def mock_transactional(func):
            return func

        play_service_module.firestore.transactional = mock_transactional

        try:
            response = play_service.cancel_offer("alice", "offer123")

            assert response.offer_id == "offer123"
            assert response.status == OfferStatusEnum.CANCELLED
        finally:
            play_service_module.firestore.transactional = original_transactional

    def test_cancel_offer_not_sender(self, play_service, mock_offers_repo):
        """Caller is not the sender - raises ValueError"""
        now = datetime.now(timezone.utc)

        mock_offer = Offer(
            offer_id="offer123",
            from_uid="alice",
            from_name="Alice",
            from_ranking=None,
            to_uid="bob",
            to_name="Bob",
            to_ranking=None,
            sport=SportEnum.TENNIS,
            proposed_time=now + timedelta(hours=1),
            court_location=None,
            message=None,
            status=OfferStatusEnum.PENDING,
            expires_at=now + timedelta(minutes=5),
            created_at=now,
            match_id=None,
        )
        mock_offers_repo.get_by_id.return_value = mock_offer

        with pytest.raises(ValueError, match="not the sender"):
            play_service.cancel_offer("charlie", "offer123")
