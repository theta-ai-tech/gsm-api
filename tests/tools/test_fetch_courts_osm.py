from tools.fetch_courts_osm import (
    METRO_BBOXES,
    SPORTS,
    build_overpass_query,
    parse_overpass_response,
)


def test_query_covers_all_metros_and_sports():
    query = build_overpass_query()
    for metro in METRO_BBOXES:
        assert f"// {metro}" in query
    for sport in SPORTS:
        assert f'"sport"~"(^|;){sport}($|;)"' in query


def test_query_uses_out_center_and_json():
    query = build_overpass_query()
    assert query.startswith("[out:json]")
    assert "out center;" in query
    assert "out center tags;" not in query


def test_query_includes_all_tag_and_element_permutations():
    query = build_overpass_query(
        bboxes={"athens": (37.80, 23.55, 38.15, 23.95)},
        sports=("tennis",),
    )
    bbox = "37.8,23.55,38.15,23.95"
    for tag in ('"leisure"="pitch"', '"leisure"="sports_centre"', '"club"="sport"'):
        for element in ("node", "way", "relation"):
            assert f'{element}[{tag}]["sport"~"(^|;)tennis($|;)"]({bbox});' in query


def test_parse_node_uses_lat_lon_directly():
    payload = {
        "elements": [
            {
                "type": "node",
                "id": 111,
                "lat": 37.9,
                "lon": 23.7,
                "tags": {
                    "name": "Athens Tennis Club",
                    "sport": "tennis",
                    "leisure": "pitch",
                    "surface": "clay",
                    "courts": "6",
                },
            }
        ]
    }
    [candidate] = parse_overpass_response(payload)
    assert candidate == {
        "name": "Athens Tennis Club",
        "lat": 37.9,
        "lng": 23.7,
        "sports": ["tennis"],
        "osm_type": "node",
        "osm_id": 111,
        "courts": "6",
        "surface": "clay",
        "building": None,
        "indoor": None,
    }


def test_parse_extracts_indoor_tag():
    payload = {
        "elements": [
            {
                "type": "way",
                "id": 666,
                "center": {"lat": 37.9, "lon": 23.7},
                "tags": {
                    "name": "Indoor Padel Arena",
                    "sport": "padel",
                    "leisure": "sports_centre",
                    "indoor": "yes",
                },
            }
        ]
    }
    [candidate] = parse_overpass_response(payload)
    assert candidate["indoor"] == "yes"


def test_parse_way_uses_center_coordinates():
    payload = {
        "elements": [
            {
                "type": "way",
                "id": 222,
                "center": {"lat": 40.6, "lon": 22.95},
                "tags": {
                    "name": "Thess Padel",
                    "sport": "padel",
                    "leisure": "sports_centre",
                    "building": "yes",
                },
            }
        ]
    }
    [candidate] = parse_overpass_response(payload)
    assert candidate["osm_type"] == "way"
    assert candidate["lat"] == 40.6
    assert candidate["lng"] == 22.95
    assert candidate["building"] == "yes"
    assert candidate["surface"] is None
    assert candidate["courts"] is None


def test_parse_splits_multi_sport_tag():
    payload = {
        "elements": [
            {
                "type": "relation",
                "id": 333,
                "center": {"lat": 38.24, "lon": 21.73},
                "tags": {"name": "Patras Complex", "sport": "tennis;padel"},
            }
        ]
    }
    [candidate] = parse_overpass_response(payload)
    assert candidate["sports"] == ["tennis", "padel"]
    assert candidate["osm_type"] == "relation"


def test_parse_skips_elements_without_coordinates():
    payload = {
        "elements": [
            {
                "type": "way",
                "id": 444,
                "tags": {"name": "No Center", "sport": "tennis"},
            },
        ]
    }
    assert parse_overpass_response(payload) == []


def test_parse_handles_missing_tags():
    payload = {"elements": [{"type": "node", "id": 555, "lat": 37.0, "lon": 23.0}]}
    [candidate] = parse_overpass_response(payload)
    assert candidate["name"] is None
    assert candidate["sports"] == []
