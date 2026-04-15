#!/usr/bin/env bash
# Smoke test for PR #265 — VEN-2: venues collection schema, VenueSummary model, VenueRepo
# No emulator needed — repo behaviour is exercised via mocked Firestore client.
# Run from the gsm-api root: bash tests/smoke/pr-265.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYTHON="$REPO_ROOT/.venv/bin/python"
PASS=0
FAIL=0

check() {
  local desc="$1" result="$2"
  if [ "$result" = "true" ]; then
    echo "  PASS: $desc"
    ((PASS++))
  else
    echo "  FAIL: $desc"
    ((FAIL++))
  fi
}

echo "=== PR #265 Smoke Tests: VenueSummary model + VenueRepo ==="
echo ""

OUTPUT=$(PYTHONPATH="$REPO_ROOT/api" "$PYTHON" - <<'PYEOF' 2>&1
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

results = {}

# 1. Imports
try:
    from app.models.venue import VenueSummary  # noqa: F401
    from app.models import VenueSummary as VS2  # noqa: F401
    results["import_model"] = "true"
except Exception as e:
    results["import_model"] = "false"
    print(f"IMPORT_ERROR_MODEL: {e}", file=sys.stderr)

try:
    from app.repos.venue_repo import VenueRepo  # noqa: F401
    results["import_repo"] = "true"
except Exception as e:
    results["import_repo"] = "false"
    print(f"IMPORT_ERROR_REPO: {e}", file=sys.stderr)

try:
    from app.repos.mappers import _parse_geo_coordinates, to_venue_summary  # noqa: F401
    results["import_mapper"] = "true"
except Exception as e:
    results["import_mapper"] = "false"
    print(f"IMPORT_ERROR_MAPPER: {e}", file=sys.stderr)

from app.models import VenueSummary
from app.models.common import GeoCoordinates
from app.models.enums import SportEnum
from app.repos.mappers import _parse_geo_coordinates, to_venue_summary
from app.repos.venue_repo import VenueRepo

# 2. VenueSummary model construction
try:
    v = VenueSummary(
        venue_id="venue_flisvos",
        name="Flisvos Padel Academy",
        coordinates=GeoCoordinates(lat=37.93, lng=23.68),
        area="Palaio Faliro",
        sports=[SportEnum.PADEL, SportEnum.TENNIS],
        court_count=6,
        indoor=False,
        place_id="ChIJFlisvos",
    )
    assert v.venue_id == "venue_flisvos"
    assert v.coordinates.lat == 37.93
    assert v.sports == [SportEnum.PADEL, SportEnum.TENNIS]
    assert v.court_count == 6
    assert v.indoor is False
    assert v.place_id == "ChIJFlisvos"
    results["venuesummary_full"] = "true"
except Exception as e:
    results["venuesummary_full"] = "false"
    print(f"VS_FULL_ERR: {e}", file=sys.stderr)

try:
    v = VenueSummary(
        venue_id="venue_glyfada",
        name="Glyfada Tennis Club",
        coordinates=GeoCoordinates(lat=37.86, lng=23.75),
        area="Glyfada",
        sports=[SportEnum.TENNIS],
    )
    assert v.court_count is None
    assert v.indoor is None
    assert v.place_id is None
    results["venuesummary_nullable_defaults"] = "true"
except Exception as e:
    results["venuesummary_nullable_defaults"] = "false"

try:
    from pydantic import ValidationError
    VenueSummary(
        venue_id="v",
        name="X",
        coordinates=GeoCoordinates(lat=0, lng=0),
        area="A",
        sports=["padel"],
        bogus="x",
    )
    results["venuesummary_extra_forbidden"] = "false"
except Exception:
    results["venuesummary_extra_forbidden"] = "true"

# 3. _parse_geo_coordinates
try:
    g = _parse_geo_coordinates(SimpleNamespace(latitude=37.93, longitude=23.68))
    assert g.lat == 37.93 and g.lng == 23.68
    results["parse_geo_geopoint"] = "true"
except Exception:
    results["parse_geo_geopoint"] = "false"

try:
    g = _parse_geo_coordinates({"lat": 1.5, "lng": 2.5})
    assert g.lat == 1.5 and g.lng == 2.5
    results["parse_geo_dict"] = "true"
except Exception:
    results["parse_geo_dict"] = "false"

try:
    _parse_geo_coordinates(None)
    results["parse_geo_none_raises"] = "false"
except ValueError:
    results["parse_geo_none_raises"] = "true"
except Exception:
    results["parse_geo_none_raises"] = "false"

# 4. to_venue_summary mapper
try:
    doc = {
        "name": "Flisvos Padel Academy",
        "coordinates": SimpleNamespace(latitude=37.93, longitude=23.68),
        "area": "Palaio Faliro",
        "sports": ["padel", "tennis"],
        "courtCount": 6,
        "indoor": False,
        "placeId": "ChIJFlisvos",
    }
    summary = to_venue_summary(doc, venue_id="venue_flisvos")
    assert summary.venue_id == "venue_flisvos"
    assert summary.coordinates.lat == 37.93
    assert summary.sports == [SportEnum.PADEL, SportEnum.TENNIS]
    assert summary.court_count == 6
    assert summary.place_id == "ChIJFlisvos"
    results["to_venue_summary_full"] = "true"
except Exception as e:
    results["to_venue_summary_full"] = "false"
    print(f"MAPPER_FULL_ERR: {e}", file=sys.stderr)

try:
    doc = {
        "name": "Glyfada Tennis Club",
        "coordinates": {"lat": 37.86, "lng": 23.75},
        "area": "Glyfada",
        "sports": ["tennis"],
    }
    summary = to_venue_summary(doc, venue_id="venue_glyfada")
    assert summary.court_count is None
    assert summary.indoor is None
    assert summary.place_id is None
    assert summary.sports == [SportEnum.TENNIS]
    results["to_venue_summary_minimal"] = "true"
except Exception:
    results["to_venue_summary_minimal"] = "false"

# 5. VenueRepo.get_by_id behaviour with mocked Firestore client
try:
    from google.cloud import firestore as gfs  # type: ignore[attr-defined]
    client = MagicMock(spec=gfs.Client)
    snap = MagicMock()
    snap.exists = False
    client.collection.return_value.document.return_value.get.return_value = snap
    repo = VenueRepo(client)
    res = repo.get_by_id("missing")
    assert res is None
    client.collection.assert_called_once_with("venues")
    results["repo_get_by_id_missing"] = "true"
except Exception as e:
    results["repo_get_by_id_missing"] = "false"
    print(f"REPO_GETBYID_MISSING_ERR: {e}", file=sys.stderr)

try:
    client = MagicMock(spec=gfs.Client)
    snap = MagicMock()
    snap.exists = True
    snap.id = "venue_flisvos"
    snap.to_dict.return_value = {
        "name": "Flisvos Padel Academy",
        "coordinates": SimpleNamespace(latitude=37.93, longitude=23.68),
        "area": "Palaio Faliro",
        "sports": ["padel"],
        "courtCount": 6,
        "indoor": False,
        "placeId": "ChIJFlisvos",
    }
    client.collection.return_value.document.return_value.get.return_value = snap
    repo = VenueRepo(client)
    res = repo.get_by_id("venue_flisvos")
    assert res is not None
    assert res.venue_id == "venue_flisvos"
    assert res.coordinates.lat == 37.93
    assert res.sports == [SportEnum.PADEL]
    results["repo_get_by_id_present"] = "true"
except Exception as e:
    results["repo_get_by_id_present"] = "false"
    print(f"REPO_GETBYID_PRESENT_ERR: {e}", file=sys.stderr)

# 6. VenueRepo.list_by_sport_and_area: sport only
try:
    client = MagicMock(spec=gfs.Client)
    coll = MagicMock()
    where_sport = MagicMock()
    ordered = MagicMock()
    client.collection.return_value = coll
    coll.where.return_value = where_sport
    where_sport.order_by.return_value = ordered

    doc = MagicMock()
    doc.id = "venue_flisvos"
    doc.to_dict.return_value = {
        "name": "Flisvos Padel Academy",
        "coordinates": SimpleNamespace(latitude=37.93, longitude=23.68),
        "area": "Palaio Faliro",
        "sports": ["padel"],
        "courtCount": 6,
    }
    ordered.stream.return_value = [doc]

    repo = VenueRepo(client)
    res = repo.list_by_sport_and_area("padel")
    assert len(res) == 1
    assert res[0].venue_id == "venue_flisvos"
    coll.where.assert_called_once_with("sports", "array_contains", "padel")
    where_sport.order_by.assert_called_once_with("name")
    results["repo_list_sport_only"] = "true"
except Exception as e:
    results["repo_list_sport_only"] = "false"
    print(f"REPO_LIST_SPORT_ERR: {e}", file=sys.stderr)

# 7. VenueRepo.list_by_sport_and_area: sport + area
try:
    client = MagicMock(spec=gfs.Client)
    coll = MagicMock()
    where_sport = MagicMock()
    where_area = MagicMock()
    ordered = MagicMock()
    client.collection.return_value = coll
    coll.where.return_value = where_sport
    where_sport.where.return_value = where_area
    where_area.order_by.return_value = ordered

    doc = MagicMock()
    doc.id = "venue_glyfada_tennis"
    doc.to_dict.return_value = {
        "name": "Glyfada Tennis Club",
        "coordinates": {"lat": 37.86, "lng": 23.75},
        "area": "Glyfada",
        "sports": ["tennis"],
    }
    ordered.stream.return_value = [doc]

    repo = VenueRepo(client)
    res = repo.list_by_sport_and_area("tennis", area="Glyfada")
    assert len(res) == 1
    assert res[0].area == "Glyfada"
    coll.where.assert_called_once_with("sports", "array_contains", "tennis")
    where_sport.where.assert_called_once_with("area", "==", "Glyfada")
    where_area.order_by.assert_called_once_with("name")
    results["repo_list_sport_and_area"] = "true"
except Exception as e:
    results["repo_list_sport_and_area"] = "false"
    print(f"REPO_LIST_SPORT_AREA_ERR: {e}", file=sys.stderr)

# 8. Empty result list
try:
    client = MagicMock(spec=gfs.Client)
    coll = MagicMock()
    where_sport = MagicMock()
    ordered = MagicMock()
    client.collection.return_value = coll
    coll.where.return_value = where_sport
    where_sport.order_by.return_value = ordered
    ordered.stream.return_value = []

    repo = VenueRepo(client)
    res = repo.list_by_sport_and_area("pickleball")
    assert res == []
    results["repo_list_empty"] = "true"
except Exception:
    results["repo_list_empty"] = "false"

for k, v in results.items():
    print(f"{k}={v}")
PYEOF
)

eval "$OUTPUT" 2>/dev/null || true

echo "1. Imports"
check "VenueSummary importable from app.models.venue and app.models" "${import_model:-false}"
check "VenueRepo importable from app.repos.venue_repo" "${import_repo:-false}"
check "to_venue_summary + _parse_geo_coordinates importable from mappers" "${import_mapper:-false}"

echo ""
echo "2. VenueSummary model"
check "Construct with all fields populated" "${venuesummary_full:-false}"
check "Nullable fields default to None when omitted" "${venuesummary_nullable_defaults:-false}"
check "Rejects unknown extra fields (extra=forbid)" "${venuesummary_extra_forbidden:-false}"

echo ""
echo "3. _parse_geo_coordinates helper"
check "Accepts Firestore GeoPoint-like objects (latitude/longitude)" "${parse_geo_geopoint:-false}"
check "Accepts plain {lat, lng} dicts" "${parse_geo_dict:-false}"
check "Raises ValueError for None" "${parse_geo_none_raises:-false}"

echo ""
echo "4. to_venue_summary mapper"
check "Maps a complete Firestore doc (camelCase keys, GeoPoint coords)" "${to_venue_summary_full:-false}"
check "Maps a minimal doc with nullable fields missing" "${to_venue_summary_minimal:-false}"

echo ""
echo "5. VenueRepo.get_by_id"
check "Returns None when document missing" "${repo_get_by_id_missing:-false}"
check "Returns VenueSummary with venue_id == doc id when present" "${repo_get_by_id_present:-false}"

echo ""
echo "6. VenueRepo.list_by_sport_and_area"
check "Sport-only filter uses array_contains and order_by name" "${repo_list_sport_only:-false}"
check "Sport + area filter chains both where clauses" "${repo_list_sport_and_area:-false}"
check "Returns empty list when no matches" "${repo_list_empty:-false}"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
