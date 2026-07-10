import logging

import pytest

from app.models.enums import SportEnum
from tools.normalize_courts import (
    metro_for_coords,
    normalize_candidate,
    normalize_candidates,
    sports_from_osm,
)
from tools.venue_ids import VenueIdCollisionError, VenueIdRegistry


def _raw(**overrides):
    """Build a raw OSM candidate dict with sensible Athens defaults."""
    base = {
        "name": "Athens Tennis Club",
        "lat": 37.95,
        "lng": 23.72,
        "sports": ["tennis"],
        "osm_type": "node",
        "osm_id": 111,
        "courts": None,
        "surface": None,
        "building": None,
    }
    base.update(overrides)
    return base


# --- metro assignment -------------------------------------------------------


@pytest.mark.parametrize(
    ("lat", "lng", "metro"),
    [
        (37.95, 23.72, "athens"),
        (40.62, 22.95, "thessaloniki"),
        (38.24, 21.73, "patras"),
    ],
)
def test_metro_for_coords_assigns_each_metro(lat, lng, metro):
    assert metro_for_coords(lat, lng) == metro


def test_metro_for_coords_outside_all_boxes_returns_none():
    assert metro_for_coords(0.0, 0.0) is None


def test_normalize_assigns_correct_metro_per_row():
    registry = VenueIdRegistry()
    athens = normalize_candidate(_raw(lat=37.95, lng=23.72), registry)
    thess = normalize_candidate(_raw(osm_id=2, lat=40.62, lng=22.95), registry)
    patras = normalize_candidate(_raw(osm_id=3, lat=38.24, lng=21.73), registry)
    assert athens is not None and athens.area == "athens"
    assert thess is not None and thess.area == "thessaloniki"
    assert patras is not None and patras.area == "patras"


# --- sport filtering --------------------------------------------------------


def test_sports_from_osm_filters_unsupported_values():
    assert sports_from_osm(["tennis", "basketball", "padel"]) == [
        SportEnum.TENNIS,
        SportEnum.PADEL,
    ]


def test_sports_from_osm_deduplicates_preserving_order():
    assert sports_from_osm(["padel", "padel", "tennis"]) == [
        SportEnum.PADEL,
        SportEnum.TENNIS,
    ]


def test_unsupported_sport_does_not_crash_and_keeps_supported():
    registry = VenueIdRegistry()
    venue = normalize_candidate(_raw(sports=["tennis", "quidditch"]), registry)
    assert venue is not None
    assert venue.sports == [SportEnum.TENNIS]


def test_multi_sport_collapses_into_one_row():
    registry = VenueIdRegistry()
    venue = normalize_candidate(_raw(sports=["tennis", "padel"]), registry)
    assert venue is not None
    assert venue.sports == [SportEnum.TENNIS, SportEnum.PADEL]


# --- optional fields --------------------------------------------------------


def test_missing_court_count_yields_none():
    registry = VenueIdRegistry()
    venue = normalize_candidate(_raw(courts=None), registry)
    assert venue is not None
    assert venue.court_count is None


def test_court_count_parsed_from_tag():
    registry = VenueIdRegistry()
    venue = normalize_candidate(_raw(courts="6"), registry)
    assert venue is not None
    assert venue.court_count == 6


def test_invalid_court_count_is_none():
    registry = VenueIdRegistry()
    venue = normalize_candidate(_raw(courts="lots"), registry)
    assert venue is not None
    assert venue.court_count is None


def test_missing_indoor_tag_yields_none():
    registry = VenueIdRegistry()
    venue = normalize_candidate(_raw(building=None, indoor=None), registry)
    assert venue is not None
    assert venue.indoor is None


def test_indoor_inferred_from_building_tag():
    registry = VenueIdRegistry()
    venue = normalize_candidate(_raw(building="yes"), registry)
    assert venue is not None
    assert venue.indoor is True


def test_explicit_indoor_no_overrides_building():
    registry = VenueIdRegistry()
    venue = normalize_candidate(_raw(building="yes", indoor="no"), registry)
    assert venue is not None
    assert venue.indoor is False


def test_place_id_always_null():
    registry = VenueIdRegistry()
    venue = normalize_candidate(_raw(), registry)
    assert venue is not None
    assert venue.place_id is None


def test_deterministic_venue_id_from_osm():
    registry = VenueIdRegistry()
    venue = normalize_candidate(_raw(osm_type="way", osm_id=123456), registry)
    assert venue is not None
    assert venue.venue_id == "osm_way_123456"


# --- drops ------------------------------------------------------------------


def test_missing_name_dropped_with_reason(caplog):
    registry = VenueIdRegistry()
    with caplog.at_level(logging.INFO, logger="normalize_courts"):
        assert normalize_candidate(_raw(name=None), registry) is None
    assert any("missing name" in r.message for r in caplog.records)


def test_missing_coords_dropped_with_reason(caplog):
    registry = VenueIdRegistry()
    with caplog.at_level(logging.INFO, logger="normalize_courts"):
        assert normalize_candidate(_raw(lat=None), registry) is None
    assert any("missing coordinates" in r.message for r in caplog.records)


def test_coords_outside_metros_dropped_with_reason(caplog):
    registry = VenueIdRegistry()
    with caplog.at_level(logging.INFO, logger="normalize_courts"):
        assert normalize_candidate(_raw(lat=0.0, lng=0.0), registry) is None
    assert any("outside every metro box" in r.message for r in caplog.records)


def test_no_supported_sport_dropped_with_reason(caplog):
    registry = VenueIdRegistry()
    with caplog.at_level(logging.INFO, logger="normalize_courts"):
        assert normalize_candidate(_raw(sports=["basketball"]), registry) is None
    assert any("no supported sports" in r.message for r in caplog.records)


# --- aggregate --------------------------------------------------------------


def test_normalize_candidates_dedupes_identical_and_sorts():
    duplicate = _raw(osm_type="way", osm_id=222, name="Dup Club", sports=["tennis"])
    another = _raw(osm_type="node", osm_id=111, name="Alpha Club", lat=40.62, lng=22.95)
    venues = normalize_candidates([duplicate, dict(duplicate), another])
    assert [v.venue_id for v in venues] == ["osm_node_111", "osm_way_222"]


def test_normalize_candidates_raises_on_distinct_collision():
    a = _raw(osm_type="way", osm_id=222, name="Club A")
    b = _raw(osm_type="way", osm_id=222, name="Club B")
    with pytest.raises(VenueIdCollisionError):
        normalize_candidates([a, b])
