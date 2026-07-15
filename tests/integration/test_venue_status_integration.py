"""Integration tests for venue lifecycle status against the Firestore emulator.

Proves the client-visible read paths (VenueRepo.list_by_sport_and_area,
VenueRepo.search_by_name_prefix) filter out hidden venues while still
returning unverified ones, and that tools.set_area_status flips a region's
hidden venues to live without touching unverified rows in the same area.
"""

from __future__ import annotations

import pytest
from google.cloud import firestore

from app.repos.venue_repo import VenueRepo
from tools.seed_mapping import venue_summary_to_firestore_doc
from tools.set_area_status import set_area_status
from app.models.common import GeoCoordinates
from app.models.enums import SportEnum, VenueStatusEnum
from app.models.venue import VenueSummary

pytestmark = pytest.mark.integration

# Use a fake, never-launched area so this suite is fully isolated from seeded
# data and from other test files touching real launch metros.
_AREA = "statustest_zzztestarea"
_PREFIX = "statustest_"


def _venue(
    venue_id: str, name: str, status: VenueStatusEnum, area: str = _AREA
) -> VenueSummary:
    return VenueSummary(
        venue_id=venue_id,
        name=name,
        coordinates=GeoCoordinates(lat=10.0, lng=10.0),
        area=area,
        sports=[SportEnum.TENNIS],
        status=status,
    )


@pytest.fixture
def _cleanup_venues(db: firestore.Client):
    written: list[str] = []
    yield written
    for venue_id in written:
        db.collection("venues").document(venue_id).delete()


def _write(db: firestore.Client, venue: VenueSummary) -> None:
    db.collection("venues").document(venue.venue_id).set(
        venue_summary_to_firestore_doc(venue), merge=False
    )


def test_list_excludes_hidden_includes_unverified(
    db: firestore.Client, _cleanup_venues
):
    live = _venue(f"{_PREFIX}live", "StatusTest Live Club", VenueStatusEnum.LIVE)
    hidden = _venue(
        f"{_PREFIX}hidden", "StatusTest Hidden Club", VenueStatusEnum.HIDDEN
    )
    unverified = _venue(
        f"{_PREFIX}unverified",
        "StatusTest Unverified Court",
        VenueStatusEnum.UNVERIFIED,
    )
    for v in (live, hidden, unverified):
        _cleanup_venues.append(v.venue_id)
        _write(db, v)

    repo = VenueRepo(db)
    results = repo.list_by_sport_and_area("tennis", area=_AREA)

    result_ids = {v.venue_id for v in results}
    assert live.venue_id in result_ids
    assert unverified.venue_id in result_ids
    assert hidden.venue_id not in result_ids


def test_search_excludes_hidden(db: firestore.Client, _cleanup_venues):
    live = _venue(
        f"{_PREFIX}searchlive", "StatusTest SearchLive Club", VenueStatusEnum.LIVE
    )
    hidden = _venue(
        f"{_PREFIX}searchhidden", "StatusTest SearchHidden Club", VenueStatusEnum.HIDDEN
    )
    for v in (live, hidden):
        _cleanup_venues.append(v.venue_id)
        _write(db, v)

    repo = VenueRepo(db)
    results = repo.search_by_name_prefix("StatusTest Search")

    result_ids = {v.venue_id for v in results}
    assert live.venue_id in result_ids
    assert hidden.venue_id not in result_ids


def test_flip_tool_launches_region_without_touching_unverified(
    db: firestore.Client, _cleanup_venues
):
    hidden_a = _venue(
        f"{_PREFIX}flip_hidden_a", "StatusTest Flip Hidden A", VenueStatusEnum.HIDDEN
    )
    hidden_b = _venue(
        f"{_PREFIX}flip_hidden_b", "StatusTest Flip Hidden B", VenueStatusEnum.HIDDEN
    )
    unverified = _venue(
        f"{_PREFIX}flip_unverified",
        "StatusTest Flip Unverified",
        VenueStatusEnum.UNVERIFIED,
    )
    for v in (hidden_a, hidden_b, unverified):
        _cleanup_venues.append(v.venue_id)
        _write(db, v)

    updated = set_area_status(db, _AREA, "hidden", "live")
    assert updated == 2

    repo = VenueRepo(db)
    results = repo.list_by_sport_and_area("tennis", area=_AREA)
    result_by_id = {v.venue_id: v for v in results}

    assert result_by_id[hidden_a.venue_id].status == VenueStatusEnum.LIVE
    assert result_by_id[hidden_b.venue_id].status == VenueStatusEnum.LIVE
    # The pre-existing unverified doc in the same area was left untouched.
    assert result_by_id[unverified.venue_id].status == VenueStatusEnum.UNVERIFIED
