#!/usr/bin/env bash
# Smoke tests for PR #380: feat: North Star edit path — GET /me/north-star +
# client-set progress_pct (#372)
# Generated: 2026-07-08
# Usage: bash tests/smoke/pr-380.sh
#
# Requires: make emu-all running + emulator seeded (make seed-emu).
# The smoke-test skill starts the API.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8000}"
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

firestore_delete_field() {
  # Usage: firestore_delete_field <collection/docId> <field>
  curl -s -X PATCH "$FIRESTORE/$1?updateMask.fieldPaths=$2" \
    -H "Content-Type: application/json" -d '{"fields":{}}' > /dev/null
}

api_put() {
  # Usage: api_put <json-body>
  curl -s -X PUT -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d "$1" "$API/me/north-star"
}

api_get() {
  curl -s -H "Authorization: Bearer $TOKEN" "$API/me/north-star"
}

# ── Token acquisition ───────────────────────────────────────────────────────
TOKEN=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null)
if [ -z "$TOKEN" ]; then
  echo "ERROR: Could not get auth token for user_ignatios. Is the auth emulator running?"
  exit 1
fi

USER_EXISTS=$(curl -s "$FIRESTORE/users/user_ignatios" | jq -r '.fields.uid.stringValue // "missing"')
if [ "$USER_EXISTS" = "missing" ]; then
  echo "ERROR: users/user_ignatios not found in emulator. Run 'make seed-emu' first."
  exit 1
fi

# ── Tests ───────────────────────────────────────────────────────────────────

echo "PR #380 smoke: GET/PUT /me/north-star"

# Setup: clear any pre-existing goal so the run starts from a known state
firestore_delete_field "users/user_ignatios" "northStarGoal"

# Step 1: no auth → 401
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$API/me/north-star")
assert_eq "unauthenticated GET rejected" "$CODE" "401"

# Step 2: GET before any goal is set → 404
CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$API/me/north-star")
assert_eq "GET with no goal returns 404" "$CODE" "404"
DETAIL=$(api_get | jq -r '.detail')
assert_eq "404 detail message" "$DETAIL" "North Star goal not set"

# Step 3: create goal without progress_pct → defaults to 0.0
RESP=$(api_put '{"goal_text":"Reduce double faults by 20%"}')
assert_eq "create without progress → 0" "$(echo "$RESP" | jq -r '.progress_pct')" "0.0"
assert_eq "create echoes goal_text" "$(echo "$RESP" | jq -r '.goal_text')" "Reduce double faults by 20%"

# Step 4: GET after set returns the stored goal
RESP=$(api_get)
assert_eq "GET after set returns goal" "$(echo "$RESP" | jq -r '.goal_text')" "Reduce double faults by 20%"
assert_eq "GET after set progress 0" "$(echo "$RESP" | jq -r '.progress_pct')" "0.0"

# Step 5: PUT with explicit progress_pct persists it
RESP=$(api_put '{"goal_text":"Reduce double faults by 20%","progress_pct":40}')
assert_eq "PUT with progress persists" "$(echo "$RESP" | jq -r '.progress_pct')" "40.0"
assert_eq "GET reflects progress 40" "$(api_get | jq -r '.progress_pct')" "40.0"

# Step 6: text-only update preserves existing progress (the core #372 fix)
RESP=$(api_put '{"goal_text":"Reduce double faults by 30%"}')
assert_eq "text-only update preserves progress" "$(echo "$RESP" | jq -r '.progress_pct')" "40.0"
assert_eq "GET still 40 after text-only update" "$(api_get | jq -r '.progress_pct')" "40.0"
assert_eq "goal_text updated" "$(api_get | jq -r '.goal_text')" "Reduce double faults by 30%"

# Step 7: explicit zero overwrites
RESP=$(api_put '{"goal_text":"Reduce double faults by 30%","progress_pct":0}')
assert_eq "explicit 0 overwrites progress" "$(echo "$RESP" | jq -r '.progress_pct')" "0.0"

# Step 8: boundary + validation
RESP=$(api_put '{"goal_text":"g","progress_pct":100}')
assert_eq "progress 100 accepted" "$(echo "$RESP" | jq -r '.progress_pct')" "100.0"
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"goal_text":"g","progress_pct":101}' "$API/me/north-star")
assert_eq "progress 101 rejected 422" "$CODE" "422"
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X PUT -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{"goal_text":"g","progress_pct":-1}' "$API/me/north-star")
assert_eq "progress -1 rejected 422" "$CODE" "422"

# ── Teardown ────────────────────────────────────────────────────────────────
firestore_delete_field "users/user_ignatios" "northStarGoal"

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #380: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
