from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from app.models.common import GeoCoordinates, VenueRef
from app.models.enums import (
    AvailabilityEnum,
    BroadcastStatusEnum,
    BroadcastTypeEnum,
    CourtStatusEnum,
    MatchTypeEnum,
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
    repo = Mock(spec=BroadcastsRepo)
    # list_active must return an iterable (used by DISCOVERY payload builder)
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
        from app.models.play import DiscoveryPayload

        mock_users_repo.get_user_doc.return_value = None

        response = play_service.get_me_state("nonexistent_user")

        assert response.mode == PlayTabStateEnum.DISCOVERY
        assert isinstance(response.payload, DiscoveryPayload)

    def test_get_me_state_discovery(
        self, play_service, mock_users_repo, mock_broadcasts_repo
    ):
        """Returns DISCOVERY mode with DiscoveryPayload"""
        from app.models.play import DiscoveryPayload

        mock_users_repo.get_user_doc.return_value = {
            "name": "Alice",
            "playTab": {"state": "DISCOVERY"},
        }
        mock_broadcasts_repo.list_active.return_value = []

        response = play_service.get_me_state("alice")

        assert response.mode == PlayTabStateEnum.DISCOVERY
        assert isinstance(response.payload, DiscoveryPayload)

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
            venue_ref=_curated_venue_ref(),
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
        assert response.payload["venue_ref"]["venueId"] == "ten_twenty_club"
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
        # Defaults from a singles broadcast surface in the discovery payload.
        assert response.payload["match_type"] == MatchTypeEnum.SINGLES.value
        assert (
            response.payload["broadcast_type"] == BroadcastTypeEnum.FIND_OPPONENT.value
        )
        assert response.payload["partner_uid"] is None

    def test_get_me_state_broadcast_active_doubles_find_fourth(
        self, play_service, mock_users_repo, mock_broadcasts_repo, mock_offers_repo
    ):
        """BROADCAST_ACTIVE on a doubles 'find a 4th' broadcast surfaces
        match_type/broadcast_type in the payload (mobile renders 'Looking for
        a 4th' badges)."""
        now = datetime.now(timezone.utc)
        user_docs = {
            "alice": {
                "name": "Alice",
                "playTab": {
                    "state": "BROADCAST_ACTIVE",
                    "activeBroadcastId": "broadcast_dbl",
                    "pendingIncomingOfferIds": [],
                },
            },
            "bob": {"name": "Bob Brown"},
        }
        mock_users_repo.get_user_doc.side_effect = lambda uid: user_docs.get(uid)

        mock_broadcast = Broadcast(
            broadcast_id="broadcast_dbl",
            owner_uid="alice",
            owner_name="Alice",
            owner_ranking=None,
            sport=SportEnum.PADEL,
            match_type=MatchTypeEnum.DOUBLES,
            broadcast_type=BroadcastTypeEnum.FIND_FOURTH,
            partner_uid="bob",
            availability=AvailabilityEnum.TODAY,
            court_status=CourtStatusEnum.HAVE_COURT,
            court_location="Padel Club",
            status=BroadcastStatusEnum.ACTIVE,
            expires_at=now + timedelta(hours=2),
            created_at=now,
            location=BroadcastLocation(area=10001),
        )
        mock_broadcasts_repo.get_by_id.return_value = mock_broadcast
        mock_offers_repo.get_by_ids.return_value = []

        response = play_service.get_me_state("alice")

        assert response.mode == PlayTabStateEnum.BROADCAST_ACTIVE
        assert response.payload["match_type"] == MatchTypeEnum.DOUBLES.value
        assert response.payload["broadcast_type"] == BroadcastTypeEnum.FIND_FOURTH.value
        assert response.payload["partner_uid"] == "bob"
        # DBL-7: partner_name is resolved from the partner's user doc.
        assert response.payload["partner_name"] == "Bob Brown"

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
        user_docs = {
            "alice": {
                "name": "Alice Anderson",
                "playTab": {
                    "state": "MATCH_SCHEDULED",
                    "activeMatchId": "match_offer123",
                },
            },
            "bob": {
                "name": "Bob Brown",
                "profileUrl": "https://example.com/bob.png",
                "rankings": {
                    "tennis": {"sport": "tennis", "pts": 1200, "globalRanking": 42}
                },
            },
        }
        mock_users_repo.get_user_doc.side_effect = lambda uid: user_docs.get(uid)
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
        assert response.payload["match_type"] == MatchTypeEnum.SINGLES.value
        assert response.payload["venue_ref"]["venueId"] == "ten_twenty_club"
        assert response.payload["opponent"]["uid"] == "bob"
        assert response.payload["opponent"]["ranking"]["global_ranking"] == 42
        # Singles: participants array has 2 entries with team=None (DBL-7).
        participants = response.payload["participants"]
        assert len(participants) == 2
        assert {p["uid"] for p in participants} == {"alice", "bob"}
        assert all(p["team"] is None for p in participants)
        assert all(p["role"] == "player" for p in participants)

    def test_get_me_state_match_scheduled_doubles(
        self, play_service, mock_users_repo, mock_matches_repo
    ):
        """Doubles MATCH_SCHEDULED returns participants with team A/B and matchType=doubles."""
        now = datetime.now(timezone.utc)
        user_docs = {
            "alice": {
                "name": "Alice Anderson",
                "playTab": {
                    "state": "MATCH_SCHEDULED",
                    "activeMatchId": "match_dbl",
                },
            },
            "bob": {"name": "Bob Brown"},
            "carol": {"name": "Carol Carr"},
            "dave": {"name": "Dave Doe"},
        }
        mock_users_repo.get_user_doc.side_effect = lambda uid: user_docs.get(uid)
        mock_matches_repo.get_by_id.return_value = Match(
            match_id="match_dbl",
            sport=SportEnum.PADEL,
            status="scheduled",
            match_type=MatchTypeEnum.DOUBLES,
            scheduled_at=now + timedelta(hours=2),
            participants=[
                MatchParticipant(
                    uid="alice", team="A", role="player", display_name="Alice A."
                ),
                MatchParticipant(
                    uid="bob", team="A", role="player", display_name="Bob B."
                ),
                MatchParticipant(
                    uid="carol", team="B", role="player", display_name="Carol C."
                ),
                MatchParticipant(
                    uid="dave", team="B", role="player", display_name="Dave D."
                ),
            ],
            participant_uids=["alice", "bob", "carol", "dave"],
        )

        response = play_service.get_me_state("alice")

        assert response.mode == PlayTabStateEnum.MATCH_SCHEDULED
        assert response.payload["match_type"] == MatchTypeEnum.DOUBLES.value
        participants = response.payload["participants"]
        assert len(participants) == 4
        teams = {p["uid"]: p["team"] for p in participants}
        assert teams == {"alice": "A", "bob": "A", "carol": "B", "dave": "B"}
        names = {p["uid"]: p["name"] for p in participants}
        assert names["alice"] == "Alice A."
        assert names["dave"] == "Dave D."


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
                court_status=CourtStatusEnum.HAVE_COURT,
                court_location="Central Park",
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

    def test_create_broadcast_need_court_ignores_venue_ref(
        self, play_service, mock_users_repo, mock_firestore_client
    ):
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.return_value = {
            "name": "Alice",
            "rankings": {},
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

            play_service.create_broadcast("alice", request)

            mock_transaction = mock_firestore_client.transaction.return_value
            broadcast_data = mock_transaction.set.call_args.args[1]
            assert broadcast_data["venueRef"] is None
        finally:
            play_service_module.firestore.transactional = original_transactional

    def test_create_broadcast_have_court_without_venue_ref_logs_warning(
        self, play_service, mock_users_repo, mock_firestore_client, caplog
    ):
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.return_value = {
            "name": "Alice",
            "rankings": {},
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
                court_status=CourtStatusEnum.HAVE_COURT,
                court_location="Central Park",
                venue_ref=None,
                expires_at=now + timedelta(hours=2),
                location=BroadcastLocation(area=10001),
            )

            with caplog.at_level("WARNING", logger="app.services.play_service"):
                play_service.create_broadcast("alice", request)

            assert "Broadcast created without venueRef" in caplog.text
        finally:
            play_service_module.firestore.transactional = original_transactional

    def test_create_broadcast_doubles_find_opponent_persists_doubles_fields(
        self, play_service, mock_users_repo, mock_firestore_client
    ):
        """Doubles + find_opponent + partner is persisted on the Firestore doc."""
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.return_value = {
            "name": "Alice",
            "rankings": {},
            "playTab": {"state": "DISCOVERY"},
        }

        mock_doc_ref = Mock()
        mock_doc_ref.id = "broadcast_doubles"
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
                match_type=MatchTypeEnum.DOUBLES,
                broadcast_type=BroadcastTypeEnum.FIND_OPPONENT,
                partner_uid="bob",
                availability=AvailabilityEnum.TODAY,
                court_status=CourtStatusEnum.NEED_COURT,
                expires_at=now + timedelta(hours=2),
                location=BroadcastLocation(area=10001),
            )

            response = play_service.create_broadcast("alice", request)

            assert response.match_type == MatchTypeEnum.DOUBLES
            assert response.broadcast_type == BroadcastTypeEnum.FIND_OPPONENT
            assert response.partner_uid == "bob"

            mock_transaction = mock_firestore_client.transaction.return_value
            broadcast_data = mock_transaction.set.call_args.args[1]
            assert broadcast_data["matchType"] == "doubles"
            assert broadcast_data["broadcastType"] == "find_opponent"
            assert broadcast_data["partnerUid"] == "bob"
        finally:
            play_service_module.firestore.transactional = original_transactional

    def test_create_broadcast_doubles_find_fourth_without_partner(
        self, play_service, mock_users_repo, mock_firestore_client
    ):
        """Doubles + find_fourth without partner persists partnerUid=None."""
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.return_value = {
            "name": "Alice",
            "rankings": {},
            "playTab": {"state": "DISCOVERY"},
        }

        mock_doc_ref = Mock()
        mock_doc_ref.id = "broadcast_4th"
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
                sport=SportEnum.PADEL,
                match_type=MatchTypeEnum.DOUBLES,
                broadcast_type=BroadcastTypeEnum.FIND_FOURTH,
                availability=AvailabilityEnum.WEEKEND,
                court_status=CourtStatusEnum.NEED_COURT,
                expires_at=now + timedelta(hours=2),
                location=BroadcastLocation(area=10001),
            )

            response = play_service.create_broadcast("alice", request)

            assert response.match_type == MatchTypeEnum.DOUBLES
            assert response.broadcast_type == BroadcastTypeEnum.FIND_FOURTH
            assert response.partner_uid is None

            mock_transaction = mock_firestore_client.transaction.return_value
            broadcast_data = mock_transaction.set.call_args.args[1]
            assert broadcast_data["matchType"] == "doubles"
            assert broadcast_data["broadcastType"] == "find_fourth"
            assert broadcast_data["partnerUid"] is None
        finally:
            play_service_module.firestore.transactional = original_transactional

    def test_create_broadcast_singles_clears_partner_uid(
        self, play_service, mock_users_repo, mock_firestore_client
    ):
        """A singles broadcast must never persist a partnerUid even if one
        somehow leaks into the request."""
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.return_value = {
            "name": "Alice",
            "rankings": {},
            "playTab": {"state": "DISCOVERY"},
        }

        mock_doc_ref = Mock()
        mock_doc_ref.id = "broadcast_singles"
        mock_firestore_client.collection.return_value.document.return_value = (
            mock_doc_ref
        )

        import app.services.play_service as play_service_module

        original_transactional = play_service_module.firestore.transactional

        def mock_transactional(func):
            return func

        play_service_module.firestore.transactional = mock_transactional

        try:
            # Construct a request and then mutate ``partner_uid`` to mimic the
            # service receiving an ill-formed but model-valid request.
            request = CreateBroadcastRequest(
                sport=SportEnum.TENNIS,
                match_type=MatchTypeEnum.SINGLES,
                broadcast_type=BroadcastTypeEnum.FIND_OPPONENT,
                availability=AvailabilityEnum.TODAY,
                court_status=CourtStatusEnum.NEED_COURT,
                expires_at=now + timedelta(hours=2),
                location=BroadcastLocation(area=10001),
            )
            object.__setattr__(request, "partner_uid", "ghost_partner")

            response = play_service.create_broadcast("alice", request)

            assert response.partner_uid is None
            mock_transaction = mock_firestore_client.transaction.return_value
            broadcast_data = mock_transaction.set.call_args.args[1]
            assert broadcast_data["partnerUid"] is None
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
        self,
        play_service,
        mock_users_repo,
        mock_broadcasts_repo,
        mock_firestore_client,
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
        # DBL-4: send_offer reads the source broadcast to validate match_type.
        # Return a singles broadcast so the validation passes for this case.
        mock_broadcasts_repo.get_by_id.return_value = Broadcast(
            broadcast_id="broadcast123",
            owner_uid="bob",
            owner_name="Bob",
            owner_ranking=None,
            sport=SportEnum.TENNIS,
            match_type=MatchTypeEnum.SINGLES,
            broadcast_type=BroadcastTypeEnum.FIND_OPPONENT,
            partner_uid=None,
            availability=AvailabilityEnum.TODAY,
            court_status=CourtStatusEnum.HAVE_COURT,
            court_location="Central Park",
            venue_ref=None,
            status=BroadcastStatusEnum.ACTIVE,
            expires_at=now + timedelta(hours=2),
            created_at=now - timedelta(minutes=1),
            location=BroadcastLocation(area=10001),
        )

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
            # DBL-4: singles offer persists matchType=singles and partnerUid=null
            assert offer_data["matchType"] == "singles"
            assert offer_data["partnerUid"] is None
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
            # DBL-2: matchType + resultSubmittedBy + per-participant displayName
            # are stamped on the new match document.
            assert match_data["matchType"] == "singles"
            assert match_data["resultSubmittedBy"] == []
            participants = match_data["participants"]
            assert len(participants) == 2
            assert all("displayName" in p for p in participants)
            # Single-token names round-trip as-is via _short_display_name.
            sender_entry = next(p for p in participants if p["uid"] == "alice")
            recipient_entry = next(p for p in participants if p["uid"] == "bob")
            assert sender_entry["displayName"] == "Alice"
            assert recipient_entry["displayName"] == "Bob"
            mock_broadcasts_repo.get_by_id.assert_not_called()
        finally:
            play_service_module.firestore.transactional = original_transactional

    def test_accept_offer_writes_short_display_name(
        self,
        play_service,
        mock_offers_repo,
        mock_users_repo,
        mock_broadcasts_repo,
        mock_firestore_client,
    ):
        """DBL-2: full ``Firstname Lastname`` is written as ``Firstname L.``."""
        now = datetime.now(timezone.utc)

        mock_offer = Offer(
            offer_id="offer123",
            from_uid="alice",
            from_name="Alice King",
            from_ranking=None,
            to_uid="bob",
            to_name="Bob Smith",
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
                "name": "Bob Smith",
                "playTab": {
                    "state": "INCOMING_OFFER_PENDING",
                    "activeBroadcastId": None,
                    "pendingIncomingOfferIds": ["offer123"],
                },
            },
            {
                "name": "Alice King",
                "playTab": {
                    "state": "OUTGOING_OFFER_PENDING",
                    "activeOutgoingOfferId": "offer123",
                },
            },
        ]

        import app.services.play_service as play_service_module

        original_transactional = play_service_module.firestore.transactional
        play_service_module.firestore.transactional = lambda fn: fn

        try:
            mock_transaction = mock_firestore_client.transaction.return_value
            play_service.accept_offer("bob", "offer123")

            match_data = mock_transaction.set.call_args.args[1]
            participants = {p["uid"]: p for p in match_data["participants"]}
            assert participants["alice"]["displayName"] == "Alice K."
            assert participants["bob"]["displayName"] == "Bob S."
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


# ===== DBL-4: Doubles offer + acceptance flow =====


def _doubles_broadcast(
    *,
    owner_uid: str = "bob",
    partner_uid: str | None = "dave",
    broadcast_type: BroadcastTypeEnum = BroadcastTypeEnum.FIND_OPPONENT,
    sport: SportEnum = SportEnum.PADEL,
    venue_ref: VenueRef | None = None,
) -> Broadcast:
    now = datetime.now(timezone.utc)
    return Broadcast(
        broadcast_id="broadcast_doubles",
        owner_uid=owner_uid,
        owner_name="Bob",
        owner_ranking=None,
        sport=sport,
        match_type=MatchTypeEnum.DOUBLES,
        broadcast_type=broadcast_type,
        partner_uid=partner_uid,
        availability=AvailabilityEnum.TODAY,
        court_status=CourtStatusEnum.HAVE_COURT,
        court_location="Padel Athens",
        venue_ref=venue_ref,
        status=BroadcastStatusEnum.ACTIVE,
        expires_at=now + timedelta(hours=2),
        created_at=now - timedelta(minutes=5),
        location=BroadcastLocation(area=10001),
    )


class TestDoublesSendOffer:
    """DBL-4: doubles validation on the send-offer path."""

    def test_send_offer_doubles_requires_partner_uid_in_request_model(self):
        """SendOfferRequest with match_type=doubles and no partner_uid raises."""
        now = datetime.now(timezone.utc)
        with pytest.raises(ValueError, match="partner_uid"):
            SendOfferRequest(
                to_uid="bob",
                sport=SportEnum.PADEL,
                match_type=MatchTypeEnum.DOUBLES,
                proposed_time=now + timedelta(hours=2),
            )

    def test_send_offer_singles_must_not_carry_partner_uid(self):
        """Singles offer with partner_uid raises at the model level."""
        now = datetime.now(timezone.utc)
        with pytest.raises(ValueError, match="singles offer"):
            SendOfferRequest(
                to_uid="bob",
                sport=SportEnum.TENNIS,
                match_type=MatchTypeEnum.SINGLES,
                partner_uid="charlie",
                proposed_time=now + timedelta(hours=2),
            )

    def test_send_offer_direct_doubles_without_source_broadcast_rejected(
        self,
        play_service,
        mock_users_repo,
        mock_broadcasts_repo,
    ):
        """Direct doubles challenge (no source_broadcast_id) is rejected at
        send_offer time so we never create an offer accept_offer can't satisfy.
        """
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.side_effect = [
            # sender
            {"name": "Alice", "rankings": {}, "playTab": {"state": "DISCOVERY"}},
            # recipient — also in DISCOVERY, no active broadcast
            {
                "name": "Bob",
                "rankings": {},
                "playTab": {"state": "DISCOVERY"},
            },
        ]
        mock_broadcasts_repo.get_by_id.return_value = None

        request = SendOfferRequest(
            to_uid="bob",
            sport=SportEnum.PADEL,
            match_type=MatchTypeEnum.DOUBLES,
            partner_uid="charlie",
            proposed_time=now + timedelta(hours=2),
            source_broadcast_id=None,
        )
        with pytest.raises(ValueError, match="source broadcast"):
            play_service.send_offer("alice", request)

    def test_send_offer_doubles_match_type_must_match_broadcast(
        self,
        play_service,
        mock_users_repo,
        mock_broadcasts_repo,
    ):
        """Singles offer against a doubles broadcast → ValueError."""
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.side_effect = [
            {"name": "Alice", "rankings": {}, "playTab": {"state": "DISCOVERY"}},
            {
                "name": "Bob",
                "rankings": {},
                "playTab": {
                    "state": "BROADCAST_ACTIVE",
                    "activeBroadcastId": "broadcast_doubles",
                    "pendingIncomingOfferIds": [],
                },
            },
        ]
        mock_broadcasts_repo.get_by_id.return_value = _doubles_broadcast()

        request = SendOfferRequest(
            to_uid="bob",
            sport=SportEnum.PADEL,
            match_type=MatchTypeEnum.SINGLES,
            proposed_time=now + timedelta(hours=2),
            source_broadcast_id="broadcast_doubles",
        )
        with pytest.raises(ValueError, match="does not match broadcast match_type"):
            play_service.send_offer("alice", request)

    def test_send_offer_doubles_partner_must_exist(
        self,
        play_service,
        mock_users_repo,
        mock_broadcasts_repo,
    ):
        """Doubles offer with non-existent partner_uid → ValueError."""
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.side_effect = [
            # sender
            {"name": "Alice", "rankings": {}, "playTab": {"state": "DISCOVERY"}},
            # recipient (broadcaster)
            {
                "name": "Bob",
                "rankings": {},
                "playTab": {
                    "state": "BROADCAST_ACTIVE",
                    "activeBroadcastId": "broadcast_doubles",
                    "pendingIncomingOfferIds": [],
                },
            },
            # partner lookup → not found
            None,
        ]
        mock_broadcasts_repo.get_by_id.return_value = _doubles_broadcast()

        request = SendOfferRequest(
            to_uid="bob",
            sport=SportEnum.PADEL,
            match_type=MatchTypeEnum.DOUBLES,
            partner_uid="ghost_partner",
            proposed_time=now + timedelta(hours=2),
            source_broadcast_id="broadcast_doubles",
        )
        with pytest.raises(ValueError, match="Partner user not found"):
            play_service.send_offer("alice", request)

    def test_send_offer_doubles_broadcast_partner_must_exist(
        self,
        play_service,
        mock_users_repo,
        mock_broadcasts_repo,
        mock_firestore_client,
    ):
        """Doubles offer where the broadcast's stored partner_uid does not
        exist as a user → ValueError at send_offer time, before any write.

        Without this fail-fast check, both users would be moved into pending
        states and accept_offer would later fail when looking up the
        broadcaster's partner.
        """
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.side_effect = [
            # sender
            {"name": "Alice", "rankings": {}, "playTab": {"state": "DISCOVERY"}},
            # recipient (broadcaster)
            {
                "name": "Bob",
                "rankings": {},
                "playTab": {
                    "state": "BROADCAST_ACTIVE",
                    "activeBroadcastId": "broadcast_doubles",
                    "pendingIncomingOfferIds": [],
                },
            },
            # challenger's partner (charlie) exists
            {"name": "Charlie", "rankings": {}},
            # broadcast partner lookup (ghost_dave) → not found
            None,
        ]
        mock_broadcasts_repo.get_by_id.return_value = _doubles_broadcast(
            partner_uid="ghost_dave",
        )

        request = SendOfferRequest(
            to_uid="bob",
            sport=SportEnum.PADEL,
            match_type=MatchTypeEnum.DOUBLES,
            partner_uid="charlie",
            proposed_time=now + timedelta(hours=2),
            source_broadcast_id="broadcast_doubles",
        )
        with pytest.raises(ValueError, match="Broadcast partner user not found"):
            play_service.send_offer("alice", request)

        # No writes should have happened.
        assert not mock_firestore_client.transaction.called

    def test_send_offer_doubles_rejects_duplicate_uids(
        self,
        play_service,
        mock_users_repo,
        mock_broadcasts_repo,
    ):
        """Sender = partner is rejected as a duplicate."""
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.side_effect = [
            {"name": "Alice", "rankings": {}, "playTab": {"state": "DISCOVERY"}},
            {
                "name": "Bob",
                "rankings": {},
                "playTab": {
                    "state": "BROADCAST_ACTIVE",
                    "activeBroadcastId": "broadcast_doubles",
                    "pendingIncomingOfferIds": [],
                },
            },
        ]
        mock_broadcasts_repo.get_by_id.return_value = _doubles_broadcast()

        request = SendOfferRequest(
            to_uid="bob",
            sport=SportEnum.PADEL,
            match_type=MatchTypeEnum.DOUBLES,
            partner_uid="alice",  # same as sender
            proposed_time=now + timedelta(hours=2),
            source_broadcast_id="broadcast_doubles",
        )
        with pytest.raises(ValueError, match="distinct"):
            play_service.send_offer("alice", request)

    def test_send_offer_doubles_persists_match_type_and_partner_uid(
        self,
        play_service,
        mock_users_repo,
        mock_broadcasts_repo,
        mock_firestore_client,
    ):
        """Doubles offer happy path: matchType + partnerUid persisted."""
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.side_effect = [
            # sender
            {"name": "Alice", "rankings": {}, "playTab": {"state": "DISCOVERY"}},
            # recipient (broadcaster)
            {
                "name": "Bob",
                "rankings": {},
                "playTab": {
                    "state": "BROADCAST_ACTIVE",
                    "activeBroadcastId": "broadcast_doubles",
                    "pendingIncomingOfferIds": [],
                },
            },
            # partner
            {"name": "Charlie", "rankings": {}, "playTab": {"state": "DISCOVERY"}},
            # broadcast partner (dave)
            {"name": "Dave", "rankings": {}, "playTab": {"state": "DISCOVERY"}},
        ]
        mock_broadcasts_repo.get_by_id.return_value = _doubles_broadcast()

        mock_doc_ref = Mock()
        mock_doc_ref.id = "offer_doubles"
        mock_firestore_client.collection.return_value.document.return_value = (
            mock_doc_ref
        )

        import app.services.play_service as play_service_module

        original_transactional = play_service_module.firestore.transactional
        play_service_module.firestore.transactional = lambda fn: fn

        try:
            request = SendOfferRequest(
                to_uid="bob",
                sport=SportEnum.PADEL,
                match_type=MatchTypeEnum.DOUBLES,
                partner_uid="charlie",
                proposed_time=now + timedelta(hours=2),
                source_broadcast_id="broadcast_doubles",
            )

            response = play_service.send_offer("alice", request)

            assert response.match_type == MatchTypeEnum.DOUBLES
            assert response.partner_uid == "charlie"
            mock_transaction = mock_firestore_client.transaction.return_value
            offer_data = mock_transaction.set.call_args.args[1]
            assert offer_data["matchType"] == "doubles"
            assert offer_data["partnerUid"] == "charlie"
        finally:
            play_service_module.firestore.transactional = original_transactional

    def test_send_offer_rejects_find_fourth_broadcast(
        self,
        play_service,
        mock_users_repo,
        mock_broadcasts_repo,
    ):
        """Offers against find_fourth broadcasts are explicitly deferred."""
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.side_effect = [
            {"name": "Alice", "rankings": {}, "playTab": {"state": "DISCOVERY"}},
            {
                "name": "Bob",
                "rankings": {},
                "playTab": {
                    "state": "BROADCAST_ACTIVE",
                    "activeBroadcastId": "broadcast_doubles",
                    "pendingIncomingOfferIds": [],
                },
            },
        ]
        mock_broadcasts_repo.get_by_id.return_value = _doubles_broadcast(
            broadcast_type=BroadcastTypeEnum.FIND_FOURTH,
            partner_uid=None,
        )

        request = SendOfferRequest(
            to_uid="bob",
            sport=SportEnum.PADEL,
            match_type=MatchTypeEnum.DOUBLES,
            partner_uid="charlie",
            proposed_time=now + timedelta(hours=2),
            source_broadcast_id="broadcast_doubles",
        )
        with pytest.raises(ValueError, match="find_fourth"):
            play_service.send_offer("alice", request)


class TestDoublesAcceptOffer:
    """DBL-4: doubles match-creation transaction in accept_offer."""

    def test_accept_doubles_offer_creates_4_participant_match(
        self,
        play_service,
        mock_offers_repo,
        mock_users_repo,
        mock_broadcasts_repo,
        mock_firestore_client,
    ):
        """4 distinct UIDs → match with 2-A / 2-B participants; all 4 → MATCH_SCHEDULED."""
        now = datetime.now(timezone.utc)

        mock_offer = Offer(
            offer_id="offer_doubles",
            from_uid="alice",
            from_name="Alice",
            from_ranking=None,
            to_uid="bob",
            to_name="Bob",
            to_ranking=None,
            sport=SportEnum.PADEL,
            match_type=MatchTypeEnum.DOUBLES,
            partner_uid="charlie",
            proposed_time=now + timedelta(hours=1),
            court_location=None,
            venue_ref=_curated_venue_ref(),
            source_broadcast_id="broadcast_doubles",
            message=None,
            status=OfferStatusEnum.PENDING,
            expires_at=now + timedelta(minutes=5),
            created_at=now - timedelta(minutes=1),
            match_id=None,
        )
        mock_offers_repo.get_by_id.return_value = mock_offer
        mock_broadcasts_repo.get_by_id.return_value = _doubles_broadcast(
            owner_uid="bob",
            partner_uid="dave",
        )

        mock_users_repo.get_user_doc.side_effect = [
            # recipient (broadcaster)
            {
                "name": "Bob Smith",
                "playTab": {
                    "state": "BROADCAST_ACTIVE",
                    "activeBroadcastId": "broadcast_doubles",
                    "pendingIncomingOfferIds": ["offer_doubles"],
                },
            },
            # sender (challenger)
            {
                "name": "Alice King",
                "playTab": {
                    "state": "OUTGOING_OFFER_PENDING",
                    "activeOutgoingOfferId": "offer_doubles",
                },
            },
            # recipient's partner
            {"name": "Dave Knight", "playTab": {"state": "DISCOVERY"}},
            # sender's partner
            {"name": "Charlie Owen", "playTab": {"state": "DISCOVERY"}},
        ]

        import app.services.play_service as play_service_module

        original_transactional = play_service_module.firestore.transactional
        play_service_module.firestore.transactional = lambda fn: fn

        try:
            mock_transaction = mock_firestore_client.transaction.return_value
            response = play_service.accept_offer("bob", "offer_doubles")

            assert response.status == OfferStatusEnum.ACCEPTED

            match_data = mock_transaction.set.call_args.args[1]
            assert match_data["matchType"] == "doubles"
            participants = match_data["participants"]
            assert len(participants) == 4

            by_uid = {p["uid"]: p for p in participants}
            assert by_uid["bob"]["team"] == "A"
            assert by_uid["dave"]["team"] == "A"
            assert by_uid["alice"]["team"] == "B"
            assert by_uid["charlie"]["team"] == "B"

            # Cached short display names (DBL-1 contract).
            assert by_uid["alice"]["displayName"] == "Alice K."
            assert by_uid["bob"]["displayName"] == "Bob S."
            assert by_uid["charlie"]["displayName"] == "Charlie O."
            assert by_uid["dave"]["displayName"] == "Dave K."

            # Flattened uids cover all 4 players.
            assert set(match_data["participantUids"]) == {
                "alice",
                "bob",
                "charlie",
                "dave",
            }
            # Pair key only meaningful for 2-player singles.
            assert match_data["participantPair"] is None

            # All 4 users transitioned to MATCH_SCHEDULED. We can't tell the
            # document refs apart with a generic Mock client, but we can check
            # how many of the update calls carried a MATCH_SCHEDULED state
            # patch — one per user, plus one for the offer (status=accepted)
            # and one for the broadcast (status=matched).
            match_scheduled_calls = [
                call
                for call in mock_transaction.update.call_args_list
                if call.args[1].get("playTab.state") == "MATCH_SCHEDULED"
            ]
            assert len(match_scheduled_calls) == 4
        finally:
            play_service_module.firestore.transactional = original_transactional

    def test_accept_doubles_offer_rejects_duplicate_uids(
        self,
        play_service,
        mock_offers_repo,
        mock_users_repo,
        mock_broadcasts_repo,
    ):
        """Sender's partner == recipient's partner → rejected."""
        now = datetime.now(timezone.utc)

        mock_offer = Offer(
            offer_id="offer_doubles",
            from_uid="alice",
            from_name="Alice",
            from_ranking=None,
            to_uid="bob",
            to_name="Bob",
            to_ranking=None,
            sport=SportEnum.PADEL,
            match_type=MatchTypeEnum.DOUBLES,
            partner_uid="dave",  # same as recipient's partner
            proposed_time=now + timedelta(hours=1),
            court_location=None,
            venue_ref=None,
            source_broadcast_id="broadcast_doubles",
            message=None,
            status=OfferStatusEnum.PENDING,
            expires_at=now + timedelta(minutes=5),
            created_at=now - timedelta(minutes=1),
            match_id=None,
        )
        mock_offers_repo.get_by_id.return_value = mock_offer
        mock_broadcasts_repo.get_by_id.return_value = _doubles_broadcast(
            owner_uid="bob",
            partner_uid="dave",
        )
        mock_users_repo.get_user_doc.side_effect = [
            {"name": "Bob", "playTab": {"state": "BROADCAST_ACTIVE"}},
            {"name": "Alice", "playTab": {"state": "OUTGOING_OFFER_PENDING"}},
        ]

        with pytest.raises(ValueError, match="distinct"):
            play_service.accept_offer("bob", "offer_doubles")

    def test_accept_doubles_offer_requires_source_broadcast_partner(
        self,
        play_service,
        mock_offers_repo,
        mock_users_repo,
        mock_broadcasts_repo,
    ):
        """Doubles offer without a source broadcast → can't infer team A."""
        now = datetime.now(timezone.utc)

        mock_offer = Offer(
            offer_id="offer_doubles",
            from_uid="alice",
            from_name="Alice",
            from_ranking=None,
            to_uid="bob",
            to_name="Bob",
            to_ranking=None,
            sport=SportEnum.PADEL,
            match_type=MatchTypeEnum.DOUBLES,
            partner_uid="charlie",
            proposed_time=now + timedelta(hours=1),
            court_location=None,
            venue_ref=None,
            source_broadcast_id=None,  # no broadcast
            message=None,
            status=OfferStatusEnum.PENDING,
            expires_at=now + timedelta(minutes=5),
            created_at=now - timedelta(minutes=1),
            match_id=None,
        )
        mock_offers_repo.get_by_id.return_value = mock_offer
        mock_users_repo.get_user_doc.side_effect = [
            {"name": "Bob", "playTab": {"state": "INCOMING_OFFER_PENDING"}},
            {"name": "Alice", "playTab": {"state": "OUTGOING_OFFER_PENDING"}},
        ]

        with pytest.raises(ValueError, match="source broadcast"):
            play_service.accept_offer("bob", "offer_doubles")

    def test_accept_doubles_offer_rejects_find_fourth_broadcast(
        self,
        play_service,
        mock_offers_repo,
        mock_users_repo,
        mock_broadcasts_repo,
    ):
        """find_fourth doubles acceptance is deferred to a follow-up."""
        now = datetime.now(timezone.utc)

        mock_offer = Offer(
            offer_id="offer_doubles",
            from_uid="alice",
            from_name="Alice",
            from_ranking=None,
            to_uid="bob",
            to_name="Bob",
            to_ranking=None,
            sport=SportEnum.PADEL,
            match_type=MatchTypeEnum.DOUBLES,
            partner_uid="charlie",
            proposed_time=now + timedelta(hours=1),
            court_location=None,
            venue_ref=None,
            source_broadcast_id="broadcast_doubles",
            message=None,
            status=OfferStatusEnum.PENDING,
            expires_at=now + timedelta(minutes=5),
            created_at=now - timedelta(minutes=1),
            match_id=None,
        )
        mock_offers_repo.get_by_id.return_value = mock_offer
        mock_broadcasts_repo.get_by_id.return_value = _doubles_broadcast(
            broadcast_type=BroadcastTypeEnum.FIND_FOURTH,
            partner_uid=None,
        )
        mock_users_repo.get_user_doc.side_effect = [
            {"name": "Bob", "playTab": {"state": "BROADCAST_ACTIVE"}},
            {"name": "Alice", "playTab": {"state": "OUTGOING_OFFER_PENDING"}},
        ]

        with pytest.raises(ValueError, match="find_fourth"):
            play_service.accept_offer("bob", "offer_doubles")


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
