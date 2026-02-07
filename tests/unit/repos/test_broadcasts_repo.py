from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, MagicMock

import pytest

from app.models.enums import BroadcastStatusEnum, SportEnum, AvailabilityEnum, CourtStatusEnum
from app.repos.broadcasts_repo import BroadcastsRepo


@pytest.fixture
def mock_firestore_client():
    return Mock()


@pytest.fixture
def broadcasts_repo(mock_firestore_client):
    return BroadcastsRepo(mock_firestore_client)


@pytest.fixture
def sample_broadcast_data():
    now = datetime.now(timezone.utc)
    return {
        "ownerUid": "user123",
        "ownerName": "Alice",
        "ownerRanking": {"sport": "tennis", "pts": 1200, "globalRanking": 42},
        "sport": "tennis",
        "availability": "today",
        "courtStatus": "have_court",
        "courtLocation": "Central Park Court 3",
        "status": "active",
        "expiresAt": now + timedelta(hours=2),
        "createdAt": now,
        "location": {
            "area": 10001,
            "geo": {"lat": 40.7128, "lng": -74.0060},
            "radiusKm": 5.0
        }
    }


class TestBroadcastsRepoCreate:
    def test_create_broadcast(self, broadcasts_repo, mock_firestore_client, sample_broadcast_data):
        """Creates broadcast doc with auto-generated ID"""
        mock_doc_ref = Mock()
        mock_doc_ref.id = "broadcast123"
        mock_firestore_client.collection.return_value.document.return_value = mock_doc_ref

        broadcast_id = broadcasts_repo.create(sample_broadcast_data)

        assert broadcast_id == "broadcast123"
        mock_firestore_client.collection.assert_called_once_with("broadcasts")
        mock_firestore_client.collection.return_value.document.assert_called_once()
        mock_doc_ref.set.assert_called_once_with(sample_broadcast_data)


class TestBroadcastsRepoGetById:
    def test_get_by_id_exists(self, broadcasts_repo, mock_firestore_client, sample_broadcast_data):
        """Returns Broadcast Pydantic model with correct field mapping"""
        mock_doc = Mock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = sample_broadcast_data
        mock_firestore_client.collection.return_value.document.return_value.get.return_value = mock_doc

        broadcast = broadcasts_repo.get_by_id("broadcast123")

        assert broadcast is not None
        assert broadcast.broadcast_id == "broadcast123"
        assert broadcast.owner_uid == "user123"
        assert broadcast.owner_name == "Alice"
        assert broadcast.sport == SportEnum.TENNIS
        assert broadcast.availability == AvailabilityEnum.TODAY
        assert broadcast.court_status == CourtStatusEnum.HAVE_COURT
        assert broadcast.status == BroadcastStatusEnum.ACTIVE
        assert broadcast.location.area == 10001
        assert broadcast.location.geo.lat == 40.7128
        assert broadcast.location.geo.lng == -74.0060
        assert broadcast.location.radius_km == 5.0
        assert broadcast.owner_ranking.sport == SportEnum.TENNIS
        assert broadcast.owner_ranking.pts == 1200

    def test_get_by_id_not_found(self, broadcasts_repo, mock_firestore_client):
        """Returns None for non-existent ID"""
        mock_doc = Mock()
        mock_doc.exists = False
        mock_firestore_client.collection.return_value.document.return_value.get.return_value = mock_doc

        broadcast = broadcasts_repo.get_by_id("nonexistent")

        assert broadcast is None


class TestBroadcastsRepoGetActiveByOwner:
    def test_get_active_by_owner_exists(self, broadcasts_repo, mock_firestore_client, sample_broadcast_data):
        """Returns user's active broadcast"""
        mock_doc = Mock()
        mock_doc.id = "broadcast123"
        mock_doc.to_dict.return_value = sample_broadcast_data

        mock_query = Mock()
        mock_query.where.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.stream.return_value = [mock_doc]

        mock_firestore_client.collection.return_value = mock_query

        broadcast = broadcasts_repo.get_active_by_owner("user123")

        assert broadcast is not None
        assert broadcast.broadcast_id == "broadcast123"
        assert broadcast.owner_uid == "user123"
        assert broadcast.status == BroadcastStatusEnum.ACTIVE

    def test_get_active_by_owner_multiple_broadcasts(self, broadcasts_repo, mock_firestore_client, sample_broadcast_data):
        """Returns only the active one when user has multiple broadcasts"""
        mock_doc = Mock()
        mock_doc.id = "active_broadcast"
        mock_doc.to_dict.return_value = sample_broadcast_data

        mock_query = Mock()
        mock_query.where.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.stream.return_value = [mock_doc]  # limit(1) ensures only one returned

        mock_firestore_client.collection.return_value = mock_query

        broadcast = broadcasts_repo.get_active_by_owner("user123")

        assert broadcast is not None
        assert broadcast.broadcast_id == "active_broadcast"

    def test_get_active_by_owner_none(self, broadcasts_repo, mock_firestore_client):
        """Returns None when user has no active broadcast"""
        mock_query = Mock()
        mock_query.where.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.stream.return_value = []

        mock_firestore_client.collection.return_value = mock_query

        broadcast = broadcasts_repo.get_active_by_owner("user123")

        assert broadcast is None


class TestBroadcastsRepoUpdateStatus:
    def test_update_status(self, broadcasts_repo, mock_firestore_client):
        """Updates status field"""
        mock_doc_ref = Mock()
        mock_firestore_client.collection.return_value.document.return_value = mock_doc_ref

        broadcasts_repo.update_status("broadcast123", BroadcastStatusEnum.EXPIRED)

        mock_firestore_client.collection.assert_called_once_with("broadcasts")
        mock_firestore_client.collection.return_value.document.assert_called_once_with("broadcast123")
        mock_doc_ref.update.assert_called_once_with({"status": "expired"})

    def test_update_status_idempotent(self, broadcasts_repo, mock_firestore_client):
        """Multiple updates to same status don't fail"""
        mock_doc_ref = Mock()
        mock_firestore_client.collection.return_value.document.return_value = mock_doc_ref

        broadcasts_repo.update_status("broadcast123", BroadcastStatusEnum.EXPIRED)
        broadcasts_repo.update_status("broadcast123", BroadcastStatusEnum.EXPIRED)

        assert mock_doc_ref.update.call_count == 2


class TestBroadcastsRepoDelete:
    def test_delete_broadcast(self, broadcasts_repo, mock_firestore_client):
        """Deletes doc"""
        mock_doc_ref = Mock()
        mock_firestore_client.collection.return_value.document.return_value = mock_doc_ref

        broadcasts_repo.delete("broadcast123")

        mock_firestore_client.collection.assert_called_once_with("broadcasts")
        mock_firestore_client.collection.return_value.document.assert_called_once_with("broadcast123")
        mock_doc_ref.delete.assert_called_once()
