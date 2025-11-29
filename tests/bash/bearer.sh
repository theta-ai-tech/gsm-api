#!/usr/bin/env bash
# real_token_integration_test.sh
# Usage:
#   chmod +x real_token_integration_test.sh
#   ./real_token_integration_test.sh \
#     --api-key "<FIREBASE_WEB_API_KEY>" \
#     --email "test@example.com" \
#     --password "StrongPass123!" \
#     [--api-base "http://localhost:8000"]

set -euo pipefail

# -------- Defaults --------
API_BASE="http://localhost:8000"
EXPECT_OWNER_STATUS="200"
EXPECT_NONOWNER_STATUS="403"

# -------- Args --------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-key) API_KEY="${2:-}"; shift 2 ;;
    --email) EMAIL="${2:-}"; shift 2 ;;
    --password) PASSWORD="${2:-}"; shift 2 ;;
    --api-base) API_BASE="${2:-}"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

# -------- Validation --------
if ! command -v jq >/dev/null 2>&1; then
  echo "Error: jq is required (brew install jq | apt-get install jq)" >&2
  exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
  echo "Error: curl is required" >&2
  exit 1
fi

if [[ -z "${API_KEY:-}" || -z "${EMAIL:-}" || -z "${PASSWORD:-}" ]]; then
  echo "Usage: $0 --api-key <FIREBASE_WEB_API_KEY> --email <EMAIL> --password <PASSWORD> [--api-base <URL>]" >&2
  exit 1
fi

echo "API base:        ${API_BASE}"
echo "Firebase API key: (provided)"
echo "Email:           ${EMAIL}"
echo

# -------- Step 1: Sign in to Firebase (Email/Password) --------
echo "Signing in via Firebase REST..."
ID_TOKEN="$(curl -s -X POST \
  "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=${API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"${EMAIL}\",\"password\":\"${PASSWORD}\",\"returnSecureToken\":true}" \
  | jq -r '.idToken')"

if [[ -z "${ID_TOKEN}" || "${ID_TOKEN}" == "null" ]]; then
  echo "Error: failed to obtain ID token. Check API key, email, and password." >&2
  exit 1
fi
echo "Obtained ID token."

# -------- Step 2: Extract uid from JWT payload (base64url decode) --------
# JWT format: header.payload.signature; we decode the payload part.
b64url_decode() {
  # replace URL-safe chars, pad, decode
  local input="${1//-/+}"
  input="${input//_//}"
  local pad=$(( (4 - ${#input} % 4) % 4 ))
  input="${input}$(printf '=%.0s' $(seq 1 $pad))"
  echo -n "$input" | base64 --decode 2>/dev/null
}

PAYLOAD_B64="$(echo -n "${ID_TOKEN}" | cut -d '.' -f2)"
if [[ -z "${PAYLOAD_B64}" ]]; then
  echo "Error: could not parse JWT payload." >&2
  exit 1
fi

PAYLOAD_JSON="$(b64url_decode "${PAYLOAD_B64}")" || {
  echo "Error: failed to base64url-decode JWT payload." >&2
  exit 1
}

TOKEN_UID="$(echo "${PAYLOAD_JSON}" | jq -r '.uid // .sub')"
if [[ -z "${TOKEN_UID}" || "${TOKEN_UID}" == "null" ]]; then
  echo "Error: UID not found in token payload." >&2
  echo "Payload was: ${PAYLOAD_JSON}" >&2
  exit 1
fi
echo "Token UID: ${TOKEN_UID}"
echo

AUTH_HEADER="Authorization: Bearer ${ID_TOKEN}"

# -------- Step 3: Owner request (expect 200) --------
OWNER_URL="${API_BASE}/users/${TOKEN_UID}"
echo "Request (owner)  : GET ${OWNER_URL}"
OWNER_STATUS="$(curl -s -o /tmp/owner_resp.json -w "%{http_code}" -H "${AUTH_HEADER}" "${OWNER_URL}")"
echo "Status (owner)   : ${OWNER_STATUS}"
echo "Body (owner)     :"
cat /tmp/owner_resp.json; echo

if [[ "${OWNER_STATUS}" != "${EXPECT_OWNER_STATUS}" ]]; then
  echo "❌ Expected owner status ${EXPECT_OWNER_STATUS}, got ${OWNER_STATUS}" >&2
  exit 1
else
  echo "✅ Owner request OK"
fi
echo

# -------- Step 4: Non-owner request (expect 403) --------
NONOWNER_URL="${API_BASE}/users/someone_else"
echo "Request (non-own): GET ${NONOWNER_URL}"
NONOWNER_STATUS="$(curl -s -o /tmp/nonowner_resp.json -w "%{http_code}" -H "${AUTH_HEADER}" "${NONOWNER_URL}")"
echo "Status (non-own) : ${NONOWNER_STATUS}"
echo "Body (non-own)   :"
cat /tmp/nonowner_resp.json; echo

if [[ "${NONOWNER_STATUS}" != "${EXPECT_NONOWNER_STATUS}" ]]; then
  echo "❌ Expected non-owner status ${EXPECT_NONOWNER_STATUS}, got ${NONOWNER_STATUS}" >&2
  exit 1
else
  echo "✅ Non-owner request correctly forbidden"
fi

echo
echo "🎉 Integration test completed successfully."
