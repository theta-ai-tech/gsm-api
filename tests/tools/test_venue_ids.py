import pytest

from tools.venue_ids import (
    VenueIdCollisionError,
    VenueIdRegistry,
    slugify,
    venue_id_for_manual,
    venue_id_for_osm,
)


def test_osm_id_is_deterministic():
    first = venue_id_for_osm("way", 123456)
    second = venue_id_for_osm("way", 123456)
    assert first == second == "osm_way_123456"


def test_osm_id_normalizes_type_case_and_accepts_str_id():
    assert venue_id_for_osm("WAY", "123456") == "osm_way_123456"
    assert venue_id_for_osm("Node", 42) == "osm_node_42"
    assert venue_id_for_osm("relation", 7) == "osm_relation_7"


def test_osm_id_rejects_unknown_element_type():
    with pytest.raises(ValueError):
        venue_id_for_osm("area", 1)


def test_osm_id_rejects_non_numeric_id():
    with pytest.raises(ValueError):
        venue_id_for_osm("way", "abc")


def test_manual_id_is_deterministic_and_documented_rule():
    first = venue_id_for_manual("Ten Twenty Club", "Athens")
    second = venue_id_for_manual("Ten Twenty Club", "Athens")
    assert first == second == "manual_athens_ten_twenty_club"


def test_manual_id_strips_accents_and_collapses_separators():
    assert venue_id_for_manual("Glyfáda  Tennis-Club!", "Athens") == (
        "manual_athens_glyfada_tennis_club"
    )


def test_manual_id_distinct_per_metro():
    athens = venue_id_for_manual("Sports Club", "Athens")
    patras = venue_id_for_manual("Sports Club", "Patras")
    assert athens != patras


def test_manual_id_rejects_empty_slug():
    with pytest.raises(ValueError):
        venue_id_for_manual("!!!", "Athens")
    with pytest.raises(ValueError):
        venue_id_for_manual("Club", "###")


def test_slugify_basics():
    assert slugify("Ten Twenty Club") == "ten_twenty_club"
    assert slugify("  Leading/Trailing  ") == "leading_trailing"


def test_registry_allows_idempotent_same_payload():
    registry = VenueIdRegistry()
    payload = {"name": "Club A"}
    registry.register("osm_way_1", payload)
    registry.register("osm_way_1", {"name": "Club A"})
    assert "osm_way_1" in registry
    assert len(registry) == 1


def test_registry_raises_on_distinct_venue_collision():
    registry = VenueIdRegistry()
    registry.register("manual_athens_club", {"name": "Club A"})
    with pytest.raises(VenueIdCollisionError):
        registry.register("manual_athens_club", {"name": "Club B"})


def test_registry_assignments_are_copied():
    registry = VenueIdRegistry()
    registry.register("osm_node_5", {"name": "X"})
    snapshot = registry.assignments
    snapshot["osm_node_5"] = "mutated"
    assert registry.assignments["osm_node_5"] == {"name": "X"}
