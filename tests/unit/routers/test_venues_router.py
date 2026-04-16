"""Unit tests for GET /venues/search.

Repos and PlacesService are mocked -- no emulator or Google API needed.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.dependencies.repos import get_venue_repo
from app.deps import get_current_user
from app.main import app
from app.models.common import GeoCoordinates, VenueRef
from app.models.enums import SportEnum
from app.models.venue import VenueSummary
from app.routers.venues import get_places_service
from app.security import CurrentUser
from app.services.places_service import PlacesService

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
    app.dependency_overrides[get_places_service] = lambda: svc
    yield svc
    app.dependency_overrides.pop(get_places_service, None)


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
) -> VenueSummary:
    return VenueSummary(
        venue_id=venue_id,
        name=name,
        coordinates=GeoCoordinates(lat=lat, lng=lng),
        area="Athens",
        sports=[SportEnum.PADEL],
        place_id=place_id,
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
        assert set(r.keys()) == {"placeId", "venueId", "name", "coordinates"}
        assert r["coordinates"] == {"lat": 37.93, "lng": 23.68}


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


class TestSearchVenuesAuth:
    def test_no_auth_returns_401(self):
        app.dependency_overrides.pop(get_current_user, None)
        c = TestClient(app, raise_server_exceptions=False)
        resp = c.get("/venues/search", params={"q": "padel"})
        assert resp.status_code == 401
