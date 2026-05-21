#!/usr/bin/env bash
# Smoke tests for PR #303: feat: LG-13 seed LeagueMember docs and fix currentPlayers counts (#260)
# Generated: 2026-05-20
# Usage: bash tests/smoke/pr-303.sh
#
# Requires: make emu-all running. Seeds the emulator then verifies Firestore state.
# No API server needed — tests query the Firestore emulator REST API directly.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FIRESTORE_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}"
FIRESTORE="http://${FIRESTORE_HOST}/v1/projects/gsm-dev-f70d0/databases/(default)/documents"

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

firestore_get() {
  curl -sf "$FIRESTORE/$1" 2>/dev/null
}

firestore_list() {
  curl -sf "$FIRESTORE/$1" 2>/dev/null
}

# ── Preflight: emulator reachable ──────────────────────────────────────────
if ! curl -sf "http://${FIRESTORE_HOST}/" >/dev/null 2>&1; then
  echo "ABORT: Firestore emulator not reachable at ${FIRESTORE_HOST}. Run 'make emu-all' first."
  exit 1
fi

# ── Seed the emulator ──────────────────────────────────────────────────────
echo "Seeding emulator..."
# Resolve venv (lives in main checkout, not worktrees)
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  VENV_DIR="$REPO_ROOT/.venv"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null | awk '/^worktree /{print $2; exit}')
  VENV_DIR="${MAIN_WT}/.venv"
fi
FIRESTORE_EMULATOR_HOST="$FIRESTORE_HOST" \
  GOOGLE_CLOUD_PROJECT=gsm-dev-f70d0 \
  PYTHONPATH="$REPO_ROOT/api:$REPO_ROOT" \
  "$VENV_DIR/bin/python" "$REPO_ROOT/tools/seed_firestore.py" --env emu
echo ""

# ── Tests: padel-local-2025 members ───────────────────────────────────────
echo "padel-local-2025 members:"

# 3 member docs exist
PADEL_MEMBERS=$(firestore_list "leagues/padel-local-2025/members" | jq -r '.documents | length' 2>/dev/null || echo "0")
assert_eq "padel-local-2025 has 3 seeded members" "$PADEL_MEMBERS" "3"

# ignatios is admin
IGNATIOS_ROLE=$(firestore_get "leagues/padel-local-2025/members/user_ignatios" | jq -r '.fields.role.stringValue' 2>/dev/null || echo "null")
assert_eq "user_ignatios is admin of padel league" "$IGNATIOS_ROLE" "admin"

# alice is player
ALICE_PADEL_ROLE=$(firestore_get "leagues/padel-local-2025/members/user_alice" | jq -r '.fields.role.stringValue' 2>/dev/null || echo "null")
assert_eq "user_alice is player of padel league" "$ALICE_PADEL_ROLE" "player"

# bob is player
BOB_ROLE=$(firestore_get "leagues/padel-local-2025/members/user_bob" | jq -r '.fields.role.stringValue' 2>/dev/null || echo "null")
assert_eq "user_bob is player of padel league" "$BOB_ROLE" "player"

# all members are active
PADEL_ACTIVE=$(firestore_list "leagues/padel-local-2025/members" | jq -r '[.documents[].fields.status.stringValue] | map(select(. == "active")) | length' 2>/dev/null || echo "0")
assert_eq "all padel-local-2025 members are active" "$PADEL_ACTIVE" "3"

# currentPlayers on league doc = 3
PADEL_CURRENT=$(firestore_get "leagues/padel-local-2025" | jq -r '.fields.currentPlayers.integerValue' 2>/dev/null || echo "null")
assert_eq "padel-local-2025 currentPlayers = 3" "$PADEL_CURRENT" "3"

echo ""
echo "tennis-local-2025 members:"

# 2 member docs exist
TENNIS_LOCAL_MEMBERS=$(firestore_list "leagues/tennis-local-2025/members" | jq -r '.documents | length' 2>/dev/null || echo "0")
assert_eq "tennis-local-2025 has 2 seeded members" "$TENNIS_LOCAL_MEMBERS" "2"

# alice is admin
ALICE_TENNIS_ROLE=$(firestore_get "leagues/tennis-local-2025/members/user_alice" | jq -r '.fields.role.stringValue' 2>/dev/null || echo "null")
assert_eq "user_alice is admin of tennis-local league" "$ALICE_TENNIS_ROLE" "admin"

# ignatios is player
IGNATIOS_TENNIS_ROLE=$(firestore_get "leagues/tennis-local-2025/members/user_ignatios" | jq -r '.fields.role.stringValue' 2>/dev/null || echo "null")
assert_eq "user_ignatios is player of tennis-local league" "$IGNATIOS_TENNIS_ROLE" "player"

# currentPlayers on league doc = 2
TENNIS_LOCAL_CURRENT=$(firestore_get "leagues/tennis-local-2025" | jq -r '.fields.currentPlayers.integerValue' 2>/dev/null || echo "null")
assert_eq "tennis-local-2025 currentPlayers = 2" "$TENNIS_LOCAL_CURRENT" "2"

echo ""
echo "tennis-completed-2024 members:"

# 2 member docs exist
TENNIS_COMPLETED_MEMBERS=$(firestore_list "leagues/tennis-completed-2024/members" | jq -r '.documents | length' 2>/dev/null || echo "0")
assert_eq "tennis-completed-2024 has 2 seeded members" "$TENNIS_COMPLETED_MEMBERS" "2"

# alice is admin
ALICE_COMPLETED_ROLE=$(firestore_get "leagues/tennis-completed-2024/members/user_alice" | jq -r '.fields.role.stringValue' 2>/dev/null || echo "null")
assert_eq "user_alice is admin of tennis-completed league" "$ALICE_COMPLETED_ROLE" "admin"

# ignatios is player
IGNATIOS_COMPLETED_ROLE=$(firestore_get "leagues/tennis-completed-2024/members/user_ignatios" | jq -r '.fields.role.stringValue' 2>/dev/null || echo "null")
assert_eq "user_ignatios is player of tennis-completed league" "$IGNATIOS_COMPLETED_ROLE" "player"

# currentPlayers on league doc = 2
TENNIS_COMPLETED_CURRENT=$(firestore_get "leagues/tennis-completed-2024" | jq -r '.fields.currentPlayers.integerValue' 2>/dev/null || echo "null")
assert_eq "tennis-completed-2024 currentPlayers = 2" "$TENNIS_COMPLETED_CURRENT" "2"

echo ""
echo "league doc fields (new fields present):"

# Verify all 6 new fields present on padel league
PADEL_REGION=$(firestore_get "leagues/padel-local-2025" | jq -r '.fields.region.stringValue' 2>/dev/null || echo "null")
assert_eq "padel-local-2025 has region field" "$PADEL_REGION" "athens"

PADEL_TIER=$(firestore_get "leagues/padel-local-2025" | jq -r '.fields.tier.stringValue' 2>/dev/null || echo "null")
assert_eq "padel-local-2025 has tier field" "$PADEL_TIER" "intermediate"

PADEL_MAX=$(firestore_get "leagues/padel-local-2025" | jq -r '.fields.maxPlayers.integerValue' 2>/dev/null || echo "null")
assert_eq "padel-local-2025 has maxPlayers field" "$PADEL_MAX" "12"

# ── Summary ────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #303: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
