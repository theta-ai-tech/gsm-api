#!/usr/bin/env bash
# Smoke tests for PR #398: fix: classify onboarding config errors as 500, not 400 (#396)
# Generated: 2026-07-20
# Usage: bash tests/smoke/pr-398.sh
#
# Requires: make emu-all running. The smoke-test skill starts the API.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8000}"
FIRESTORE_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}"
GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}"
FIRESTORE="http://${FIRESTORE_HOST}/v1/projects/${GOOGLE_CLOUD_PROJECT}/databases/(default)/documents"

# ── Venv resolution ─────────────────────────────────────────────────────────
# `.venv` only lives in the main checkout, never in git worktrees. When the
# script runs from a worktree, fall back to the main worktree's path via
# `git worktree list`. Then export PYTHONPATH so `import app` resolves to the
# *current* tree's source rather than the editable install's target inside
# the main checkout — otherwise the script would silently exercise main's code.
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

firestore_delete() {
  # Usage: firestore_delete <collection/docId>
  curl -s -X DELETE "$FIRESTORE/$1" > /dev/null
}

# Delete config/tiers via the real TierConfigRepo path (so this exactly
# matches how the router/service reads it) and reset the in-process cache.
delete_tier_config() {
  (
    cd "$REPO_ROOT" && \
    . "$VENV_DIR/bin/activate" && \
    export FIRESTORE_EMULATOR_HOST="$FIRESTORE_HOST" && \
    export GOOGLE_CLOUD_PROJECT="$GOOGLE_CLOUD_PROJECT" && \
    python3 -c "
from google.cloud import firestore
db = firestore.Client(project='$GOOGLE_CLOUD_PROJECT')
db.collection('config').document('tiers').delete()
"
  )
}

# Restore config/tiers to the same seed shape used by
# tests/integration/test_onboarding_integration.py::_seed_tier_config
# and tools/seed_mapping.py, so subsequent onboarding calls (and other
# smoke/integration runs) see a healthy config again.
restore_tier_config() {
  (
    cd "$REPO_ROOT" && \
    . "$VENV_DIR/bin/activate" && \
    export FIRESTORE_EMULATOR_HOST="$FIRESTORE_HOST" && \
    export GOOGLE_CLOUD_PROJECT="$GOOGLE_CLOUD_PROJECT" && \
    python3 -c "
from datetime import datetime, timezone
from google.cloud import firestore
db = firestore.Client(project='$GOOGLE_CLOUD_PROJECT')
db.collection('config').document('tiers').set({
    'thresholds': [
        {'tier': 'amateur', 'minPts': 1000, 'maxPts': 1999, 'label': 'Amateur', 'color': '#8B8B8B'},
        {'tier': 'intermediate', 'minPts': 2000, 'maxPts': 2999, 'label': 'Intermediate', 'color': '#00A3CC'},
        {'tier': 'advanced', 'minPts': 3000, 'maxPts': 3999, 'label': 'Advanced', 'color': '#BFFF00'},
        {'tier': 'competitive', 'minPts': 4000, 'maxPts': None, 'label': 'Competitive', 'color': '#FF6B35'},
    ],
    'version': 1,
    'updatedAt': datetime(2026, 1, 1, tzinfo=timezone.utc),
})
"
  )
}

delete_user_doc() {
  # Usage: delete_user_doc <uid>
  firestore_delete "users/$1"
}

# ── Token acquisition ───────────────────────────────────────────────────────
UID_HAPPY="smoke_onboard_398_happy"
UID_CONFIG="smoke_onboard_398_no_config"

TOKEN_HAPPY=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" "$UID_HAPPY" -t 2>/dev/null)
if [ -z "$TOKEN_HAPPY" ]; then
  echo "ERROR: Could not get auth token for $UID_HAPPY. Is the auth emulator running?"
  exit 1
fi

TOKEN_CONFIG=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" "$UID_CONFIG" -t 2>/dev/null)
if [ -z "$TOKEN_CONFIG" ]; then
  echo "ERROR: Could not get auth token for $UID_CONFIG. Is the auth emulator running?"
  exit 1
fi

PAYLOAD='{"name":"Smoke Test User","sports":["padel"],"levels":{"padel":"intermediate"},"area":1}'

# ── Cleanup any leftovers from a previous run ───────────────────────────────
delete_user_doc "$UID_HAPPY"
delete_user_doc "$UID_CONFIG"

# ── Tests ───────────────────────────────────────────────────────────────────

# Step 1: happy path still returns 201 (unchanged by this PR)
ACTUAL=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API/me" \
  -H "Authorization: Bearer $TOKEN_HAPPY" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")
assert_eq "happy path onboarding returns 201" "$ACTUAL" "201"

# Step 2: re-POST as the same user still returns 409 (unchanged by this PR)
ACTUAL=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API/me" \
  -H "Authorization: Bearer $TOKEN_HAPPY" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")
assert_eq "duplicate onboarding returns 409" "$ACTUAL" "409"

# Step 3: missing config/tiers now returns 500, not 400 (the fix)
delete_tier_config
ACTUAL=$(curl -s -X POST "$API/me" \
  -H "Authorization: Bearer $TOKEN_CONFIG" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")
ACTUAL_STATUS=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API/me" \
  -H "Authorization: Bearer $TOKEN_CONFIG" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")
assert_eq "missing config/tiers returns 500" "$ACTUAL_STATUS" "500"

ACTUAL_DETAIL=$(echo "$ACTUAL" | jq -r '.detail // "null"')
case "$ACTUAL_DETAIL" in
  *"Tier config not found"*) DETAIL_OK="match" ;;
  *) DETAIL_OK="no-match: $ACTUAL_DETAIL" ;;
esac
assert_eq "500 detail mentions missing tier config" "$DETAIL_OK" "match"

# ── Teardown ────────────────────────────────────────────────────────────────
restore_tier_config
delete_user_doc "$UID_HAPPY"
delete_user_doc "$UID_CONFIG"

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #398: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
