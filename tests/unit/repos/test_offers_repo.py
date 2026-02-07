from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from app.models.enums import OfferStatusEnum, SportEnum
from app.repos.offers_repo import OffersRepo


@pytest.fixture
def mock_firestore_client():
    return Mock()


@pytest.fixture
def offers_repo(mock_firestore_client):
    return OffersRepo(mock_firestore_client)


@pytest.fixture
def sample_offer_data():
    now = datetime.now(timezone.utc)
    return {
        "fromUid": "alice",
        "fromName": "Alice",
        "fromRanking": {"sport": "tennis", "pts": 1200, "globalRanking": 42},
        "toUid": "bob",
        "toName": "Bob",
        "toRanking": {"sport": "tennis", "pts": 1100, "globalRanking": 50},
        "sport": "tennis",
        "proposedTime": now + timedelta(hours=2),
        "courtLocation": "Central Park Court 3",
        "message": "Let's play!",
        "status": "pending",
        "expiresAt": now + timedelta(minutes=5),
        "createdAt": now,
        "matchId": None
    }


class TestOffersRepoCreate:
    def test_create_offer(self, offers_repo, mock_firestore_client, sample_offer_data):
        """Creates offer doc and returns created offer ID"""
        mock_doc_ref = Mock()
        mock_doc_ref.id = "offer123"
        mock_firestore_client.collection.return_value.document.return_value = mock_doc_ref

        offer_id = offers_repo.create(sample_offer_data)

        assert offer_id == "offer123"
        mock_firestore_client.collection.assert_called_once_with("offers")
        mock_doc_ref.set.assert_called_once_with(sample_offer_data)


class TestOffersRepoGetById:
    def test_get_by_id_exists(self, offers_repo, mock_firestore_client, sample_offer_data):
        """Returns Offer Pydantic model with correct mapping"""
        mock_doc = Mock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = sample_offer_data
        mock_firestore_client.collection.return_value.document.return_value.get.return_value = mock_doc

        offer = offers_repo.get_by_id("offer123")

        assert offer is not None
        assert offer.offer_id == "offer123"
        assert offer.from_uid == "alice"
        assert offer.from_name == "Alice"
        assert offer.to_uid == "bob"
        assert offer.to_name == "Bob"
        assert offer.sport == SportEnum.TENNIS
        assert offer.status == OfferStatusEnum.PENDING
        assert offer.from_ranking.pts == 1200
        assert offer.to_ranking.pts == 1100
        assert offer.message == "Let's play!"

    def test_get_by_id_not_found(self, offers_repo, mock_firestore_client):
        """Returns None for non-existent ID"""
        mock_doc = Mock()
        mock_doc.exists = False
        mock_firestore_client.collection.return_value.document.return_value.get.return_value = mock_doc

        offer = offers_repo.get_by_id("nonexistent")

        assert offer is None


class TestOffersRepoGetByIds:
    def test_get_by_ids_batch(self, offers_repo, mock_firestore_client, sample_offer_data):
        """Returns list of Offer objects, skips non-existent IDs"""
        mock_doc1 = Mock()
        mock_doc1.exists = True
        mock_doc1.id = "offer1"
        mock_doc1.to_dict.return_value = sample_offer_data

        mock_doc2 = Mock()
        mock_doc2.exists = False
        mock_doc2.id = "offer2"

        mock_doc3 = Mock()
        mock_doc3.exists = True
        mock_doc3.id = "offer3"
        mock_doc3.to_dict.return_value = sample_offer_data

        mock_firestore_client.get_all.return_value = [mock_doc1, mock_doc2, mock_doc3]

        offers = offers_repo.get_by_ids(["offer1", "offer2", "offer3"])

        assert len(offers) == 2
        assert offers[0].offer_id == "offer1"
        assert offers[1].offer_id == "offer3"

    def test_get_by_ids_empty_list(self, offers_repo, mock_firestore_client):
        """Handles empty list input"""
        offers = offers_repo.get_by_ids([])

        assert offers == []
        mock_firestore_client.get_all.assert_not_called()

    def test_get_by_ids_all_missing(self, offers_repo, mock_firestore_client):
        """Returns empty list when all IDs don't exist"""
        mock_doc1 = Mock()
        mock_doc1.exists = False
        mock_doc2 = Mock()
        mock_doc2.exists = False

        mock_firestore_client.get_all.return_value = [mock_doc1, mock_doc2]

        offers = offers_repo.get_by_ids(["nonexistent1", "nonexistent2"])

        assert offers == []


class TestOffersRepoGetActiveOutgoing:
    def test_get_active_outgoing_exists(self, offers_repo, mock_firestore_client, sample_offer_data):
        """Returns user's pending outgoing offer"""
        mock_doc = Mock()
        mock_doc.id = "offer123"
        mock_doc.to_dict.return_value = sample_offer_data

        mock_query = Mock()
        mock_query.where.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.stream.return_value = [mock_doc]

        mock_firestore_client.collection.return_value = mock_query

        offer = offers_repo.get_active_outgoing("alice")

        assert offer is not None
        assert offer.offer_id == "offer123"
        assert offer.from_uid == "alice"
        assert offer.status == OfferStatusEnum.PENDING

    def test_get_active_outgoing_none(self, offers_repo, mock_firestore_client):
        """Returns None when user has no pending outgoing offer"""
        mock_query = Mock()
        mock_query.where.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.stream.return_value = []

        mock_firestore_client.collection.return_value = mock_query

        offer = offers_repo.get_active_outgoing("alice")

        assert offer is None


class TestOffersRepoGetPendingForUser:
    def test_get_pending_for_user(self, offers_repo, mock_firestore_client, sample_offer_data):
        """Returns all pending incoming offers for toUid"""
        mock_doc1 = Mock()
        mock_doc1.id = "offer1"
        mock_doc1.to_dict.return_value = sample_offer_data

        mock_doc2 = Mock()
        mock_doc2.id = "offer2"
        mock_doc2.to_dict.return_value = sample_offer_data

        mock_query = Mock()
        mock_query.where.return_value = mock_query
        mock_query.stream.return_value = [mock_doc1, mock_doc2]

        mock_firestore_client.collection.return_value = mock_query

        offers = offers_repo.get_pending_for_user("bob")

        assert len(offers) == 2
        assert all(o.status == OfferStatusEnum.PENDING for o in offers)

    def test_get_pending_for_user_empty(self, offers_repo, mock_firestore_client):
        """Returns empty list when no pending offers"""
        mock_query = Mock()
        mock_query.where.return_value = mock_query
        mock_query.stream.return_value = []

        mock_firestore_client.collection.return_value = mock_query

        offers = offers_repo.get_pending_for_user("bob")

        assert offers == []

    def test_get_pending_for_user_multiple(self, offers_repo, mock_firestore_client, sample_offer_data):
        """User has 3 pending offers from different senders"""
        mock_docs = []
        for i in range(3):
            mock_doc = Mock()
            mock_doc.id = f"offer{i}"
            mock_doc.to_dict.return_value = sample_offer_data
            mock_docs.append(mock_doc)

        mock_query = Mock()
        mock_query.where.return_value = mock_query
        mock_query.stream.return_value = mock_docs

        mock_firestore_client.collection.return_value = mock_query

        offers = offers_repo.get_pending_for_user("bob")

        assert len(offers) == 3


class TestOffersRepoUpdateStatus:
    def test_update_status_without_match_id(self, offers_repo, mock_firestore_client):
        """Updates status to declined without match ID"""
        mock_doc_ref = Mock()
        mock_firestore_client.collection.return_value.document.return_value = mock_doc_ref

        offers_repo.update_status("offer123", OfferStatusEnum.DECLINED)

        mock_doc_ref.update.assert_called_once_with({"status": "declined"})

    def test_update_status_with_match_id(self, offers_repo, mock_firestore_client):
        """Updates status to accepted and sets matchId"""
        mock_doc_ref = Mock()
        mock_firestore_client.collection.return_value.document.return_value = mock_doc_ref

        offers_repo.update_status("offer123", OfferStatusEnum.ACCEPTED, match_id="match456")

        mock_doc_ref.update.assert_called_once_with({"status": "accepted", "matchId": "match456"})


class TestOffersRepoBatchUpdateStatus:
    def test_batch_update_status(self, offers_repo, mock_firestore_client):
        """Updates multiple offers in single batch"""
        mock_batch = Mock()
        mock_firestore_client.batch.return_value = mock_batch

        mock_doc_refs = []
        for i in range(3):
            mock_doc_ref = Mock()
            mock_doc_refs.append(mock_doc_ref)

        call_count = 0
        def document_side_effect(offer_id):
            nonlocal call_count
            result = mock_doc_refs[call_count]
            call_count += 1
            return result

        mock_firestore_client.collection.return_value.document.side_effect = document_side_effect

        offers_repo.batch_update_status(["offer1", "offer2", "offer3"], OfferStatusEnum.DECLINED)

        assert mock_batch.update.call_count == 3
        mock_batch.commit.assert_called_once()

    def test_batch_update_status_empty_list(self, offers_repo, mock_firestore_client):
        """No-op for empty list"""
        mock_batch = Mock()
        mock_firestore_client.batch.return_value = mock_batch

        offers_repo.batch_update_status([], OfferStatusEnum.DECLINED)

        mock_batch.update.assert_not_called()
        mock_batch.commit.assert_not_called()

    def test_batch_update_status_large_batch(self, offers_repo, mock_firestore_client):
        """500 offer IDs (Firestore batch limit)"""
        mock_batch = Mock()
        mock_firestore_client.batch.return_value = mock_batch

        offer_ids = [f"offer{i}" for i in range(500)]
        mock_doc_refs = [Mock() for _ in range(500)]

        call_count = 0
        def document_side_effect(offer_id):
            nonlocal call_count
            result = mock_doc_refs[call_count]
            call_count += 1
            return result

        mock_firestore_client.collection.return_value.document.side_effect = document_side_effect

        offers_repo.batch_update_status(offer_ids, OfferStatusEnum.EXPIRED)

        assert mock_batch.update.call_count == 500
        mock_batch.commit.assert_called_once()
