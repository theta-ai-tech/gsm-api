"""Unit tests for NotificationIntentRepo."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.models.enums import PlayNotificationIntentTypeEnum
from app.models.notification import PlayNotificationIntent
from app.repos.notification_intent_repo import NotificationIntentRepo

_NOW = datetime(2026, 5, 30, 14, 0, 0, tzinfo=timezone.utc)


def _make_repo() -> tuple[NotificationIntentRepo, MagicMock]:
    mock_client = MagicMock(spec=firestore.Client)
    return NotificationIntentRepo(mock_client), mock_client


def _mock_subcollection_chain(client: MagicMock, doc_id: str = "intent_auto_id"):
    """Wire up the nested collection().document().collection().add() chain."""
    mock_doc_ref = MagicMock()
    mock_doc_ref.id = doc_id
    (
        client.collection.return_value.document.return_value.collection.return_value.add.return_value
    ) = (None, mock_doc_ref)
    return mock_doc_ref


class TestAddIntent:
    def test_calls_correct_subcollection_path(self):
        repo, client = _make_repo()
        _mock_subcollection_chain(client)
        intent = PlayNotificationIntent(
            type=PlayNotificationIntentTypeEnum.INCOMING_OFFER,
            target_uid="user_abc",
            title="New offer",
            body="Play?",
            offer_id="offer_123",
            dedupe_key="incoming_offer:offer_123",
            created_at=_NOW,
        )

        repo.add_intent(intent)

        client.collection.assert_called_once_with("users")
        client.collection.return_value.document.assert_called_once_with("user_abc")
        (
            client.collection.return_value.document.return_value.collection.assert_called_once_with(
                "notificationIntents"
            )
        )

    def test_returns_generated_doc_id(self):
        repo, client = _make_repo()
        _mock_subcollection_chain(client, doc_id="intent_xyz")
        intent = PlayNotificationIntent(
            type=PlayNotificationIntentTypeEnum.INCOMING_OFFER,
            target_uid="user_abc",
            title="New offer",
            body="Play?",
            offer_id="offer_123",
            dedupe_key="incoming_offer:offer_123",
            created_at=_NOW,
        )

        result = repo.add_intent(intent)

        assert result == "intent_xyz"

    def test_camelcase_core_fields_in_doc_data(self):
        repo, client = _make_repo()
        _mock_subcollection_chain(client)
        intent = PlayNotificationIntent(
            type=PlayNotificationIntentTypeEnum.INCOMING_OFFER,
            target_uid="user_abc",
            title="New offer",
            body="Play?",
            offer_id="offer_123",
            dedupe_key="incoming_offer:offer_123",
            created_at=_NOW,
        )

        repo.add_intent(intent)

        add_call = client.collection.return_value.document.return_value.collection.return_value.add
        doc_data = add_call.call_args[0][0]

        assert doc_data["type"] == "incoming_offer"
        assert doc_data["targetUid"] == "user_abc"
        assert doc_data["title"] == "New offer"
        assert doc_data["body"] == "Play?"
        assert doc_data["dedupeKey"] == "incoming_offer:offer_123"
        assert doc_data["createdAt"] == _NOW

    def test_offer_id_included_when_set(self):
        repo, client = _make_repo()
        _mock_subcollection_chain(client)
        intent = PlayNotificationIntent(
            type=PlayNotificationIntentTypeEnum.INCOMING_OFFER,
            target_uid="user_abc",
            title="Offer",
            body="Play?",
            offer_id="offer_123",
            dedupe_key="incoming_offer:offer_123",
            created_at=_NOW,
        )

        repo.add_intent(intent)

        add_call = client.collection.return_value.document.return_value.collection.return_value.add
        doc_data = add_call.call_args[0][0]
        assert doc_data["offerId"] == "offer_123"
        assert "matchId" not in doc_data

    def test_match_id_included_when_set(self):
        repo, client = _make_repo()
        _mock_subcollection_chain(client)
        intent = PlayNotificationIntent(
            type=PlayNotificationIntentTypeEnum.MATCH_SCHEDULED,
            target_uid="user_abc",
            title="Match confirmed",
            body="Play!",
            match_id="match_xyz",
            dedupe_key="match_scheduled:match_xyz:user_abc",
            created_at=_NOW,
        )

        repo.add_intent(intent)

        add_call = client.collection.return_value.document.return_value.collection.return_value.add
        doc_data = add_call.call_args[0][0]
        assert doc_data["matchId"] == "match_xyz"
        assert "offerId" not in doc_data

    def test_broadcast_id_included_when_set(self):
        repo, client = _make_repo()
        _mock_subcollection_chain(client)
        intent = PlayNotificationIntent(
            type=PlayNotificationIntentTypeEnum.INCOMING_OFFER,
            target_uid="user_abc",
            title="Offer",
            body="Play?",
            offer_id="offer_123",
            broadcast_id="bc_001",
            dedupe_key="incoming_offer:offer_123",
            created_at=_NOW,
        )

        repo.add_intent(intent)

        add_call = client.collection.return_value.document.return_value.collection.return_value.add
        doc_data = add_call.call_args[0][0]
        assert doc_data["broadcastId"] == "bc_001"

    def test_broadcast_id_omitted_when_none(self):
        repo, client = _make_repo()
        _mock_subcollection_chain(client)
        intent = PlayNotificationIntent(
            type=PlayNotificationIntentTypeEnum.INCOMING_OFFER,
            target_uid="user_abc",
            title="Offer",
            body="Play?",
            offer_id="offer_123",
            dedupe_key="incoming_offer:offer_123",
            created_at=_NOW,
        )

        repo.add_intent(intent)

        add_call = client.collection.return_value.document.return_value.collection.return_value.add
        doc_data = add_call.call_args[0][0]
        assert "broadcastId" not in doc_data
