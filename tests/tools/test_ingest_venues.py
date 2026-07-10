"""Unit tests for the pure parts of tools/ingest_venues.py (no Firestore)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.ingest_venues import (
    ALLOWED_AREAS,
    CheckpointValidationError,
    classify_change,
    load_checkpoint,
    validate_row,
    validate_rows,
)
from tools.venue_ids import venue_id_for_manual


def _row(**overrides):
    """Build a valid camelCase checkpoint row with Athens defaults."""
    base = {
        "venueId": "osm_node_111",
        "name": "Athens Tennis Club",
        "coordinates": {"lat": 37.95, "lng": 23.72},
        "area": "athens",
        "sports": ["tennis"],
        "courtCount": 4,
        "indoor": False,
        "placeId": None,
    }
    base.update(overrides)
    return base


# --- validation happy path --------------------------------------------------


def test_validate_row_returns_venue_summary():
    venue = validate_row(_row(), 0)
    assert venue.venue_id == "osm_node_111"
    assert venue.area == "athens"
    assert venue.court_count == 4


def test_validate_rows_preserves_order():
    rows = [_row(venueId="osm_node_1"), _row(venueId="osm_node_2")]
    venues = validate_rows(rows)
    assert [v.venue_id for v in venues] == ["osm_node_1", "osm_node_2"]


def test_allowed_areas_are_the_three_launch_metros():
    assert ALLOWED_AREAS == {"athens", "thessaloniki", "patras"}


def test_allowed_areas_reject_legacy_london():
    # REGION_MAPPING still carries a legacy "303" -> "london" fixture entry; the
    # explicit allowlist must not let it through.
    assert "london" not in ALLOWED_AREAS


def test_london_area_row_is_rejected():
    with pytest.raises(CheckpointValidationError) as exc:
        validate_row(_row(area="london"), 5)
    message = str(exc.value)
    assert "london" in message
    assert "Row 5" in message


# --- hand-added rows derive a stable venueId --------------------------------


def test_hand_added_row_without_venue_id_is_derived():
    row = _row()
    del row["venueId"]
    venue = validate_row(row, 0)
    assert venue.venue_id == venue_id_for_manual("Athens Tennis Club", "athens")
    assert venue.venue_id == "manual_athens_athens_tennis_club"


def test_hand_added_row_with_blank_venue_id_is_derived():
    venue = validate_row(_row(venueId="   "), 0)
    assert venue.venue_id == venue_id_for_manual("Athens Tennis Club", "athens")


def test_missing_venue_id_without_name_raises():
    row = _row()
    del row["venueId"]
    del row["name"]
    with pytest.raises(CheckpointValidationError) as exc:
        validate_row(row, 3)
    assert "Row 3" in str(exc.value)


# --- invalid data fails loudly ----------------------------------------------


def test_invalid_area_raises_with_venue_id():
    with pytest.raises(CheckpointValidationError) as exc:
        validate_row(_row(area="berlin"), 2)
    message = str(exc.value)
    assert "osm_node_111" in message
    assert "berlin" in message


def test_extra_field_is_rejected():
    with pytest.raises(CheckpointValidationError) as exc:
        validate_row(_row(bogus="x"), 1)
    assert "Row 1" in str(exc.value)


def test_missing_required_field_raises():
    row = _row()
    del row["coordinates"]
    with pytest.raises(CheckpointValidationError):
        validate_row(row, 0)


def test_validate_rows_aborts_on_first_bad_row():
    rows = [_row(venueId="osm_node_ok"), _row(venueId="osm_node_bad", area="mars")]
    with pytest.raises(CheckpointValidationError):
        validate_rows(rows)


# --- duplicate venueId detection --------------------------------------------


def test_validate_rows_rejects_duplicate_explicit_venue_id():
    rows = [
        _row(venueId="osm_node_dup", name="First"),
        _row(venueId="osm_node_ok"),
        _row(venueId="osm_node_dup", name="Second"),
    ]
    with pytest.raises(CheckpointValidationError) as exc:
        validate_rows(rows)
    message = str(exc.value)
    assert "osm_node_dup" in message
    # Names BOTH offending rows (0 and 2), not just the second.
    assert "0" in message
    assert "2" in message


def test_validate_rows_rejects_hand_added_slug_collision():
    # "Ten-Twenty Club" and "Ten Twenty Club" slugify to the same venueId.
    row_a = _row(name="Ten-Twenty Club")
    del row_a["venueId"]
    row_b = _row(name="Ten Twenty Club")
    del row_b["venueId"]
    with pytest.raises(CheckpointValidationError) as exc:
        validate_rows([row_a, row_b])
    assert "manual_athens_ten_twenty_club" in str(exc.value)


def test_validate_rows_rejects_identical_copy_pasted_rows():
    with pytest.raises(CheckpointValidationError):
        validate_rows([_row(), _row()])


# --- classification ---------------------------------------------------------


def test_classify_created_when_no_existing():
    assert classify_change(None, {"name": "x"}) == "created"


def test_classify_unchanged_when_identical():
    doc = {"name": "x", "area": "athens"}
    assert classify_change(dict(doc), dict(doc)) == "unchanged"


def test_classify_updated_when_different():
    assert classify_change({"name": "x"}, {"name": "y"}) == "updated"


# --- load_checkpoint --------------------------------------------------------


def test_load_checkpoint_reads_list(tmp_path: Path):
    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps([_row()]), encoding="utf-8")
    rows = load_checkpoint(path)
    assert isinstance(rows, list)
    assert rows[0]["venueId"] == "osm_node_111"


def test_load_checkpoint_rejects_non_list(tmp_path: Path):
    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    with pytest.raises(CheckpointValidationError):
        load_checkpoint(path)
