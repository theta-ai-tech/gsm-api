from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.enums import (
    BroadcastStatusEnum,
    OfferStatusEnum,
    PlayTabStateEnum,
    SportEnum,
    AvailabilityEnum,
    CourtStatusEnum,
)
from app.models.play import (
    CreateBroadcastResponse,
    MeStateResponse,
    MeStatePrimary,
    OfferActionResponse,
    SendOfferResponse,
)
from app.routers.play import get_play_service
from app.deps import get_current_user
from app.security import CurrentUser
from app.services.play_service import PlayService


@pytest.fixture
def mock_play_service():
    return Mock(spec=PlayService)


@pytest.fixture
def mock_current_user():
    return CurrentUser(uid="test_user", email="test@example.com")


@pytest.fixture
def client(mock_play_service, mock_current_user):
    """TestClient with mocked dependencies"""
    previous_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_play_service] = lambda: mock_play_service
    app.dependency_overrides[get_current_user] = lambda: mock_current_user
    yield TestClient(app)
    app.dependency_overrides = previous_overrides


class TestGetMeState:
    def test_get_me_state_success(self, client, mock_play_service):
        """Calls play_service.get_me_state and returns 200"""
        now = datetime.now(timezone.utc)
        mock_response = MeStateResponse(
            mode=PlayTabStateEnum.DISCOVERY,
            server_time=now,
            primary=MeStatePrimary(),
            payload={},
            ui_events=[],
        )
        mock_play_service.get_me_state.return_value = mock_response

        response = client.get("/me/state")

        assert response.status_code == 200
        data = response.json()
        assert data["mode"] == "DISCOVERY"
        mock_play_service.get_me_state.assert_called_once_with("test_user")


class TestCreateBroadcast:
    def test_create_broadcast_success(self, client, mock_play_service):
        """Valid request returns 201 with CreateBroadcastResponse"""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=2)

        mock_response = CreateBroadcastResponse(
            broadcast_id="broadcast123",
            sport=SportEnum.TENNIS,
            availability=AvailabilityEnum.TODAY,
            court_status=CourtStatusEnum.HAVE_COURT,
            court_location="Central Park",
            status=BroadcastStatusEnum.ACTIVE,
            expires_at=expires_at,
            created_at=now,
        )
        mock_play_service.create_broadcast.return_value = mock_response

        payload = {
            "sport": "tennis",
            "availability": "today",
            "court_status": "have_court",
            "court_location": "Central Park",
            "expires_at": expires_at.isoformat(),
            "location": {"area": 10001},
        }

        response = client.post("/me/broadcast", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert data["broadcast_id"] == "broadcast123"
        assert data["sport"] == "tennis"

    def test_create_broadcast_invalid_state(self, client, mock_play_service):
        """Service raises ValueError - returns 409"""
        now = datetime.now(timezone.utc)
        mock_play_service.create_broadcast.side_effect = ValueError(
            "Cannot create broadcast: user is in BROADCAST_ACTIVE state"
        )

        payload = {
            "sport": "tennis",
            "availability": "today",
            "court_status": "need_court",
            "expires_at": (now + timedelta(hours=2)).isoformat(),
            "location": {"area": 10001},
        }

        response = client.post("/me/broadcast", json=payload)

        assert response.status_code == 409

    def test_create_broadcast_validation_error(self, client, mock_play_service):
        """Missing required field - returns 422"""
        payload = {
            "availability": "today",
            "court_status": "need_court",
            "location": {"area": 10001},
            # Missing sport
        }

        response = client.post("/me/broadcast", json=payload)

        assert response.status_code == 422

    def test_create_broadcast_invalid_enum(self, client, mock_play_service):
        """Invalid enum value - returns 422"""
        now = datetime.now(timezone.utc)
        payload = {
            "sport": "invalid_sport",
            "availability": "today",
            "court_status": "need_court",
            "expires_at": (now + timedelta(hours=2)).isoformat(),
            "location": {"area": 10001},
        }

        response = client.post("/me/broadcast", json=payload)

        assert response.status_code == 422


class TestCancelBroadcast:
    def test_cancel_broadcast_success(self, client, mock_play_service):
        """Returns 204 No Content"""
        mock_play_service.cancel_broadcast.return_value = None

        response = client.delete("/me/broadcast")

        assert response.status_code == 204
        mock_play_service.cancel_broadcast.assert_called_once_with("test_user")

    def test_cancel_broadcast_no_active_broadcast(self, client, mock_play_service):
        """Service raises ValueError - returns 409"""
        mock_play_service.cancel_broadcast.side_effect = ValueError(
            "No active broadcast to cancel"
        )

        response = client.delete("/me/broadcast")

        assert response.status_code == 409


class TestSendOffer:
    def test_send_offer_success(self, client, mock_play_service):
        """Valid request returns 201 with SendOfferResponse"""
        now = datetime.now(timezone.utc)
        proposed_time = now + timedelta(hours=2)
        expires_at = now + timedelta(minutes=5)

        mock_response = SendOfferResponse(
            offer_id="offer123",
            to_uid="bob",
            to_name="Bob",
            sport=SportEnum.TENNIS,
            proposed_time=proposed_time,
            status=OfferStatusEnum.PENDING,
            expires_at=expires_at,
            created_at=now,
        )
        mock_play_service.send_offer.return_value = mock_response

        payload = {
            "to_uid": "bob",
            "sport": "tennis",
            "proposed_time": proposed_time.isoformat(),
            "court_location": "Central Park",
            "message": "Let's play!",
        }

        response = client.post("/me/offers", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert data["offer_id"] == "offer123"
        assert data["to_uid"] == "bob"

    def test_send_offer_recipient_not_found(self, client, mock_play_service):
        """Service raises ValueError with 'not found' - returns 404"""
        now = datetime.now(timezone.utc)
        mock_play_service.send_offer.side_effect = ValueError("Recipient not found")

        payload = {
            "to_uid": "nonexistent",
            "sport": "tennis",
            "proposed_time": (now + timedelta(hours=2)).isoformat(),
        }

        response = client.post("/me/offers", json=payload)

        assert response.status_code == 404

    def test_send_offer_sender_invalid_state(self, client, mock_play_service):
        """Service raises ValueError - returns 409"""
        now = datetime.now(timezone.utc)
        mock_play_service.send_offer.side_effect = ValueError(
            "Cannot send offer: sender is in MATCH_SCHEDULED state"
        )

        payload = {
            "to_uid": "bob",
            "sport": "tennis",
            "proposed_time": (now + timedelta(hours=2)).isoformat(),
        }

        response = client.post("/me/offers", json=payload)

        assert response.status_code == 409

    def test_send_offer_validation_error(self, client, mock_play_service):
        """Missing toUid - returns 422"""
        now = datetime.now(timezone.utc)
        payload = {
            "sport": "tennis",
            "proposed_time": (now + timedelta(hours=2)).isoformat(),
            # Missing toUid
        }

        response = client.post("/me/offers", json=payload)

        assert response.status_code == 422


class TestAcceptOffer:
    def test_accept_offer_success(self, client, mock_play_service):
        """Returns 200 with OfferActionResponse including matchId"""
        now = datetime.now(timezone.utc)
        mock_response = OfferActionResponse(
            offer_id="offer123",
            status=OfferStatusEnum.ACCEPTED,
            match_id="match456",
            scheduled_at=now + timedelta(hours=1),
        )
        mock_play_service.accept_offer.return_value = mock_response

        response = client.post("/me/offers/offer123/accept")

        assert response.status_code == 200
        data = response.json()
        assert data["offer_id"] == "offer123"
        assert data["status"] == "accepted"
        assert data["match_id"] == "match456"
        mock_play_service.accept_offer.assert_called_once_with("test_user", "offer123")

    def test_accept_offer_not_found(self, client, mock_play_service):
        """Service raises ValueError with 'not found' - returns 404"""
        mock_play_service.accept_offer.side_effect = ValueError("Offer not found")

        response = client.post("/me/offers/nonexistent/accept")

        assert response.status_code == 404

    def test_accept_offer_not_recipient(self, client, mock_play_service):
        """Service raises ValueError with 'not the recipient' - returns 403"""
        mock_play_service.accept_offer.side_effect = ValueError(
            "You are not the recipient of this offer"
        )

        response = client.post("/me/offers/offer123/accept")

        assert response.status_code == 403

    def test_accept_offer_expired(self, client, mock_play_service):
        """Service raises ValueError with 'expired' - returns 410"""
        mock_play_service.accept_offer.side_effect = ValueError("Offer has expired")

        response = client.post("/me/offers/offer123/accept")

        assert response.status_code == 410

    def test_accept_offer_already_accepted(self, client, mock_play_service):
        """Service raises ValueError (status mismatch) - returns 409"""
        mock_play_service.accept_offer.side_effect = ValueError(
            "Offer is accepted, not pending"
        )

        response = client.post("/me/offers/offer123/accept")

        assert response.status_code == 409


class TestDeclineOffer:
    def test_decline_offer_success(self, client, mock_play_service):
        """Returns 200 with OfferActionResponse"""
        mock_response = OfferActionResponse(
            offer_id="offer123",
            status=OfferStatusEnum.DECLINED,
            match_id=None,
            scheduled_at=None,
        )
        mock_play_service.decline_offer.return_value = mock_response

        response = client.post("/me/offers/offer123/decline")

        assert response.status_code == 200
        data = response.json()
        assert data["offer_id"] == "offer123"
        assert data["status"] == "declined"

    def test_decline_offer_not_found(self, client, mock_play_service):
        """Service raises ValueError with 'not found' - returns 404"""
        mock_play_service.decline_offer.side_effect = ValueError("Offer not found")

        response = client.post("/me/offers/nonexistent/decline")

        assert response.status_code == 404

    def test_decline_offer_not_recipient(self, client, mock_play_service):
        """Service raises ValueError with 'not the recipient' - returns 403"""
        mock_play_service.decline_offer.side_effect = ValueError(
            "You are not the recipient of this offer"
        )

        response = client.post("/me/offers/offer123/decline")

        assert response.status_code == 403


class TestCancelOffer:
    def test_cancel_offer_success(self, client, mock_play_service):
        """Returns 200"""
        mock_response = OfferActionResponse(
            offer_id="offer123",
            status=OfferStatusEnum.CANCELLED,
            match_id=None,
            scheduled_at=None,
        )
        mock_play_service.cancel_offer.return_value = mock_response

        response = client.post("/me/offers/offer123/cancel")

        assert response.status_code == 200
        data = response.json()
        assert data["offer_id"] == "offer123"
        assert data["status"] == "cancelled"

    def test_cancel_offer_not_sender(self, client, mock_play_service):
        """Service raises ValueError with 'not the sender' - returns 403"""
        mock_play_service.cancel_offer.side_effect = ValueError(
            "You are not the sender of this offer"
        )

        response = client.post("/me/offers/offer123/cancel")

        assert response.status_code == 403
