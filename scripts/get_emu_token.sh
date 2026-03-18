#!/usr/bin/env bash
# =============================================================================
# get_emu_token.sh — Obtain a Firebase Auth emulator ID token for manual testing
#
# Creates (or re-uses) a user in the Auth emulator with a SPECIFIC UID that
# matches the seeded Firestore data, then prints a ready-to-use Bearer token.
#
# Prerequisites:
#   make emu-all            — Firestore + Auth emulators must be running
#   make seed-emu           — seed sample Firestore data (user_1, user_2, ...)
#
# Usage:
#   ./scripts/get_emu_token.sh                         # defaults: uid=user_1
#   ./scripts/get_emu_token.sh user_2                  # sign in as user_2
#   ./scripts/get_emu_token.sh user_1 my@email.com     # custom email
#
# Positional args:
#   $1  TARGET_UID  — the Firestore doc ID to authenticate as (default: user_1)
#   $2  EMAIL       — email to register (default: <uid>@gsm.local)
#   $3  PASSWORD    — password (default: test_pass_123)
#
# Optional env overrides:
#   FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099
#   GOOGLE_CLOUD_PROJECT=gsm-dev-f70d0
# =============================================================================
set -euo pipefail

AUTH_EMU="${FIREBASE_AUTH_EMULATOR_HOST:-127.0.0.1:9099}"
AUTH_BASE="http://${AUTH_EMU}/identitytoolkit.googleapis.com/v1"
FAKE_API_KEY="fake-api-key"

TARGET_UID="${1:-user_1}"
EMAIL="${2:-${TARGET_UID}@gsm.local}"
PASSWORD="${3:-test_pass_123}"

# Check jq is available
if ! command -v jq &> /dev/null; then
  echo "Error: jq is required. Install with: brew install jq" >&2
  exit 1
fi

# --- Step 1: ensure Auth emulator user exists with the correct UID -----------
# The emulator accepts signUp with a specific localId when the request carries
# "Authorization: Bearer owner" (admin bypass). Idempotent — silently ignore
# the error if the user already exists.
curl -s --max-time 10 -X POST \
  "${AUTH_BASE}/accounts:signUp?key=${FAKE_API_KEY}" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer owner" \
  -d "{\"localId\":\"${TARGET_UID}\",\"email\":\"${EMAIL}\",\"password\":\"${PASSWORD}\"}" \
  > /dev/null || true

# --- Step 2: sign in to obtain the ID token ----------------------------------
RESP=$(curl -s --max-time 10 -X POST \
  "${AUTH_BASE}/accounts:signInWithPassword?key=${FAKE_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"${EMAIL}\",\"password\":\"${PASSWORD}\",\"returnSecureToken\":true}" \
  || echo "{}")

TOKEN=$(echo "$RESP" | jq -r '.idToken // empty' 2>/dev/null || true)

if [[ -z "$TOKEN" || "$TOKEN" == "null" ]]; then
  echo "Error: failed to obtain a token from the Auth emulator at ${AUTH_EMU}" >&2
  echo "Make sure 'make emu-all' is running first." >&2
  echo "Raw response: ${RESP}" >&2
  exit 1
fi

RETURNED_UID=$(echo "$RESP" | jq -r '.localId // empty')

echo ""
echo "Auth emulator : ${AUTH_EMU}"
echo "Email         : ${EMAIL}"
echo "UID           : ${RETURNED_UID}"
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
