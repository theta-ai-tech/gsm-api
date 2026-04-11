#!/usr/bin/env bash
# Smoke test for PR #264 — VEN-1: Create VenueRef value object + GeoCoordinates model
#
# This PR is models-only (no HTTP endpoints), so the smoke test validates the
# models by importing them and exercising each acceptance criterion via Python.
#
# Prerequisites: project venv exists at ./.venv and dependencies are installed.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

PASS=0
FAIL=0

check() {
  local desc="$1" result="$2"
  if [ "$result" = "PASS" ]; then
    echo "  PASS: $desc"
    ((PASS++))
  else
    echo "  FAIL: $desc"
    ((FAIL++))
  fi
}

echo "=== PR #264 Smoke Tests: VenueRef + GeoCoordinates ==="

if [ ! -f ".venv/bin/python" ]; then
  echo "FAIL: .venv/bin/python not found at $REPO_ROOT/.venv"
  exit 1
fi

# Run a single Python process that exercises each acceptance criterion and
# emits one line per check in "RESULT: desc" format that we parse.
OUTPUT=$(. .venv/bin/activate && cd api && python - <<'PYEOF'
import json
import sys

results: list[tuple[str, str]] = []


def record(desc: str, ok: bool) -> None:
    results.append((desc, "PASS" if ok else "FAIL"))


try:
    from pydantic import ValidationError

    from app.models import GeoCoordinates as ExportedGeo
    from app.models import VenueRef as ExportedVenueRef
    from app.models.common import GeoCoordinates, VenueRef

    record("GeoCoordinates and VenueRef importable from app.models", True)
    record("GeoCoordinates re-export matches", ExportedGeo is GeoCoordinates)
    record("VenueRef re-export matches", ExportedVenueRef is VenueRef)
except Exception as exc:  # noqa: BLE001
    print(f"IMPORT_ERROR: {exc}", file=sys.stderr)
    sys.exit(2)

# 1. GeoCoordinates basic construction
try:
    g = GeoCoordinates(lat=37.9838, lng=23.7275)
    record(
        "GeoCoordinates accepts lat/lng floats",
        g.lat == 37.9838 and g.lng == 23.7275,
    )
except Exception:  # noqa: BLE001
    record("GeoCoordinates accepts lat/lng floats", False)

# 2. GeoCoordinates rejects extra fields
try:
    GeoCoordinates(lat=0.0, lng=0.0, altitude=10.0)  # type: ignore[call-arg]
    record("GeoCoordinates rejects extra fields", False)
except ValidationError:
    record("GeoCoordinates rejects extra fields", True)

coords = GeoCoordinates(lat=37.8638, lng=23.7545)

# 3. VenueRef with venue_id only
try:
    v = VenueRef(
        venue_id="venue_athens_padel_glyfada",
        name="Athens Padel Glyfada",
        coordinates=coords,
    )
    record(
        "VenueRef valid with venue_id only",
        v.venue_id == "venue_athens_padel_glyfada" and v.place_id is None,
    )
except Exception:  # noqa: BLE001
    record("VenueRef valid with venue_id only", False)

# 4. VenueRef with place_id only
try:
    v = VenueRef(
        place_id="ChIJN1t_tDeuEmsRUsoyG83frY4",
        name="Google Place Venue",
        coordinates=coords,
    )
    record(
        "VenueRef valid with place_id only",
        v.place_id == "ChIJN1t_tDeuEmsRUsoyG83frY4" and v.venue_id is None,
    )
except Exception:  # noqa: BLE001
    record("VenueRef valid with place_id only", False)

# 5. VenueRef with both ids
try:
    v = VenueRef(
        venue_id="venue_athens_padel_glyfada",
        place_id="ChIJN1t_tDeuEmsRUsoyG83frY4",
        name="Athens Padel Glyfada",
        coordinates=coords,
    )
    record(
        "VenueRef valid with both ids",
        v.venue_id is not None and v.place_id is not None,
    )
except Exception:  # noqa: BLE001
    record("VenueRef valid with both ids", False)

# 6. VenueRef rejects when both ids missing
try:
    VenueRef(name="No ID", coordinates=coords)
    record("VenueRef rejects when both ids missing", False)
except ValidationError:
    record("VenueRef rejects when both ids missing", True)

# 7. VenueRef rejects when both ids explicit None
try:
    VenueRef(venue_id=None, place_id=None, name="No ID", coordinates=coords)
    record("VenueRef rejects when both ids explicitly None", False)
except ValidationError:
    record("VenueRef rejects when both ids explicitly None", True)

# 8. VenueRef rejects when both ids empty string
try:
    VenueRef(venue_id="", place_id="", name="Empty", coordinates=coords)
    record("VenueRef rejects when both ids are empty strings", False)
except ValidationError:
    record("VenueRef rejects when both ids are empty strings", True)

# 9. VenueRef requires name
try:
    VenueRef(venue_id="v_x", coordinates=coords)  # type: ignore[call-arg]
    record("VenueRef requires name", False)
except ValidationError:
    record("VenueRef requires name", True)

# 10. VenueRef requires coordinates
try:
    VenueRef(venue_id="v_x", name="X")  # type: ignore[call-arg]
    record("VenueRef requires coordinates", False)
except ValidationError:
    record("VenueRef requires coordinates", True)

# 11. VenueRef rejects unknown extra fields
try:
    VenueRef(
        venue_id="v_x",
        name="X",
        coordinates=coords,
        city="Athens",  # type: ignore[call-arg]
    )
    record("VenueRef rejects unknown extra fields", False)
except ValidationError:
    record("VenueRef rejects unknown extra fields", True)

# 12. VenueRef camelCase deserialization
try:
    v = VenueRef.model_validate(
        {
            "venueId": "venue_athens_padel_glyfada",
            "placeId": None,
            "name": "Athens Padel Glyfada",
            "coordinates": {"lat": 37.8638, "lng": 23.7545},
        }
    )
    record(
        "VenueRef deserializes camelCase keys",
        v.venue_id == "venue_athens_padel_glyfada"
        and v.coordinates.lat == 37.8638,
    )
except Exception:  # noqa: BLE001
    record("VenueRef deserializes camelCase keys", False)

# 13. VenueRef camelCase serialization via by_alias=True
try:
    v = VenueRef(
        venue_id="venue_athens_padel_glyfada",
        name="Athens Padel Glyfada",
        coordinates=GeoCoordinates(lat=37.8638, lng=23.7545),
    )
    dumped = v.model_dump(by_alias=True)
    record(
        "VenueRef.model_dump(by_alias=True) emits camelCase keys",
        "venueId" in dumped and "placeId" in dumped and "venue_id" not in dumped,
    )
except Exception:  # noqa: BLE001
    record("VenueRef.model_dump(by_alias=True) emits camelCase keys", False)

# 14. VenueRef snake_case default serialization
try:
    v = VenueRef(
        venue_id="venue_athens_padel_glyfada",
        name="Athens Padel Glyfada",
        coordinates=GeoCoordinates(lat=37.8638, lng=23.7545),
    )
    dumped = v.model_dump()
    record(
        "VenueRef.model_dump() default emits snake_case keys",
        "venue_id" in dumped and "place_id" in dumped and "venueId" not in dumped,
    )
except Exception:  # noqa: BLE001
    record("VenueRef.model_dump() default emits snake_case keys", False)

# 15. Round-trip camelCase -> model -> camelCase preserves data
try:
    original = VenueRef(
        place_id="ChIJN1t_tDeuEmsRUsoyG83frY4",
        name="Round Trip Venue",
        coordinates=GeoCoordinates(lat=40.7128, lng=-74.0060),
    )
    dumped = original.model_dump(by_alias=True)
    rehydrated = VenueRef.model_validate(dumped)
    record(
        "VenueRef camelCase round-trip preserves all fields",
        rehydrated.place_id == original.place_id
        and rehydrated.venue_id is None
        and rehydrated.name == original.name
        and rehydrated.coordinates.lat == original.coordinates.lat,
    )
except Exception:  # noqa: BLE001
    record("VenueRef camelCase round-trip preserves all fields", False)

print(json.dumps(results))
PYEOF
)
PY_EXIT=$?

if [ $PY_EXIT -ne 0 ]; then
  echo "FAIL: Python smoke harness exited with status $PY_EXIT"
  echo "$OUTPUT"
  exit 1
fi

# Parse JSON result array and feed each entry to check()
while IFS=$'\t' read -r desc result; do
  [ -z "$desc" ] && continue
  check "$desc" "$result"
done < <(echo "$OUTPUT" | .venv/bin/python -c "
import json, sys
data = json.loads(sys.stdin.read())
for desc, result in data:
    print(f'{desc}\t{result}')
")

echo ""
echo "=== Summary: $PASS passed, $FAIL failed ==="

if [ $FAIL -gt 0 ]; then
  exit 1
fi
exit 0
