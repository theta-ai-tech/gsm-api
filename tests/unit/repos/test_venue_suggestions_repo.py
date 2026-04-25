from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.models.common import GeoCoordinates
from app.models.enums import SportEnum
from app.models.venue_suggestion import CreateVenueSuggestionRequest
from app.repos.venue_suggestions_repo import VenueSuggestionsRepo


def _make_repo() -> tuple[VenueSuggestionsRepo, MagicMock, MagicMock]:
    mock_client = MagicMock(spec=firestore.Client)
    doc_ref = MagicMock()
    doc_ref.id = "auto_generated_id_xyz"
    mock_client.collection.return_value.document.return_value = doc_ref
    return VenueSuggestionsRepo(mock_client), mock_client, doc_ref


def _request(
    *,
    name: str = "My Local Club",
    lat: float = 37.95,
    lng: float = 23.72,
    sport: SportEnum = SportEnum.PADEL,
    notes: str | None = "2 outdoor courts, open until 11pm",
) -> CreateVenueSuggestionRequest:
    return CreateVenueSuggestionRequest(
        name=name,
        coordinates=GeoCoordinates(lat=lat, lng=lng),
        sport=sport,
        notes=notes,
    )


class TestCreate:
    def test_writes_to_venue_suggestions_collection(self) -> None:
        repo, client, doc_ref = _make_repo()

        repo.create(uid="user_abc", request=_request())

        client.collection.assert_called_once_with("venueSuggestions")
        # An auto-id document is requested via .document() with no args
        client.collection.return_value.document.assert_called_once_with()
        doc_ref.set.assert_called_once()

    def test_returns_auto_generated_id(self) -> None:
        repo, _, _ = _make_repo()

        result = repo.create(uid="user_abc", request=_request())

        assert result == "auto_generated_id_xyz"

    def test_stores_all_required_fields(self) -> None:
        repo, _, doc_ref = _make_repo()

        repo.create(uid="user_abc", request=_request())

        payload = doc_ref.set.call_args[0][0]
        assert payload["name"] == "My Local Club"
        assert payload["coordinates"] == {"lat": 37.95, "lng": 23.72}
        assert payload["sport"] == "padel"
        assert payload["notes"] == "2 outdoor courts, open until 11pm"
        assert payload["suggestedBy"] == "user_abc"
        assert payload["status"] == "pending"
        assert isinstance(payload["createdAt"], datetime)
        assert payload["createdAt"].tzinfo is not None
        # Should be UTC
        assert payload["createdAt"].utcoffset() == timezone.utc.utcoffset(
            payload["createdAt"]
        )

    def test_notes_optional_stored_as_none(self) -> None:
        repo, _, doc_ref = _make_repo()

        repo.create(uid="user_abc", request=_request(notes=None))

        payload = doc_ref.set.call_args[0][0]
        assert payload["notes"] is None

    def test_sport_enum_serialized_to_string(self) -> None:
        repo, _, doc_ref = _make_repo()

        repo.create(uid="user_abc", request=_request(sport=SportEnum.TENNIS))

        payload = doc_ref.set.call_args[0][0]
        assert payload["sport"] == "tennis"
