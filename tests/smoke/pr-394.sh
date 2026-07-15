#!/usr/bin/env bash
# Smoke tests for PR #394: feat: venue lifecycle status live/hidden/unverified (#392)
# Generated: 2026-07-13
# Usage: bash tests/smoke/pr-394.sh
#
# Requires: make emu-all running. The smoke-test skill starts the API.
#
# Covers the manual test plan from the PR body:
#   - visible statuses (live/unverified) are returned by GET /venues with the
#     status field serialized
#   - hidden venues (non-live area) are excluded from GET /venues
#   - tools/set_area_status.py flips hidden -> live and the venues appear
#   - the flip does NOT touch unverified rows in the same area
# GET /venues/search is not exercised: the emulator has no Google Places API
# key, so the endpoint returns 503 by design; the hidden-venue exclusion is
# enforced in VenueRepo.search_by_name_prefix, covered by unit + integration
# tests.
#
# Test venues use sport "pickleball" (unused by seeded data) and the
# smoketest394_ id prefix so assertions are isolated and teardown is safe.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8000}"
FIRESTORE="http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents"

# ── Venv resolution ─────────────────────────────────────────────────────────
# `.venv` only lives in the main checkout, never in git worktrees. When the
# script runs from a worktree, fall back to the main checkout's venv via
# `git worktree list` (first listed worktree is the main checkout). Export
# PYTHONPATH so `import app` resolves to the *current* tree's source rather
# than the editable install's target inside the main checkout.
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  VENV_DIR="$REPO_ROOT/.venv"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null \
    | awk '/^worktree / {print $2; exit}')
  VENV_DIR="$MAIN_WT/.venv"
fi
if [ ! -f "$VENV_DIR/bin/activate" ]; then
  echo "ABORT: no venv found at $VENV_DIR (or $REPO_ROOT/.venv). Run 'make venv && make install' in the main checkout."
  exit 1
fi
export PYTHONPATH="$REPO_ROOT/api${PYTHONPATH:+:$PYTHONPATH}"

# ── Helpers ────────────────────────────────────────────────────────────────

assert_eq() {
  local name="$1" actual="$2" expected="$3"
  if [ "$actual" = "$expected" ]; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name"
    echo "    expected: $expected"
    echo "    actual:   $actual"
    ((FAIL++)) || true
  fi
}

put_venue() {
  # Usage: put_venue <docId> <name> <area> <status>
  local doc_id="$1" name="$2" area="$3" status="$4"
  curl -s -X PATCH "$FIRESTORE/venues/$doc_id" \
    -H "Content-Type: application/json" \
    -d "{\"fields\":{
          \"name\":{\"stringValue\":\"$name\"},
          \"coordinates\":{\"mapValue\":{\"fields\":{
            \"lat\":{\"doubleValue\":37.9},\"lng\":{\"doubleValue\":23.7}}}},
          \"area\":{\"stringValue\":\"$area\"},
          \"sports\":{\"arrayValue\":{\"values\":[{\"stringValue\":\"pickleball\"}]}},
          \"courtCount\":{\"integerValue\":\"2\"},
          \"status\":{\"stringValue\":\"$status\"}
        }}" > /dev/null
}

delete_venue() {
  curl -s -X DELETE "$FIRESTORE/venues/$1" > /dev/null
}

list_pickleball() {
  curl -s -H "Authorization: Bearer $TOKEN" "$API/venues?sport=pickleball&limit=100"
}

# status of one venue in the listing, or "absent"
venue_status_in_listing() {
  list_pickleball | jq -r --arg id "$1" \
    '(.venues[] | select(.venueId == $id) | .status) // "absent"'
}

# ── Token acquisition ───────────────────────────────────────────────────────
TOKEN=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null)
if [ -z "$TOKEN" ]; then
  echo "ERROR: Could not get auth token for user_ignatios. Is the auth emulator running?"
  exit 1
fi

# ── Setup: seed a live, an unverified (live area) and two hidden (non-live area) venues
put_venue "smoketest394_live"       "Smoketest Live Club"       "athens"          "live"
put_venue "smoketest394_unverified" "Smoketest Unverified Club" "athens"          "unverified"
put_venue "smoketest394_hidden"     "Smoketest Lavrio Club"     "smoketestlavrio" "hidden"
put_venue "smoketest394_unv_lavrio" "Smoketest Lavrio Unv Club" "smoketestlavrio" "unverified"

# ── Tests ───────────────────────────────────────────────────────────────────

# Step 4a: live venue is returned with status serialized
assert_eq "GET /venues returns live venue with status=live" \
  "$(venue_status_in_listing smoketest394_live)" "live"

# Step 4b: unverified venue IS returned, payload carries status=unverified
assert_eq "GET /venues returns unverified venue with status=unverified" \
  "$(venue_status_in_listing smoketest394_unverified)" "unverified"

# Step 4c: hidden venue is excluded from the listing
assert_eq "GET /venues excludes hidden venue" \
  "$(venue_status_in_listing smoketest394_hidden)" "absent"

# Step 6: launch the region — flip hidden -> live for area smoketestlavrio
(
  cd "$REPO_ROOT" \
    && . "$VENV_DIR/bin/activate" \
    && FIRESTORE_EMULATOR_HOST=127.0.0.1:8082 GOOGLE_CLOUD_PROJECT=gsm-dev-f70d0 \
      python -m tools.set_area_status \
        --area=smoketestlavrio --from=hidden --to=live --env=emu
) > /dev/null 2>&1
assert_eq "flip tool ran" "$?" "0"

# Step 7: previously hidden venue now appears as live
assert_eq "after flip, venue appears with status=live" \
  "$(venue_status_in_listing smoketest394_hidden)" "live"

# Flip must not touch unverified rows in the same area
UNV_DOC_STATUS=$(curl -s "$FIRESTORE/venues/smoketest394_unv_lavrio" \
  | jq -r '.fields.status.stringValue // "null"')
assert_eq "flip leaves unverified row in same area untouched" \
  "$UNV_DOC_STATUS" "unverified"

# Step 8: ingest invariant — a non-live-area row without status=hidden aborts
INGEST_ERR=$(
  cd "$REPO_ROOT" \
    && . "$VENV_DIR/bin/activate" \
    && FIRESTORE_EMULATOR_HOST=127.0.0.1:8082 GOOGLE_CLOUD_PROJECT=gsm-dev-f70d0 \
      python - <<'PYEOF' 2>&1
from tools.ingest_venues import CheckpointValidationError, validate_rows

row = {
    "venueId": "smoketest394_invariant",
    "name": "Champion Padel Club Lavrio",
    "coordinates": {"lat": 37.71, "lng": 24.05},
    "area": "lavrio",
    "sports": ["padel"],
    "courtCount": 5,
}
try:
    validate_rows([row])
    print("NO_ERROR")
except CheckpointValidationError as exc:
    print(exc)
PYEOF
)
case "$INGEST_ERR" in
  *'is not live; row must set status="hidden"'*)
    assert_eq "ingest rejects non-live area without status=hidden" "ok" "ok" ;;
  *)
    assert_eq "ingest rejects non-live area without status=hidden" "$INGEST_ERR" \
      "…is not live; row must set status=\"hidden\"…" ;;
esac

# ── Teardown ────────────────────────────────────────────────────────────────
delete_venue "smoketest394_live"
delete_venue "smoketest394_unverified"
delete_venue "smoketest394_hidden"
delete_venue "smoketest394_unv_lavrio"

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #394: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
