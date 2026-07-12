"""Unit tests for GET /venues/search.

Repos and PlacesService are mocked -- no emulator or Google API needed.
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies.repos import get_venue_repo, get_venue_suggestions_repo
from app.deps import get_current_user
from app.main import app
from app.models.common import GeoCoordinates, VenueRef
from app.models.enums import SportEnum, VenueStatusEnum
from app.models.venue import VenueSummary
from app.security import CurrentUser
from app.services.places_service import PlacesService, PlacesUpstreamError

_UID = "user_test"


@pytest.fixture()
def _override_auth():
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        uid=_UID, email="test@gsm.local"
    )
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture()
def mock_venue_repo():
    repo = Mock()
    repo.search_by_name_prefix.return_value = []
    app.dependency_overrides[get_venue_repo] = lambda: repo
    yield repo
    app.dependency_overrides.pop(get_venue_repo, None)


@pytest.fixture()
def mock_places_service():
    svc = Mock(spec=PlacesService)
    svc.autocomplete.return_value = []
    with patch("app.routers.venues.get_places_service", return_value=svc):
        yield svc


@pytest.fixture()
def client(_override_auth, mock_venue_repo, mock_places_service):
    return TestClient(app)


# ---- Helpers ----


def _google_ref(
    place_id: str, name: str, lat: float = 37.9, lng: float = 23.7
) -> VenueRef:
    return VenueRef(
        place_id=place_id, name=name, coordinates=GeoCoordinates(lat=lat, lng=lng)
    )


def _curated_venue(
    venue_id: str,
    name: str,
    place_id: str | None = None,
    lat: float = 37.9,
    lng: float = 23.7,
    status: VenueStatusEnum = VenueStatusEnum.LIVE,
) -> VenueSummary:
    return VenueSummary(
        venue_id=venue_id,
        name=name,
        coordinates=GeoCoordinates(lat=lat, lng=lng),
        area="athens",
        sports=[SportEnum.PADEL],
        place_id=place_id,
        status=status,
    )


# ---- Tests ----


class TestSearchVenuesHappyPath:
    def test_google_only_results(self, client: TestClient, mock_places_service: Mock):
        mock_places_service.autocomplete.return_value = [
            _google_ref("ChIJ_abc", "Flisvos Padel"),
            _google_ref("ChIJ_def", "Athens Tennis Club"),
        ]
        resp = client.get("/venues/search", params={"q": "padel"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["results"]) == 2
        assert body["results"][0]["placeId"] == "ChIJ_abc"
        assert body["results"][0]["venueId"] is None

    def test_curated_only_results(self, client: TestClient, mock_venue_repo: Mock):
        mock_venue_repo.search_by_name_prefix.return_value = [
            _curated_venue("ven_001", "Athens Padel Club", place_id="ChIJ_xyz"),
        ]
        resp = client.get("/venues/search", params={"q": "Athens"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["results"]) == 1
        assert body["results"][0]["venueId"] == "ven_001"
        assert body["results"][0]["placeId"] == "ChIJ_xyz"

    def test_merged_results_deduplicates_by_place_id(
        self,
        client: TestClient,
        mock_venue_repo: Mock,
        mock_places_service: Mock,
    ):
        mock_venue_repo.search_by_name_prefix.return_value = [
            _curated_venue("ven_001", "Athens Padel Club", place_id="ChIJ_shared"),
        ]
        mock_places_service.autocomplete.return_value = [
            _google_ref("ChIJ_shared", "Athens Padel Club"),
            _google_ref("ChIJ_new", "Some Other Venue"),
        ]
        resp = client.get("/venues/search", params={"q": "Athens"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["results"]) == 2
        # Curated venue comes first
        assert body["results"][0]["venueId"] == "ven_001"
        # Google-only venue second
        assert body["results"][1]["placeId"] == "ChIJ_new"
        assert body["results"][1]["venueId"] is None

    def test_max_five_results(
        self,
        client: TestClient,
        mock_places_service: Mock,
    ):
        mock_places_service.autocomplete.return_value = [
            _google_ref(f"ChIJ_{i}", f"Venue {i}") for i in range(10)
        ]
        resp = client.get("/venues/search", params={"q": "venue"})
        assert resp.status_code == 200
        assert len(resp.json()["results"]) == 5

    def test_lat_lng_forwarded_to_places(
        self,
        client: TestClient,
        mock_places_service: Mock,
    ):
        client.get(
            "/venues/search",
            params={"q": "padel", "lat": 37.93, "lng": 23.68},
        )
        mock_places_service.autocomplete.assert_called_once_with(
            query="padel", lat=37.93, lng=23.68
        )

    def test_response_shape(self, client: TestClient, mock_places_service: Mock):
        mock_places_service.autocomplete.return_value = [
            _google_ref("ChIJ_abc", "Flisvos Padel", lat=37.93, lng=23.68),
        ]
        resp = client.get("/venues/search", params={"q": "flisvos"})
        assert resp.status_code == 200
        r = resp.json()["results"][0]
        assert set(r.keys()) == {"placeId", "venueId", "name", "coordinates", "status"}
        assert r["coordinates"] == {"lat": 37.93, "lng": 23.68}

    def test_google_only_result_status_is_null(
        self, client: TestClient, mock_places_service: Mock
    ):
        mock_places_service.autocomplete.return_value = [
            _google_ref("ChIJ_abc", "Flisvos Padel"),
        ]
        resp = client.get("/venues/search", params={"q": "flisvos"})
        assert resp.status_code == 200
        assert resp.json()["results"][0]["status"] is None

    def test_curated_unverified_result_carries_status(
        self, client: TestClient, mock_venue_repo: Mock
    ):
        mock_venue_repo.search_by_name_prefix.return_value = [
            _curated_venue(
                "ven_generic",
                "Generic Court",
                status=VenueStatusEnum.UNVERIFIED,
            ),
        ]
        resp = client.get("/venues/search", params={"q": "Generic"})
        assert resp.status_code == 200
        assert resp.json()["results"][0]["status"] == "unverified"


class TestSearchVenuesValidation:
    def test_missing_query_returns_422(self, client: TestClient):
        resp = client.get("/venues/search")
        assert resp.status_code == 422

    def test_empty_query_returns_422(self, client: TestClient):
        resp = client.get("/venues/search", params={"q": ""})
        assert resp.status_code == 422

    def test_invalid_lat_returns_422(self, client: TestClient):
        resp = client.get("/venues/search", params={"q": "padel", "lat": 100})
        assert resp.status_code == 422

    def test_invalid_lng_returns_422(self, client: TestClient):
        resp = client.get(
            "/venues/search", params={"q": "padel", "lat": 37.9, "lng": 200}
        )
        assert resp.status_code == 422


class TestSearchVenuesApiKeyOrdering:
    """Verify that param validation (422) fires before the API key check (503)."""

    def test_valid_params_missing_key_returns_503(
        self, _override_auth, mock_venue_repo
    ):
        """Valid query params but no GOOGLE_PLACES_API_KEY => 503."""
        with patch("app.routers.venues.get_settings") as mock_settings:
            mock_settings.return_value.google_places_api_key = None
            c = TestClient(app, raise_server_exceptions=False)
            resp = c.get("/venues/search", params={"q": "padel"})
            assert resp.status_code == 503

    def test_invalid_params_missing_key_returns_422(
        self, _override_auth, mock_venue_repo
    ):
        """Invalid query params + no API key => 422 (not 503)."""
        with patch("app.routers.venues.get_settings") as mock_settings:
            mock_settings.return_value.google_places_api_key = None
            c = TestClient(app, raise_server_exceptions=False)
            resp = c.get("/venues/search", params={"q": "padel", "lat": 100})
            assert resp.status_code == 422


class TestSearchVenuesUpstreamError:
    def test_upstream_error_returns_502(
        self, _override_auth, mock_venue_repo, mock_places_service
    ):
        mock_places_service.autocomplete.side_effect = PlacesUpstreamError(
            "Google Places API error: REQUEST_DENIED"
        )
        c = TestClient(app, raise_server_exceptions=False)
        resp = c.get("/venues/search", params={"q": "padel"})
        assert resp.status_code == 502
        assert "REQUEST_DENIED" in resp.json()["detail"]


class TestSearchVenuesAuth:
    def test_no_auth_returns_401(self):
        app.dependency_overrides.pop(get_current_user, None)
        c = TestClient(app, raise_server_exceptions=False)
        resp = c.get("/venues/search", params={"q": "padel"})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /venues/suggest
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_suggestions_repo():
    repo = Mock()
    repo.create.return_value = "suggestion_abc123"
    app.dependency_overrides[get_venue_suggestions_repo] = lambda: repo
    yield repo
    app.dependency_overrides.pop(get_venue_suggestions_repo, None)


@pytest.fixture()
def suggest_client(_override_auth, mock_suggestions_repo):
    return TestClient(app)


def _valid_suggestion_payload() -> dict:
    return {
        "name": "My Local Club",
        "coordinates": {"lat": 37.95, "lng": 23.72},
        "sport": "padel",
        "notes": "2 outdoor courts, open until 11pm",
    }


class TestSuggestVenueHappyPath:
    def test_returns_201_with_suggestion_id(
        self, suggest_client: TestClient, mock_suggestions_repo: Mock
    ):
        resp = suggest_client.post("/venues/suggest", json=_valid_suggestion_payload())
        assert resp.status_code == 201
        body = resp.json()
        assert body == {"suggestionId": "suggestion_abc123"}

    def test_authenticated_uid_passed_to_repo(
        self, suggest_client: TestClient, mock_suggestions_repo: Mock
    ):
        suggest_client.post("/venues/suggest", json=_valid_suggestion_payload())
        mock_suggestions_repo.create.assert_called_once()
        kwargs = mock_suggestions_repo.create.call_args.kwargs
        assert kwargs["uid"] == _UID
        request_arg = kwargs["request"]
        assert request_arg.name == "My Local Club"
        assert request_arg.coordinates.lat == 37.95
        assert request_arg.coordinates.lng == 23.72
        assert request_arg.sport.value == "padel"
        assert request_arg.notes == "2 outdoor courts, open until 11pm"

    def test_notes_optional(
        self, suggest_client: TestClient, mock_suggestions_repo: Mock
    ):
        payload = _valid_suggestion_payload()
        payload.pop("notes")
        resp = suggest_client.post("/venues/suggest", json=payload)
        assert resp.status_code == 201
        request_arg = mock_suggestions_repo.create.call_args.kwargs["request"]
        assert request_arg.notes is None

    def test_name_is_trimmed_before_persistence(
        self, suggest_client: TestClient, mock_suggestions_repo: Mock
    ):
        payload = _valid_suggestion_payload()
        payload["name"] = "  My Local Club  "
        resp = suggest_client.post("/venues/suggest", json=payload)
        assert resp.status_code == 201
        request_arg = mock_suggestions_repo.create.call_args.kwargs["request"]
        assert request_arg.name == "My Local Club"


class TestSuggestVenueValidation:
    def test_missing_name_returns_422(self, suggest_client: TestClient):
        payload = _valid_suggestion_payload()
        payload.pop("name")
        resp = suggest_client.post("/venues/suggest", json=payload)
        assert resp.status_code == 422

    def test_empty_name_returns_422(self, suggest_client: TestClient):
        payload = _valid_suggestion_payload()
        payload["name"] = ""
        resp = suggest_client.post("/venues/suggest", json=payload)
        assert resp.status_code == 422

    def test_whitespace_only_name_returns_422(self, suggest_client: TestClient):
        payload = _valid_suggestion_payload()
        payload["name"] = "   "
        resp = suggest_client.post("/venues/suggest", json=payload)
        assert resp.status_code == 422

    def test_name_too_long_returns_422(self, suggest_client: TestClient):
        payload = _valid_suggestion_payload()
        payload["name"] = "x" * 201
        resp = suggest_client.post("/venues/suggest", json=payload)
        assert resp.status_code == 422

    def test_invalid_sport_returns_422(self, suggest_client: TestClient):
        payload = _valid_suggestion_payload()
        payload["sport"] = "chess"
        resp = suggest_client.post("/venues/suggest", json=payload)
        assert resp.status_code == 422

    def test_invalid_lat_returns_422(self, suggest_client: TestClient):
        payload = _valid_suggestion_payload()
        payload["coordinates"]["lat"] = 100
        resp = suggest_client.post("/venues/suggest", json=payload)
        assert resp.status_code == 422

    def test_invalid_lng_returns_422(self, suggest_client: TestClient):
        payload = _valid_suggestion_payload()
        payload["coordinates"]["lng"] = 200
        resp = suggest_client.post("/venues/suggest", json=payload)
        assert resp.status_code == 422

    def test_missing_coordinates_returns_422(self, suggest_client: TestClient):
        payload = _valid_suggestion_payload()
        payload.pop("coordinates")
        resp = suggest_client.post("/venues/suggest", json=payload)
        assert resp.status_code == 422

    def test_notes_too_long_returns_422(self, suggest_client: TestClient):
        payload = _valid_suggestion_payload()
        payload["notes"] = "x" * 501
        resp = suggest_client.post("/venues/suggest", json=payload)
        assert resp.status_code == 422


class TestSuggestVenueAuth:
    def test_no_auth_returns_401(self):
        app.dependency_overrides.pop(get_current_user, None)
        c = TestClient(app, raise_server_exceptions=False)
        resp = c.post("/venues/suggest", json=_valid_suggestion_payload())
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /venues
# ---------------------------------------------------------------------------


@pytest.fixture()
def list_client(_override_auth, mock_venue_repo):
    mock_venue_repo.list_by_sport_and_area.return_value = []
    return TestClient(app)


class TestListVenues:
    def test_returns_200_empty_list_when_no_venues(self, list_client: TestClient):
        resp = list_client.get("/venues", params={"sport": "padel"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["venues"] == []
        assert body["nextCursor"] is None

    def test_sport_required_passed_to_repo(
        self, list_client: TestClient, mock_venue_repo: Mock
    ):
        list_client.get("/venues", params={"sport": "padel"})
        mock_venue_repo.list_by_sport_and_area.assert_called_once()
        call_kwargs = mock_venue_repo.list_by_sport_and_area.call_args
        assert call_kwargs.args[0] == "padel"

    def test_area_forwarded_to_repo(
        self, list_client: TestClient, mock_venue_repo: Mock
    ):
        list_client.get("/venues", params={"sport": "padel", "area": "athens"})
        mock_venue_repo.list_by_sport_and_area.assert_called_once()
        call_kwargs = mock_venue_repo.list_by_sport_and_area.call_args
        assert call_kwargs.kwargs.get("area") == "athens"

    def test_area_is_optional(self, list_client: TestClient):
        resp = list_client.get("/venues", params={"sport": "padel"})
        assert resp.status_code == 200

    def test_response_shape(self, list_client: TestClient, mock_venue_repo: Mock):
        mock_venue_repo.list_by_sport_and_area.return_value = [
            _curated_venue("ven_001", "Athens Padel Club")
        ]
        resp = list_client.get("/venues", params={"sport": "padel", "limit": "1"})
        assert resp.status_code == 200
        body = resp.json()
        assert "venues" in body
        assert "nextCursor" in body
        assert len(body["venues"]) == 1

    def test_venues_serialized_as_camelcase(
        self, list_client: TestClient, mock_venue_repo: Mock
    ):
        mock_venue_repo.list_by_sport_and_area.return_value = [
            _curated_venue("ven_001", "Athens Padel Club")
        ]
        resp = list_client.get("/venues", params={"sport": "padel", "limit": "1"})
        assert resp.status_code == 200
        venue = resp.json()["venues"][0]
        assert "venueId" in venue
        assert "courtCount" in venue
        assert "status" in venue

    def test_unverified_venue_carries_status_value(
        self, list_client: TestClient, mock_venue_repo: Mock
    ):
        mock_venue_repo.list_by_sport_and_area.return_value = [
            _curated_venue(
                "ven_generic",
                "Generic Court",
                status=VenueStatusEnum.UNVERIFIED,
            )
        ]
        resp = list_client.get("/venues", params={"sport": "padel", "limit": "1"})
        assert resp.status_code == 200
        assert resp.json()["venues"][0]["status"] == "unverified"

    def test_next_cursor_none_when_fewer_than_limit(
        self, list_client: TestClient, mock_venue_repo: Mock
    ):
        mock_venue_repo.list_by_sport_and_area.return_value = [
            _curated_venue("ven_001", "Athens Padel Club"),
            _curated_venue("ven_002", "Glyfada Tennis Club"),
        ]
        resp = list_client.get("/venues", params={"sport": "padel"})
        assert resp.status_code == 200
        assert resp.json()["nextCursor"] is None

    def test_next_cursor_set_when_results_equal_limit(
        self, list_client: TestClient, mock_venue_repo: Mock
    ):
        mock_venue_repo.list_by_sport_and_area.return_value = [
            _curated_venue("ven_001", "Athens Padel Club"),
            _curated_venue("ven_002", "Glyfada Tennis Club"),
            _curated_venue("ven_003", "Piraeus Padel"),
        ]
        resp = list_client.get("/venues", params={"sport": "padel", "limit": "3"})
        assert resp.status_code == 200
        assert resp.json()["nextCursor"] is not None

    def test_missing_sport_returns_422(self, list_client: TestClient):
        resp = list_client.get("/venues")
        assert resp.status_code == 422

    def test_invalid_sport_returns_422(self, list_client: TestClient):
        resp = list_client.get("/venues", params={"sport": "chess"})
        assert resp.status_code == 422

    def test_no_auth_returns_401(self):
        app.dependency_overrides.pop(get_current_user, None)
        c = TestClient(app, raise_server_exceptions=False)
        resp = c.get("/venues", params={"sport": "padel"})
        assert resp.status_code == 401

    def test_invalid_cursor_returns_400(
        self, list_client: TestClient, mock_venue_repo: Mock
    ):
        mock_venue_repo.list_by_sport_and_area.return_value = []
        resp = list_client.get(
            "/venues", params={"sport": "padel", "cursor": "garbage"}
        )
        assert resp.status_code == 400
