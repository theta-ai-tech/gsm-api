#!/usr/bin/env bash
# =============================================================================
# get_emu_token.sh — Obtain a Firebase Auth emulator ID token for manual testing
#
# Signs up (or re-uses) a test user in the Auth emulator and prints:
#   - The user's UID
#   - A ready-to-use  Authorization: Bearer <token>  header value
#
# Prerequisites:
#   make emu-all            — Firestore + Auth emulators must be running
#
# Usage:
#   ./scripts/get_emu_token.sh
#   ./scripts/get_emu_token.sh test.user@gsm.local my_password
#
# Optional env overrides:
#   FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099
#   GOOGLE_CLOUD_PROJECT=gsm-dev-f70d0
# =============================================================================
set -euo pipefail

AUTH_EMU="${FIREBASE_AUTH_EMULATOR_HOST:-127.0.0.1:9099}"
AUTH_BASE="http://${AUTH_EMU}/identitytoolkit.googleapis.com/v1"
FAKE_API_KEY="fake-api-key"

EMAIL="${1:-test.lab@gsm.local}"
PASSWORD="${2:-test_pass_123}"

# Check jq is available
if ! command -v jq &> /dev/null; then
  echo "Error: jq is required. Install with: brew install jq" >&2
  exit 1
fi

# Try to sign in first (user may already exist from a previous run)
RESP=$(curl -s --max-time 10 -X POST \
  "${AUTH_BASE}/accounts:signInWithPassword?key=${FAKE_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"${EMAIL}\",\"password\":\"${PASSWORD}\",\"returnSecureToken\":true}" \
  || echo "{}")

TOKEN=$(echo "$RESP" | jq -r '.idToken // empty' 2>/dev/null || true)

# If sign-in failed (user doesn't exist yet), sign up instead
if [[ -z "$TOKEN" || "$TOKEN" == "null" ]]; then
  RESP=$(curl -s --max-time 10 -X POST \
    "${AUTH_BASE}/accounts:signUp?key=${FAKE_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"${EMAIL}\",\"password\":\"${PASSWORD}\",\"returnSecureToken\":true}" \
    || echo "{}")

  TOKEN=$(echo "$RESP" | jq -r '.idToken // empty' 2>/dev/null || true)
fi

if [[ -z "$TOKEN" || "$TOKEN" == "null" ]]; then
  echo "Error: failed to obtain a token from the Auth emulator at ${AUTH_EMU}" >&2
  echo "Make sure 'make emu-all' is running first." >&2
  echo "Raw response: ${RESP}" >&2
  exit 1
fi

UID=$(echo "$RESP" | jq -r '.localId // empty')

echo ""
echo "Auth emulator : ${AUTH_EMU}"
echo "Email         : ${EMAIL}"
echo "UID           : ${UID}"
echo ""
echo "Authorization header (copy-paste into curl -H):"
echo ""
echo "  Authorization: Bearer ${TOKEN}"
echo ""
echo "Quick curl example:"
echo ""
echo "  curl -s http://127.0.0.1:8000/me/lab/dashboard/tennis \\"
echo "    -H 'Authorization: Bearer ${TOKEN}' | jq ."
echo ""
