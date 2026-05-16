#!/usr/bin/env bash
# Smoke tests for PR #293: feat: LG-1 add league browse fields to schema (#248)
# Generated: 2026-05-16
# Usage: bash tests/smoke/pr-293.sh
#
# Requires: make emu-all running + seed loaded. The smoke-test skill starts the API.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8293}"
FIRESTORE="http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents"

# ── Venv resolution ─────────────────────────────────────────────────────────
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  VENV_DIR="$REPO_ROOT/.venv"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null \
    | awk '/^worktree / {print $2; exit}')
  VENV_DIR="$MAIN_WT/.venv"
fi
if [ ! -f "$VENV_DIR/bin/activate" ]; then
  echo "ABORT: no venv found at $VENV_DIR. Run 'make venv && make install' in the main checkout."
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

# ── Seed the emulator ───────────────────────────────────────────────────────
echo "Seeding emulator..."
(cd "$REPO_ROOT" && . "$VENV_DIR/bin/activate" && \
  FIRESTORE_EMULATOR_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}" \
  GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}" \
  python3 tools/seed_data.py) > /dev/null 2>&1 || true

# ── Token acquisition ───────────────────────────────────────────────────────
TOKEN=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null)
if [ -z "$TOKEN" ]; then
  echo "ERROR: Could not get auth token for user_ignatios. Is the auth emulator running?"
  exit 1
fi

# ── Tests ───────────────────────────────────────────────────────────────────

echo ""
echo "── Padel league: new browse fields ─────────────────────────────────────"

PADEL=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/leagues/padel-local-2025")

ACTUAL=$(echo "$PADEL" | jq -r '.region // "null"')
assert_eq "padel-local-2025: region=athens" "$ACTUAL" "athens"

ACTUAL=$(echo "$PADEL" | jq -r '.max_players // "null"')
assert_eq "padel-local-2025: max_players=12" "$ACTUAL" "12"

ACTUAL=$(echo "$PADEL" | jq -r '.current_players // "null"')
assert_eq "padel-local-2025: current_players=3" "$ACTUAL" "3"

ACTUAL=$(echo "$PADEL" | jq -r '.tier // "null"')
assert_eq "padel-local-2025: tier=intermediate" "$ACTUAL" "intermediate"

echo ""
echo "── Tennis league: OPEN status + browse fields ──────────────────────────"

TENNIS=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/leagues/tennis-local-2025")

ACTUAL=$(echo "$TENNIS" | jq -r '.status // "null"')
assert_eq "tennis-local-2025: status=open" "$ACTUAL" "open"

ACTUAL=$(echo "$TENNIS" | jq -r '.region // "null"')
assert_eq "tennis-local-2025: region=thessaloniki" "$ACTUAL" "thessaloniki"

ACTUAL=$(echo "$TENNIS" | jq -r '.max_players // "null"')
assert_eq "tennis-local-2025: max_players=16" "$ACTUAL" "16"

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #293: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
