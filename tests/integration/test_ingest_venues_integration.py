"""Integration tests for tools/ingest_venues.py against the Firestore emulator."""

from __future__ import annotations

import pytest
from google.cloud import firestore

from tools.ingest_venues import (
    CheckpointValidationError,
    VENUES_COLLECTION,
    ingest_venues,
    validate_rows,
)
from tools.venue_ids import venue_id_for_manual

pytestmark = pytest.mark.integration

# Test venue ids are prefixed so cleanup never touches seeded/curated venues.
_PREFIX = "ingesttest_"


def _row(venue_id: str, **overrides):
    base = {
        "venueId": venue_id,
        "name": "Ingest Test Club",
        "coordinates": {"lat": 37.95, "lng": 23.72},
        "area": "athens",
        "sports": ["tennis"],
        "courtCount": 4,
        "indoor": False,
        "placeId": None,
    }
    base.update(overrides)
    return base


@pytest.fixture
def _cleanup_venues(db: firestore.Client):
    written: list[str] = []
    yield written
    for venue_id in written:
        db.collection(VENUES_COLLECTION).document(venue_id).delete()


def _count(db: firestore.Client, venue_ids: list[str]) -> int:
    return sum(
        1
        for vid in venue_ids
        if db.collection(VENUES_COLLECTION).document(vid).get().exists
    )


def test_ingest_writes_correct_field_shape(db: firestore.Client, _cleanup_venues):
    venue_id = f"{_PREFIX}shape"
    _cleanup_venues.append(venue_id)

    venues = validate_rows([_row(venue_id)])
    summary = ingest_venues(db, venues)

    assert summary.created == 1
    assert summary.updated == 0
    assert summary.unchanged == 0

    doc = db.collection(VENUES_COLLECTION).document(venue_id).get().to_dict()
    assert doc == {
        "name": "Ingest Test Club",
        "coordinates": {"lat": 37.95, "lng": 23.72},
        "area": "athens",  # metro string
        "sports": ["tennis"],
        "courtCount": 4,
        "indoor": False,
        "status": "live",
    }


def test_double_ingest_unchanged_is_idempotent(db: firestore.Client, _cleanup_venues):
    venue_id = f"{_PREFIX}idempotent"
    _cleanup_venues.append(venue_id)
    rows = [_row(venue_id)]

    first = ingest_venues(db, validate_rows(rows))
    assert first.created == 1

    before = db.collection(VENUES_COLLECTION).document(venue_id).get().to_dict()
    second = ingest_venues(db, validate_rows(rows))
    after = db.collection(VENUES_COLLECTION).document(venue_id).get().to_dict()

    assert second.created == 0
    assert second.updated == 0
    assert second.unchanged == 1
    assert before == after
    assert _count(db, [venue_id]) == 1


def test_edited_row_updates_in_place(db: firestore.Client, _cleanup_venues):
    venue_id = f"{_PREFIX}edited"
    _cleanup_venues.append(venue_id)

    ingest_venues(db, validate_rows([_row(venue_id, courtCount=4)]))
    summary = ingest_venues(db, validate_rows([_row(venue_id, courtCount=9)]))

    assert summary.updated == 1
    assert summary.created == 0
    doc = db.collection(VENUES_COLLECTION).document(venue_id).get().to_dict()
    assert doc["courtCount"] == 9
    # Same venueId, no duplicate document.
    assert _count(db, [venue_id]) == 1


def test_hand_added_row_seeds_with_stable_venue_id(
    db: firestore.Client, _cleanup_venues
):
    # No venueId in the row → derived deterministically from name + area.
    row = _row("unused", name=f"{_PREFIX}Hand Added Padel")
    del row["venueId"]
    expected_id = venue_id_for_manual(f"{_PREFIX}Hand Added Padel", "athens")
    _cleanup_venues.append(expected_id)

    venues = validate_rows([row])
    assert venues[0].venue_id == expected_id
    ingest_venues(db, venues)

    assert db.collection(VENUES_COLLECTION).document(expected_id).get().exists


def test_duplicate_venue_id_aborts_before_any_write(
    db: firestore.Client, _cleanup_venues
):
    dup_id = f"{_PREFIX}dup"
    _cleanup_venues.append(dup_id)

    rows = [_row(dup_id, name="First"), _row(dup_id, name="Second")]

    with pytest.raises(CheckpointValidationError):
        # Duplicate venueId is caught in validate_rows before any write happens.
        ingest_venues(db, validate_rows(rows))

    assert _count(db, [dup_id]) == 0


def test_non_live_area_without_hidden_status_aborts_before_any_write(
    db: firestore.Client, _cleanup_venues
):
    good_id = f"{_PREFIX}good"
    bad_id = f"{_PREFIX}bad"
    _cleanup_venues.extend([good_id, bad_id])

    rows = [_row(good_id), _row(bad_id, area="atlantis")]

    with pytest.raises(CheckpointValidationError):
        # Validation happens before any Firestore write — nothing is persisted.
        ingest_venues(db, validate_rows(rows))

    assert _count(db, [good_id, bad_id]) == 0


def test_non_live_area_with_hidden_status_ingests_as_hidden(
    db: firestore.Client, _cleanup_venues
):
    venue_id = f"{_PREFIX}lavrio_hidden"
    _cleanup_venues.append(venue_id)

    rows = [_row(venue_id, area="lavrio", status="hidden")]
    summary = ingest_venues(db, validate_rows(rows))

    assert summary.created == 1
    doc = db.collection(VENUES_COLLECTION).document(venue_id).get().to_dict()
    assert doc["area"] == "lavrio"
    assert doc["status"] == "hidden"
