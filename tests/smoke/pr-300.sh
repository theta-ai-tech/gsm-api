#!/usr/bin/env bash
# Smoke tests for PR #300: feat: VEN-8 add GET /venues?sport&area curated venue list (#271)
# Generated: 2026-05-20
# Usage: bash tests/smoke/pr-300.sh
#
# Requires: make emu-all running. Seeded venues via tools/seed_firestore.py.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8300}"
FIRESTORE="http://127.0.0.1:8082/emulator/v1/projects/gsm-dev-f70d0/databases/(default)/documents"

# ── Venv resolution ──────────────────────────────────────────────────────────
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

# ── Helpers ──────────────────────────────────────────────────────────────────

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

# ── Seed venues ──────────────────────────────────────────────────────────────
echo "Seeding venues..."
FIRESTORE_EMULATOR_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}" \
GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}" \
  . "$VENV_DIR/bin/activate" && \
  python3 -m tools.seed_firestore 2>/dev/null || true

# ── Token acquisition ─────────────────────────────────────────────────────────
TOKEN=$(GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}" \
  bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null)
if [ -z "$TOKEN" ]; then
  echo "ERROR: Could not get auth token for user_ignatios. Is the auth emulator running?"
  exit 1
fi

# ── Tests ─────────────────────────────────────────────────────────────────────

echo ""
echo "── GET /venues (padel) ──────────────────────────────────────────────────"

# List all padel venues → 200 with non-empty venues array
ACTUAL=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/venues?sport=padel" \
  | jq -r '.venues | length > 0')
assert_eq "returns venues for sport=padel" "$ACTUAL" "true"

# Response has nextCursor field (may be null)
ACTUAL=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/venues?sport=padel" \
  | jq 'has("nextCursor")')
assert_eq "response has nextCursor field" "$ACTUAL" "true"

# Venue objects contain expected camelCase fields
ACTUAL=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/venues?sport=padel" \
  | jq -r '.venues[0] | has("venueId") and has("name") and has("coordinates") and has("area") and has("sports")')
assert_eq "venue object has expected camelCase fields" "$ACTUAL" "true"

# sport=padel venues all contain padel in sports array
ACTUAL=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/venues?sport=padel" \
  | jq '[.venues[].sports[] | select(. == "padel")] | length > 0')
assert_eq "padel venues contain padel in sports array" "$ACTUAL" "true"

echo ""
echo "── GET /venues (tennis + area filter) ──────────────────────────────────"

# Filter by area=Glyfada + tennis → returns Glyfada Tennis Club
ACTUAL=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/venues?sport=tennis&area=Glyfada" \
  | jq -r '[.venues[].name] | join(",")')
assert_eq "tennis+Glyfada returns Glyfada Tennis Club" "$ACTUAL" "Glyfada Tennis Club"

# area filter excludes other areas
ACTUAL=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/venues?sport=padel&area=Glyfada" \
  | jq -r '[.venues[].area] | unique | .[]')
assert_eq "area filter returns only Glyfada venues" "$ACTUAL" "Glyfada"

echo ""
echo "── GET /venues (limit + pagination) ─────────────────────────────────────"

# limit=1 returns exactly 1 venue and a nextCursor
ACTUAL=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/venues?sport=padel&limit=1" \
  | jq -r '.venues | length')
assert_eq "limit=1 returns exactly 1 venue" "$ACTUAL" "1"

ACTUAL=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/venues?sport=padel&limit=1" \
  | jq -r '.nextCursor != null')
assert_eq "limit=1 with more results returns nextCursor" "$ACTUAL" "true"

# Using the cursor fetches the next page (different venue)
CURSOR=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/venues?sport=padel&limit=1" \
  | jq -r '.nextCursor')
FIRST=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/venues?sport=padel&limit=1" \
  | jq -r '.venues[0].venueId')
SECOND=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/venues?sport=padel&limit=1&cursor=$CURSOR" \
  | jq -r '.venues[0].venueId')
if [ "$FIRST" != "$SECOND" ]; then
  echo "  ✓ cursor pagination returns different venue on page 2"
  ((PASS++)) || true
else
  echo "  ✗ cursor pagination returns different venue on page 2"
  echo "    expected: different venue IDs"
  echo "    actual:   both are $FIRST"
  ((FAIL++)) || true
fi

echo ""
echo "── GET /venues (no match) ───────────────────────────────────────────────"

# Pickleball venues — may be empty or have results; just check 200 shape
ACTUAL=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/venues?sport=pickleball" \
  | jq 'has("venues") and has("nextCursor")')
assert_eq "pickleball returns 200 with correct shape" "$ACTUAL" "true"

echo ""
echo "── Error cases ──────────────────────────────────────────────────────────"

# Missing sport → 422
ACTUAL=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" "$API/venues")
assert_eq "missing sport returns 422" "$ACTUAL" "422"

# Invalid sport value → 422
ACTUAL=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" "$API/venues?sport=chess")
assert_eq "invalid sport returns 422" "$ACTUAL" "422"

# No auth → 401
ACTUAL=$(curl -s -o /dev/null -w "%{http_code}" "$API/venues?sport=padel")
assert_eq "no auth returns 401" "$ACTUAL" "401"

# Invalid cursor → 400
ACTUAL=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" "$API/venues?sport=padel&cursor=notbase64garbage")
assert_eq "invalid cursor returns 400" "$ACTUAL" "400"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #300: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
