from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.models import VenueSummary
from app.models.enums import SportEnum
from app.repos.venue_repo import CLIENT_VISIBLE_STATUSES, VenueRepo


def _make_repo() -> tuple[VenueRepo, MagicMock]:
    mock_client = MagicMock(spec=firestore.Client)
    return VenueRepo(mock_client), mock_client


def _geo_point(lat: float, lng: float) -> SimpleNamespace:
    """Stand-in for ``google.cloud.firestore.GeoPoint`` with the same duck-typed
    attributes (``latitude`` / ``longitude``)."""
    return SimpleNamespace(latitude=lat, longitude=lng)


def _make_venue_doc(
    doc_id: str,
    *,
    name: str,
    lat: float,
    lng: float,
    area: str,
    sports: list[str],
    court_count: int | None = None,
    indoor: bool | None = None,
    place_id: str | None = None,
    status: str | None = None,
) -> MagicMock:
    doc = MagicMock()
    doc.id = doc_id
    doc_dict: dict = {
        "name": name,
        "coordinates": _geo_point(lat, lng),
        "area": area,
        "sports": sports,
        "courtCount": court_count,
        "indoor": indoor,
        "placeId": place_id,
    }
    if status is not None:
        doc_dict["status"] = status
    doc.to_dict.return_value = doc_dict
    return doc


def test_client_visible_statuses_is_live_and_unverified() -> None:
    assert CLIENT_VISIBLE_STATUSES == ["live", "unverified"]


class TestGetById:
    def test_returns_none_when_doc_missing(self) -> None:
        repo, client = _make_repo()
        mock_snap = MagicMock()
        mock_snap.exists = False
        client.collection.return_value.document.return_value.get.return_value = (
            mock_snap
        )

        result = repo.get_by_id("venue_unknown")

        assert result is None
        client.collection.assert_called_once_with("venues")
        client.collection.return_value.document.assert_called_once_with("venue_unknown")

    def test_returns_venue_summary_with_geopoint_coordinates(self) -> None:
        repo, client = _make_repo()
        mock_snap = MagicMock()
        mock_snap.exists = True
        mock_snap.id = "venue_flisvos"
        mock_snap.to_dict.return_value = {
            "name": "Flisvos Padel Academy",
            "coordinates": _geo_point(37.93, 23.68),
            "area": "athens",
            "sports": ["padel", "tennis"],
            "courtCount": 6,
            "indoor": False,
            "placeId": "ChIJFlisvos",
        }
        client.collection.return_value.document.return_value.get.return_value = (
            mock_snap
        )

        result = repo.get_by_id("venue_flisvos")

        assert result is not None
        assert isinstance(result, VenueSummary)
        assert result.venue_id == "venue_flisvos"
        assert result.name == "Flisvos Padel Academy"
        assert result.coordinates.lat == 37.93
        assert result.coordinates.lng == 23.68
        assert result.area == "athens"
        assert result.sports == [SportEnum.PADEL, SportEnum.TENNIS]
        assert result.court_count == 6
        assert result.indoor is False
        assert result.place_id == "ChIJFlisvos"

    def test_returns_venue_summary_with_nullable_fields_missing(self) -> None:
        repo, client = _make_repo()
        mock_snap = MagicMock()
        mock_snap.exists = True
        mock_snap.id = "venue_glyfada"
        mock_snap.to_dict.return_value = {
            "name": "Glyfada Tennis Club",
            "coordinates": {"lat": 37.86, "lng": 23.75},
            "area": "athens",
            "sports": ["tennis"],
        }
        client.collection.return_value.document.return_value.get.return_value = (
            mock_snap
        )

        result = repo.get_by_id("venue_glyfada")

        assert result is not None
        assert result.venue_id == "venue_glyfada"
        assert result.coordinates.lat == 37.86
        assert result.coordinates.lng == 23.75
        assert result.sports == [SportEnum.TENNIS]
        assert result.court_count is None
        assert result.indoor is None
        assert result.place_id is None

    def test_returns_hidden_status_unfiltered(self) -> None:
        """get_by_id is intentionally unfiltered by status (D3)."""
        repo, client = _make_repo()
        mock_snap = MagicMock()
        mock_snap.exists = True
        mock_snap.id = "venue_hidden"
        mock_snap.to_dict.return_value = {
            "name": "Not Yet Launched Club",
            "coordinates": {"lat": 37.86, "lng": 23.75},
            "area": "lavrio",
            "sports": ["tennis"],
            "status": "hidden",
        }
        client.collection.return_value.document.return_value.get.return_value = (
            mock_snap
        )

        result = repo.get_by_id("venue_hidden")

        assert result is not None
        assert result.status.value == "hidden"


class TestListBySportAndArea:
    def test_filters_by_sport_only_when_area_is_none(self) -> None:
        repo, client = _make_repo()

        collection_mock = MagicMock()
        where_sport_mock = MagicMock()
        where_status_mock = MagicMock()
        ordered_mock = MagicMock()
        limited_mock = MagicMock()
        client.collection.return_value = collection_mock
        collection_mock.where.return_value = where_sport_mock
        where_sport_mock.where.return_value = where_status_mock
        where_status_mock.order_by.return_value = ordered_mock
        ordered_mock.limit.return_value = limited_mock
        limited_mock.stream.return_value = [
            _make_venue_doc(
                "venue_flisvos",
                name="Flisvos Padel Academy",
                lat=37.93,
                lng=23.68,
                area="athens",
                sports=["padel"],
                court_count=6,
                indoor=False,
            ),
            _make_venue_doc(
                "venue_glyfada",
                name="Glyfada Padel Club",
                lat=37.86,
                lng=23.75,
                area="athens",
                sports=["padel", "tennis"],
                court_count=4,
                indoor=True,
            ),
        ]

        result = repo.list_by_sport_and_area("padel")

        client.collection.assert_called_once_with("venues")
        collection_mock.where.assert_called_once_with(
            "sports", "array_contains", "padel"
        )
        # No area filter → status filter is called directly on the sport where-result
        where_sport_mock.where.assert_called_once_with(
            "status", "in", ["live", "unverified"]
        )
        where_status_mock.order_by.assert_called_once_with("name")
        assert len(result) == 2
        assert [v.venue_id for v in result] == ["venue_flisvos", "venue_glyfada"]
        assert result[0].area == "athens"
        assert result[1].sports == [SportEnum.PADEL, SportEnum.TENNIS]

    def test_filters_by_sport_and_area_when_area_provided(self) -> None:
        repo, client = _make_repo()

        collection_mock = MagicMock()
        where_sport_mock = MagicMock()
        where_area_mock = MagicMock()
        where_status_mock = MagicMock()
        ordered_mock = MagicMock()
        limited_mock = MagicMock()
        client.collection.return_value = collection_mock
        collection_mock.where.return_value = where_sport_mock
        where_sport_mock.where.return_value = where_area_mock
        where_area_mock.where.return_value = where_status_mock
        where_status_mock.order_by.return_value = ordered_mock
        ordered_mock.limit.return_value = limited_mock
        limited_mock.stream.return_value = [
            _make_venue_doc(
                "venue_glyfada_tennis",
                name="Glyfada Tennis Club",
                lat=37.86,
                lng=23.75,
                area="athens",
                sports=["tennis"],
                court_count=8,
                indoor=False,
                place_id="ChIJGlyfada",
            ),
        ]

        result = repo.list_by_sport_and_area("tennis", area="athens")

        collection_mock.where.assert_called_once_with(
            "sports", "array_contains", "tennis"
        )
        where_sport_mock.where.assert_called_once_with("area", "==", "athens")
        where_area_mock.where.assert_called_once_with(
            "status", "in", ["live", "unverified"]
        )
        where_status_mock.order_by.assert_called_once_with("name")
        assert len(result) == 1
        venue = result[0]
        assert venue.venue_id == "venue_glyfada_tennis"
        assert venue.area == "athens"
        assert venue.sports == [SportEnum.TENNIS]
        assert venue.place_id == "ChIJGlyfada"

    def test_returns_empty_list_when_no_matches(self) -> None:
        repo, client = _make_repo()

        collection_mock = MagicMock()
        where_sport_mock = MagicMock()
        where_status_mock = MagicMock()
        ordered_mock = MagicMock()
        limited_mock = MagicMock()
        client.collection.return_value = collection_mock
        collection_mock.where.return_value = where_sport_mock
        where_sport_mock.where.return_value = where_status_mock
        where_status_mock.order_by.return_value = ordered_mock
        ordered_mock.limit.return_value = limited_mock
        limited_mock.stream.return_value = []

        result = repo.list_by_sport_and_area("pickleball")

        assert result == []

    def test_excludes_hidden_and_includes_unverified(self) -> None:
        """Value-level proof that the status filter shapes what comes back."""
        repo, client = _make_repo()

        collection_mock = MagicMock()
        where_sport_mock = MagicMock()
        where_status_mock = MagicMock()
        ordered_mock = MagicMock()
        limited_mock = MagicMock()
        client.collection.return_value = collection_mock
        collection_mock.where.return_value = where_sport_mock
        where_sport_mock.where.return_value = where_status_mock
        where_status_mock.order_by.return_value = ordered_mock
        ordered_mock.limit.return_value = limited_mock
        # The mock query itself doesn't filter — this asserts the *query call*
        # requests only live/unverified, proving the repo never asks Firestore
        # for hidden rows in the first place.
        limited_mock.stream.return_value = [
            _make_venue_doc(
                "venue_unverified",
                name="Generic Court",
                lat=37.9,
                lng=23.7,
                area="athens",
                sports=["tennis"],
                status="unverified",
            ),
        ]

        result = repo.list_by_sport_and_area("tennis")

        where_sport_mock.where.assert_called_once_with(
            "status", "in", ["live", "unverified"]
        )
        assert len(result) == 1
        assert result[0].status.value == "unverified"


class TestListBySportAndAreaPagination:
    def _setup_chain(
        self, client: MagicMock, area: str | None = None
    ) -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
        collection_mock = MagicMock()
        where_sport_mock = MagicMock()
        where_status_mock = MagicMock()
        ordered_mock = MagicMock()
        limited_mock = MagicMock()
        client.collection.return_value = collection_mock
        collection_mock.where.return_value = where_sport_mock
        if area is not None:
            where_area_mock = MagicMock()
            where_sport_mock.where.return_value = where_area_mock
            where_area_mock.where.return_value = where_status_mock
        else:
            where_sport_mock.where.return_value = where_status_mock
        where_status_mock.order_by.return_value = ordered_mock
        ordered_mock.limit.return_value = limited_mock
        limited_mock.stream.return_value = []
        return collection_mock, where_sport_mock, ordered_mock, limited_mock

    def test_limit_passed_to_firestore_query(self) -> None:
        repo, client = _make_repo()
        _, _, ordered_mock, limited_mock = self._setup_chain(client)

        repo.list_by_sport_and_area("padel", limit=5)

        ordered_mock.limit.assert_called_once_with(5)

    def test_cursor_applies_start_after_on_name(self) -> None:
        repo, client = _make_repo()
        _, _, _, limited_mock = self._setup_chain(client)

        repo.list_by_sport_and_area("padel", cursor={"name": "Athens Padel Club"})

        limited_mock.start_after.assert_called_once_with(["Athens Padel Club"])

    def test_no_cursor_skips_start_after(self) -> None:
        repo, client = _make_repo()
        _, _, _, limited_mock = self._setup_chain(client)

        repo.list_by_sport_and_area("padel")

        limited_mock.start_after.assert_not_called()


class TestSearchByNamePrefix:
    def _setup_chain(self, client: MagicMock) -> MagicMock:
        collection_mock = MagicMock()
        where_ge_mock = MagicMock()
        where_lt_mock = MagicMock()
        where_status_mock = MagicMock()
        ordered_mock = MagicMock()
        limited_mock = MagicMock()
        client.collection.return_value = collection_mock
        collection_mock.where.return_value = where_ge_mock
        where_ge_mock.where.return_value = where_lt_mock
        where_lt_mock.where.return_value = where_status_mock
        where_status_mock.order_by.return_value = ordered_mock
        ordered_mock.limit.return_value = limited_mock
        return limited_mock

    def test_includes_status_filter(self) -> None:
        repo, client = _make_repo()
        limited_mock = self._setup_chain(client)
        limited_mock.stream.return_value = [
            _make_venue_doc(
                "venue_unverified",
                name="Generic Court",
                lat=37.9,
                lng=23.7,
                area="athens",
                sports=["tennis"],
                status="unverified",
            ),
        ]

        result = repo.search_by_name_prefix("Gen")

        collection_mock = client.collection.return_value
        collection_mock.where.assert_called_once_with("name", ">=", "Gen")
        collection_mock.where.return_value.where.assert_called_once_with(
            "name", "<", "Geo"
        )
        collection_mock.where.return_value.where.return_value.where.assert_called_once_with(
            "status", "in", ["live", "unverified"]
        )
        assert len(result) == 1
        assert result[0].status.value == "unverified"
