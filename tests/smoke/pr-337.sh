#!/usr/bin/env bash
# Smoke tests for PR #337: fix: SEC-1 production Firestore security rules — deny-all
# Generated: 2026-06-13
# Usage: bash tests/smoke/pr-337.sh
#
# Requires: make emu-all running (deny-all rules must be active via firestore.rules).
# The API is started automatically by the smoke-test skill on port 8337.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8337}"
FIRESTORE_V1="http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents"

# ── Venv resolution ─────────────────────────────────────────────────────────
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  VENV_DIR="$REPO_ROOT/.venv"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null \
    | awk '/^worktree / {print ; exit}')
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

assert_contains() {
  local name="$1" haystack="$2" needle="$3"
  if echo "$haystack" | grep -q "$needle"; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name"
    echo "    expected to contain: $needle"
    echo "    actual: $haystack"
    ((FAIL++)) || true
  fi
}

# ── Token acquisition ────────────────────────────────────────────────────────
TOKEN=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null)
if [ -z "$TOKEN" ]; then
  echo "ERROR: Could not get auth token for user_ignatios. Is the auth emulator running?"
  exit 1
fi

# ── Tests ────────────────────────────────────────────────────────────────────

echo "Test 1: Deny-all rules — unauthenticated Firestore REST reads return PERMISSION_DENIED"

RESP=$(curl -s "$FIRESTORE_V1/users")
assert_contains "unauthenticated read /users → PERMISSION_DENIED" "$RESP" "PERMISSION_DENIED"

RESP=$(curl -s "$FIRESTORE_V1/users/user_ignatios")
assert_contains "unauthenticated read /users/user_ignatios → PERMISSION_DENIED" "$RESP" "PERMISSION_DENIED"

RESP=$(curl -s "$FIRESTORE_V1/leagues")
assert_contains "unauthenticated read /leagues → PERMISSION_DENIED" "$RESP" "PERMISSION_DENIED"

RESP=$(curl -s "$FIRESTORE_V1/matches")
assert_contains "unauthenticated read /matches → PERMISSION_DENIED" "$RESP" "PERMISSION_DENIED"

echo ""
echo "Test 2: Verification script — 6 collections all PERMISSION_DENIED"

VERIFY_OUT=$(bash "$REPO_ROOT/scripts/verify_firestore_rules.sh" 2>&1)
assert_contains "verify_firestore_rules.sh exits 0" "$VERIFY_OUT" "6 passed, 0 failed"

echo ""
echo "Test 3: API continues to work (Admin SDK bypasses security rules)"

STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$API/health")
assert_eq "GET /health → 200" "$STATUS" "200"

STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" "$API/me")
assert_eq "GET /me → 200 (Admin SDK reads Firestore despite deny-all)" "$STATUS" "200"

echo ""
echo "Test 4: firebase.smoke.json exists and references firestore.rules.dev"

SMOKE_RULES=$(. "$VENV_DIR/bin/activate" && python3 -c "
import json, sys
with open('$REPO_ROOT/firebase.smoke.json') as f:
    cfg = json.load(f)
print(cfg.get('firestore', {}).get('rules', 'MISSING'))
" 2>/dev/null)
assert_eq "firebase.smoke.json.firestore.rules = firestore.rules.dev" "$SMOKE_RULES" "firestore.rules.dev"

PROD_RULES=$(. "$VENV_DIR/bin/activate" && python3 -c "
import json
with open('$REPO_ROOT/firebase.json') as f:
    cfg = json.load(f)
print(cfg.get('firestore', {}).get('rules', 'MISSING'))
" 2>/dev/null)
assert_eq "firebase.json.firestore.rules = firestore.rules" "$PROD_RULES" "firestore.rules"

echo ""
echo "Test 5: firestore.rules contains deny-all (if false)"

RULES_CONTENT=$(cat "$REPO_ROOT/firestore.rules")
assert_contains "firestore.rules contains 'if false'" "$RULES_CONTENT" "if false"
DENY_CHECK=$(echo "$RULES_CONTENT" | grep -c "if true" || true)
assert_eq "firestore.rules does NOT contain 'if true'" "$DENY_CHECK" "0"

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #337: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
