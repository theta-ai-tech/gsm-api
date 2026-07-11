from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.enums import SportEnum
from app.repos.mappers import _parse_geo_coordinates, to_venue_summary


class TestParseGeoCoordinates:
    def test_parses_firestore_geopoint_like_object(self) -> None:
        value = SimpleNamespace(latitude=37.93, longitude=23.68)

        result = _parse_geo_coordinates(value)

        assert result.lat == 37.93
        assert result.lng == 23.68

    def test_parses_plain_dict(self) -> None:
        result = _parse_geo_coordinates({"lat": 37.86, "lng": 23.75})

        assert result.lat == 37.86
        assert result.lng == 23.75

    def test_raises_for_none(self) -> None:
        with pytest.raises(ValueError, match="coordinates"):
            _parse_geo_coordinates(None)

    def test_raises_for_unsupported_type(self) -> None:
        with pytest.raises(ValueError, match="Unsupported"):
            _parse_geo_coordinates("37.93,23.68")

    def test_raises_for_dict_missing_lng(self) -> None:
        with pytest.raises(ValueError, match="Missing 'lat' or 'lng'"):
            _parse_geo_coordinates({"lat": 37.93})

    def test_raises_for_dict_missing_lat(self) -> None:
        with pytest.raises(ValueError, match="Missing 'lat' or 'lng'"):
            _parse_geo_coordinates({"lng": 23.68})

    def test_raises_for_empty_dict(self) -> None:
        with pytest.raises(ValueError, match="Missing 'lat' or 'lng'"):
            _parse_geo_coordinates({})

    def test_raises_for_geopoint_with_invalid_latitude(self) -> None:
        # non-None but non-numeric latitude enters the GeoPoint branch and must
        # raise ValueError (not TypeError) after the try/except guard
        with pytest.raises(ValueError, match="Invalid coordinate value"):
            _parse_geo_coordinates(SimpleNamespace(latitude=object(), longitude=23.68))

    def test_raises_for_dict_with_none_lat(self) -> None:
        with pytest.raises(ValueError, match="Invalid coordinate value"):
            _parse_geo_coordinates({"lat": None, "lng": 23.68})

    def test_raises_for_dict_with_non_numeric_value(self) -> None:
        with pytest.raises(ValueError, match="Invalid coordinate value"):
            _parse_geo_coordinates({"lat": object(), "lng": 23.68})

    def test_raises_for_geopoint_with_out_of_range_latitude(self) -> None:
        # float() succeeds but GeoCoordinates(lat=91.0) raises ValidationError
        # which must be caught and re-raised as ValueError
        with pytest.raises(ValueError, match="Invalid coordinate value"):
            _parse_geo_coordinates(SimpleNamespace(latitude=91.0, longitude=23.68))

    def test_raises_for_dict_with_out_of_range_longitude(self) -> None:
        with pytest.raises(ValueError, match="Invalid coordinate value"):
            _parse_geo_coordinates({"lat": 37.93, "lng": 200.0})


class TestToVenueSummary:
    def test_maps_all_fields_from_firestore_doc(self) -> None:
        doc = {
            "name": "Flisvos Padel Academy",
            "coordinates": SimpleNamespace(latitude=37.93, longitude=23.68),
            "area": "athens",
            "sports": ["padel", "tennis"],
            "courtCount": 6,
            "indoor": False,
            "placeId": "ChIJFlisvos",
        }

        venue = to_venue_summary(doc, venue_id="venue_flisvos")

        assert venue.venue_id == "venue_flisvos"
        assert venue.name == "Flisvos Padel Academy"
        assert venue.coordinates.lat == 37.93
        assert venue.coordinates.lng == 23.68
        assert venue.area == "athens"
        assert venue.sports == [SportEnum.PADEL, SportEnum.TENNIS]
        assert venue.court_count == 6
        assert venue.indoor is False
        assert venue.place_id == "ChIJFlisvos"

    def test_maps_minimal_doc_with_nullable_fields_missing(self) -> None:
        doc = {
            "name": "Glyfada Tennis Club",
            "coordinates": {"lat": 37.86, "lng": 23.75},
            "area": "athens",
            "sports": ["tennis"],
        }

        venue = to_venue_summary(doc, venue_id="venue_glyfada")

        assert venue.venue_id == "venue_glyfada"
        assert venue.sports == [SportEnum.TENNIS]
        assert venue.court_count is None
        assert venue.indoor is None
        assert venue.place_id is None

    def test_falls_back_to_id_field_when_venue_id_not_passed(self) -> None:
        doc = {
            "id": "venue_fallback",
            "name": "Fallback Courts",
            "coordinates": {"lat": 0.0, "lng": 0.0},
            "area": "athens",
            "sports": ["pickleball"],
        }

        venue = to_venue_summary(doc)

        assert venue.venue_id == "venue_fallback"
        assert venue.sports == [SportEnum.PICKLEBALL]

    def test_raises_when_venue_id_missing_from_both_arg_and_doc(self) -> None:
        doc = {
            "name": "No ID Venue",
            "coordinates": {"lat": 37.93, "lng": 23.68},
            "area": "athens",
            "sports": ["padel"],
        }

        with pytest.raises(ValueError, match="venue_id"):
            to_venue_summary(doc)

    def test_raises_when_name_missing(self) -> None:
        doc = {
            "coordinates": {"lat": 37.93, "lng": 23.68},
            "area": "athens",
            "sports": ["padel"],
        }

        with pytest.raises(ValueError, match="name"):
            to_venue_summary(doc, venue_id="venue_x")

    def test_raises_when_area_missing(self) -> None:
        doc = {
            "name": "No Area Venue",
            "coordinates": {"lat": 37.93, "lng": 23.68},
            "sports": ["padel"],
        }

        with pytest.raises(ValueError, match="area"):
            to_venue_summary(doc, venue_id="venue_x")

    def test_raises_when_sports_missing(self) -> None:
        doc = {
            "name": "No Sports Venue",
            "coordinates": {"lat": 37.93, "lng": 23.68},
            "area": "athens",
        }

        with pytest.raises(ValueError, match="sports"):
            to_venue_summary(doc, venue_id="venue_x")
