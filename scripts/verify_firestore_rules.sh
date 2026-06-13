#!/usr/bin/env bash
# Verify deny-all Firestore security rules via the emulator REST API.
# The emulator enforces security rules for /v1/... REST calls.
# Requires: make emu-all running.

set -euo pipefail

FIRESTORE="http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents"
PASS=0
FAIL=0

assert_permission_denied() {
  local name="$1" url="$2"
  local response
  response=$(curl -s "$url")
  if echo "$response" | grep -q "PERMISSION_DENIED"; then
    echo "  ✓ $name: PERMISSION_DENIED (rules working)"
    ((PASS++)) || true
  else
    echo "  ✗ $name: expected PERMISSION_DENIED, got: $response"
    ((FAIL++)) || true
  fi
}

echo "Verifying deny-all Firestore security rules..."
echo ""

assert_permission_denied "unauthenticated read users" "$FIRESTORE/users"
assert_permission_denied "unauthenticated read users/user_ignatios" "$FIRESTORE/users/user_ignatios"
assert_permission_denied "unauthenticated read matches" "$FIRESTORE/matches"
assert_permission_denied "unauthenticated read leagues" "$FIRESTORE/leagues"
assert_permission_denied "unauthenticated read broadcasts" "$FIRESTORE/broadcasts"
assert_permission_denied "unauthenticated read offers" "$FIRESTORE/offers"

echo ""
echo "Rule verification: $PASS passed, $FAIL failed"
echo ""
echo "Note: The API (Admin SDK) bypasses these rules and continues to work normally."
echo "      Integration tests (google.cloud.firestore.Client) also bypass rules."
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
