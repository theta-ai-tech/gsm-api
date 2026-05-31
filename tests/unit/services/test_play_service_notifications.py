"""Unit tests for notification intent emission in PlayService."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from app.models.enums import (
    OfferStatusEnum,
    PlayNotificationIntentTypeEnum,
    SportEnum,
)
from app.models.play import Offer, SendOfferRequest
from app.repos.broadcasts_repo import BroadcastsRepo
from app.repos.matches_repo import MatchesRepo
from app.repos.notification_intent_repo import NotificationIntentRepo
from app.repos.offers_repo import OffersRepo
from app.repos.users_repo import UsersRepo
from app.services.play_service import PlayService


# ---------------------------------------------------------------------------
# Fixtures
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
def mock_notification_intent_repo():
    return Mock(spec=NotificationIntentRepo)


def _make_play_service(
    mock_users_repo,
    mock_broadcasts_repo,
    mock_matches_repo,
    mock_offers_repo,
    mock_firestore_client,
    notification_intent_repo=None,
) -> PlayService:
    return PlayService(
        mock_users_repo,
        mock_broadcasts_repo,
        mock_matches_repo,
        mock_offers_repo,
        mock_firestore_client,
        notification_intent_repo=notification_intent_repo,
    )


def _patch_transactional(play_service_module):
    """Return (original, mock) transactional decorator."""
    original = play_service_module.firestore.transactional
    play_service_module.firestore.transactional = lambda func: func
    return original


def _restore_transactional(play_service_module, original):
    play_service_module.firestore.transactional = original


# ---------------------------------------------------------------------------
# send_offer tests
# ---------------------------------------------------------------------------


class TestSendOfferNotifications:
    def _setup_send_offer(self, mock_users_repo, mock_firestore_client):
        now = datetime.now(timezone.utc)
        mock_users_repo.get_user_doc.side_effect = [
            {"name": "Alice", "rankings": {}, "playTab": {"state": "DISCOVERY"}},
            {"name": "Bob", "rankings": {}, "playTab": {"state": "DISCOVERY"}},
        ]
        mock_doc_ref = Mock()
        mock_doc_ref.id = "offer_abc"
        mock_firestore_client.collection.return_value.document.return_value = (
            mock_doc_ref
        )
        return now

    def test_send_offer_emits_incoming_offer_intent(
        self,
        mock_users_repo,
        mock_broadcasts_repo,
        mock_matches_repo,
        mock_offers_repo,
        mock_firestore_client,
        mock_notification_intent_repo,
    ):
        import app.services.play_service as m

        now = self._setup_send_offer(mock_users_repo, mock_firestore_client)
        original = _patch_transactional(m)
        svc = _make_play_service(
            mock_users_repo,
            mock_broadcasts_repo,
            mock_matches_repo,
            mock_offers_repo,
            mock_firestore_client,
            notification_intent_repo=mock_notification_intent_repo,
        )
        try:
            request = SendOfferRequest(
                to_uid="bob",
                sport=SportEnum.TENNIS,
                proposed_time=now + timedelta(hours=2),
            )
            svc.send_offer("alice", request)
        finally:
            _restore_transactional(m, original)

        mock_notification_intent_repo.add_intent.assert_called_once()
        intent = mock_notification_intent_repo.add_intent.call_args[0][0]
        assert intent.type == PlayNotificationIntentTypeEnum.INCOMING_OFFER
        assert intent.target_uid == "bob"
        assert intent.offer_id == "offer_abc"

    def test_send_offer_without_intent_repo_does_not_raise(
        self,
        mock_users_repo,
        mock_broadcasts_repo,
        mock_matches_repo,
        mock_offers_repo,
        mock_firestore_client,
    ):
        import app.services.play_service as m

        now = self._setup_send_offer(mock_users_repo, mock_firestore_client)
        original = _patch_transactional(m)
        svc = _make_play_service(
            mock_users_repo,
            mock_broadcasts_repo,
            mock_matches_repo,
            mock_offers_repo,
            mock_firestore_client,
            notification_intent_repo=None,
        )
        try:
            request = SendOfferRequest(
                to_uid="bob",
                sport=SportEnum.TENNIS,
                proposed_time=now + timedelta(hours=2),
            )
            # Must not raise
            svc.send_offer("alice", request)
        finally:
            _restore_transactional(m, original)


# ---------------------------------------------------------------------------
# accept_offer tests
# ---------------------------------------------------------------------------


class TestAcceptOfferNotifications:
    def _make_offer(self, now: datetime) -> Offer:
        return Offer(
            offer_id="offer_xyz",
            from_uid="alice",
            from_name="Alice",
            from_ranking=None,
            to_uid="bob",
            to_name="Bob",
            to_ranking=None,
            sport=SportEnum.TENNIS,
            proposed_time=now + timedelta(hours=1),
            court_location=None,
            source_broadcast_id=None,
            message=None,
            status=OfferStatusEnum.PENDING,
            expires_at=now + timedelta(minutes=5),
            created_at=now - timedelta(minutes=1),
            match_id=None,
        )

    def test_accept_offer_singles_emits_match_scheduled_for_both_participants(
        self,
        mock_users_repo,
        mock_broadcasts_repo,
        mock_matches_repo,
        mock_offers_repo,
        mock_firestore_client,
        mock_notification_intent_repo,
    ):
        import app.services.play_service as m

        now = datetime.now(timezone.utc)
        mock_offers_repo.get_by_id.return_value = self._make_offer(now)
        mock_users_repo.get_user_doc.side_effect = [
            {
                "name": "Bob",
                "playTab": {
                    "state": "INCOMING_OFFER_PENDING",
                    "activeBroadcastId": None,
                    "pendingIncomingOfferIds": ["offer_xyz"],
                },
            },
            {
                "name": "Alice",
                "playTab": {
                    "state": "OUTGOING_OFFER_PENDING",
                    "activeOutgoingOfferId": "offer_xyz",
                },
            },
        ]
        original = _patch_transactional(m)
        svc = _make_play_service(
            mock_users_repo,
            mock_broadcasts_repo,
            mock_matches_repo,
            mock_offers_repo,
            mock_firestore_client,
            notification_intent_repo=mock_notification_intent_repo,
        )
        try:
            svc.accept_offer("bob", "offer_xyz")
        finally:
            _restore_transactional(m, original)

        assert mock_notification_intent_repo.add_intent.call_count == 2
        intents = [
            c[0][0] for c in mock_notification_intent_repo.add_intent.call_args_list
        ]
        for intent in intents:
            assert intent.type == PlayNotificationIntentTypeEnum.MATCH_SCHEDULED
        target_uids = {i.target_uid for i in intents}
        assert target_uids == {"alice", "bob"}

    def test_accept_offer_swallows_intent_repo_exception(
        self,
        mock_users_repo,
        mock_broadcasts_repo,
        mock_matches_repo,
        mock_offers_repo,
        mock_firestore_client,
        mock_notification_intent_repo,
    ):
        import app.services.play_service as m

        now = datetime.now(timezone.utc)
        mock_offers_repo.get_by_id.return_value = self._make_offer(now)
        mock_users_repo.get_user_doc.side_effect = [
            {
                "name": "Bob",
                "playTab": {
                    "state": "INCOMING_OFFER_PENDING",
                    "activeBroadcastId": None,
                    "pendingIncomingOfferIds": ["offer_xyz"],
                },
            },
            {
                "name": "Alice",
                "playTab": {
                    "state": "OUTGOING_OFFER_PENDING",
                    "activeOutgoingOfferId": "offer_xyz",
                },
            },
        ]
        mock_notification_intent_repo.add_intent.side_effect = RuntimeError(
            "Firestore down"
        )
        original = _patch_transactional(m)
        svc = _make_play_service(
            mock_users_repo,
            mock_broadcasts_repo,
            mock_matches_repo,
            mock_offers_repo,
            mock_firestore_client,
            notification_intent_repo=mock_notification_intent_repo,
        )
        try:
            # Should not raise even though add_intent raises
            response = svc.accept_offer("bob", "offer_xyz")
        finally:
            _restore_transactional(m, original)

        assert response.status == OfferStatusEnum.ACCEPTED
