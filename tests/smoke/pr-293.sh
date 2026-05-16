#!/usr/bin/env bash
# Smoke tests for PR #293: feat: LG-1 add league browse fields to schema (#248)
# Generated: 2026-05-16
# Usage: bash tests/smoke/pr-293.sh
#
# LG-1 is schema-only — no GET /leagues/{id} endpoint exists yet (that's LG-8).
# Tests verify the seed correctly writes new fields to Firestore by reading
# documents directly via the Firestore emulator REST API.
#
# Requires: make emu-all running + seed loaded.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FIRESTORE="http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents"

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

# ── Venv resolution ─────────────────────────────────────────────────────────
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  VENV_DIR="$REPO_ROOT/.venv"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null \
    | awk '/^worktree / {print $2; exit}')
  VENV_DIR="${MAIN_WT:-$REPO_ROOT}/.venv"
fi
export PYTHONPATH="$REPO_ROOT/api${PYTHONPATH:+:$PYTHONPATH}"

# ── Seed the emulator ───────────────────────────────────────────────────────
echo "Seeding emulator..."
(cd "$REPO_ROOT" && . "$VENV_DIR/bin/activate" && \
  FIRESTORE_EMULATOR_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}" \
  GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}" \
  python3 tools/seed_data.py) > /dev/null 2>&1

# ── Tests — read league docs directly from Firestore emulator ───────────────
# GET /leagues/{id} does not exist in this PR (added in LG-8).
# We verify the seed round-trip: new fields are persisted with correct values.

echo ""
echo "── padel-local-2025: new browse fields ──────────────────────────────────"

PADEL=$(curl -s "$FIRESTORE/leagues/padel-local-2025")

ACTUAL=$(echo "$PADEL" | jq -r '.fields.region.stringValue // "null"')
assert_eq "region=athens" "$ACTUAL" "athens"

ACTUAL=$(echo "$PADEL" | jq -r '.fields.maxPlayers.integerValue // "null"')
assert_eq "maxPlayers=12" "$ACTUAL" "12"

ACTUAL=$(echo "$PADEL" | jq -r '.fields.currentPlayers.integerValue // "null"')
assert_eq "currentPlayers=3" "$ACTUAL" "3"

ACTUAL=$(echo "$PADEL" | jq -r '.fields.tier.stringValue // "null"')
assert_eq "tier=intermediate" "$ACTUAL" "intermediate"

echo ""
echo "── tennis-local-2025: OPEN status + browse fields ───────────────────────"

TENNIS=$(curl -s "$FIRESTORE/leagues/tennis-local-2025")

ACTUAL=$(echo "$TENNIS" | jq -r '.fields.status.stringValue // "null"')
assert_eq "status=open" "$ACTUAL" "open"

ACTUAL=$(echo "$TENNIS" | jq -r '.fields.region.stringValue // "null"')
assert_eq "region=thessaloniki" "$ACTUAL" "thessaloniki"

ACTUAL=$(echo "$TENNIS" | jq -r '.fields.maxPlayers.integerValue // "null"')
assert_eq "maxPlayers=16" "$ACTUAL" "16"

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #293: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
