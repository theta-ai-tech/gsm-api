#!/usr/bin/env bash
# Smoke tests for PR #354 — PUSH-2: device token registration endpoints (#344)
#   POST /me/device-tokens   (idempotent upsert, 204)
#   DELETE /me/device-tokens (no-op-safe remove, 204)
#
# Two layers:
#   Layer A (always runs): route wiring + auth enforcement. Needs only the worktree
#                          API running on $API (no auth emulator required).
#   Layer B (conditional): full authed upsert/dedupe/delete flow. Runs only when the
#                          Auth emulator (127.0.0.1:9099) is up and a token can be minted.
#
# Prereqs:
#   Layer A: API started from THIS worktree, e.g. port 8354.
#   Layer B (full): make emu-all + make seed-emu, API via make api-dev-emu-auth.
#
# Usage: API_BASE_URL=http://127.0.0.1:8354 bash tests/smoke/pr-354.sh

set -uo pipefail

PASS=0
FAIL=0
SKIP=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8354}"
AUTH_EMU="${FIREBASE_AUTH_EMULATOR_HOST:-127.0.0.1:9099}"

ok()   { echo "  ✓ $1"; PASS=$((PASS+1)); }
no()   { echo "  ✗ $1"; echo "    $2"; FAIL=$((FAIL+1)); }
skip() { echo "  ↷ SKIP: $1"; SKIP=$((SKIP+1)); }

http_code() {
  # $1 method, $2 path, $3 body, $4(optional) bearer
  local method="$1" path="$2" body="$3" bearer="${4:-}"
  if [ -n "$bearer" ]; then
    curl -s -o /dev/null -w "%{http_code}" -X "$method" "$API$path" \
      -H "Content-Type: application/json" -H "Authorization: Bearer $bearer" -d "$body"
  else
    curl -s -o /dev/null -w "%{http_code}" -X "$method" "$API$path" \
      -H "Content-Type: application/json" -d "$body"
  fi
}

echo "── PR #354 PUSH-2 smoke — API=$API ──"

# ── Pre-flight: API reachable ────────────────────────────────────────────────
if ! curl -fsS "$API/health" >/dev/null 2>&1; then
  echo "ABORT: API not reachable at $API/health."
  echo "  Start it from THIS worktree, e.g.:"
  echo "    PYTHONPATH=$REPO_ROOT/api $REPO_ROOT/.venv/bin/uvicorn app.main:app --port 8354 \\"
  echo "      (with FIRESTORE_EMULATOR_HOST=127.0.0.1:8082 GOOGLE_CLOUD_PROJECT=gsm-dev-f70d0)"
  exit 1
fi
ok "API reachable at $API/health"

# ── Layer A: route wiring + auth enforcement (no auth emulator needed) ────────
echo ""
echo "── Layer A: routes exist and require auth ──"

# POST without a token must NOT be 404 (route exists) and must NOT be 2xx (auth enforced).
POST_NOAUTH=$(http_code POST /me/device-tokens '{"token":"tok_smoke","platform":"ios"}')
if [ "$POST_NOAUTH" = "404" ]; then
  no "POST /me/device-tokens route exists" "got 404 — route not registered"
elif [ "$POST_NOAUTH" = "401" ] || [ "$POST_NOAUTH" = "403" ]; then
  ok "POST /me/device-tokens exists and rejects unauthenticated ($POST_NOAUTH)"
else
  no "POST /me/device-tokens auth enforced" "expected 401/403, got $POST_NOAUTH"
fi

DEL_NOAUTH=$(http_code DELETE /me/device-tokens '{"token":"tok_smoke"}')
if [ "$DEL_NOAUTH" = "404" ]; then
  no "DELETE /me/device-tokens route exists" "got 404 — route not registered"
elif [ "$DEL_NOAUTH" = "401" ] || [ "$DEL_NOAUTH" = "403" ]; then
  ok "DELETE /me/device-tokens exists and rejects unauthenticated ($DEL_NOAUTH)"
else
  no "DELETE /me/device-tokens auth enforced" "expected 401/403, got $DEL_NOAUTH"
fi

# OpenAPI schema lists both endpoints
OPENAPI=$(curl -s "$API/openapi.json" 2>/dev/null)
if echo "$OPENAPI" | grep -q '/me/device-tokens'; then
  ok "/me/device-tokens present in OpenAPI schema"
else
  no "/me/device-tokens in OpenAPI" "path not found in openapi.json"
fi

# ── Layer B: full authed flow (requires auth emulator + seeded user) ─────────
echo ""
echo "── Layer B: authed upsert / dedupe / delete ──"

TOKEN=""
if curl -fsS "http://$AUTH_EMU/emulator/v1/projects/gsm-dev-f70d0/config" >/dev/null 2>&1; then
  TOKEN=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null || true)
fi

if [ -z "$TOKEN" ]; then
  skip "auth emulator down or token mint failed — full authed flow skipped (covered by integration tests)"
else
  DT="tok_smoke_$(date +%s)"
  FS="http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents"

  C1=$(http_code POST /me/device-tokens "{\"token\":\"$DT\",\"platform\":\"ios\"}" "$TOKEN")
  [ "$C1" = "204" ] && ok "POST register new token → 204" || no "POST register" "expected 204, got $C1"

  # Re-register same token: still 204, and must not duplicate.
  C2=$(http_code POST /me/device-tokens "{\"token\":\"$DT\",\"platform\":\"ios\"}" "$TOKEN")
  [ "$C2" = "204" ] && ok "POST re-register same token → 204" || no "POST re-register" "expected 204, got $C2"

  DOC=$(curl -s -H "Authorization: Bearer owner" "$FS/users/user_ignatios")
  COUNT=$(echo "$DOC" | python3 -c "
import sys, json
d = json.load(sys.stdin)
vals = d.get('fields', {}).get('deviceTokens', {}).get('arrayValue', {}).get('values', [])
n = sum(1 for v in vals if v.get('mapValue',{}).get('fields',{}).get('token',{}).get('stringValue') == '$DT')
print(n)
" 2>/dev/null || echo "ERR")
  [ "$COUNT" = "1" ] && ok "token stored exactly once (no dupe)" || no "dedupe" "expected 1 occurrence, got $COUNT"

  C3=$(http_code DELETE /me/device-tokens "{\"token\":\"$DT\"}" "$TOKEN")
  [ "$C3" = "204" ] && ok "DELETE token → 204" || no "DELETE" "expected 204, got $C3"

  DOC2=$(curl -s -H "Authorization: Bearer owner" "$FS/users/user_ignatios")
  GONE=$(echo "$DOC2" | python3 -c "
import sys, json
d = json.load(sys.stdin)
vals = d.get('fields', {}).get('deviceTokens', {}).get('arrayValue', {}).get('values', [])
present = any(v.get('mapValue',{}).get('fields',{}).get('token',{}).get('stringValue') == '$DT' for v in vals)
print('GONE' if not present else 'PRESENT')
" 2>/dev/null || echo "ERR")
  [ "$GONE" = "GONE" ] && ok "token removed after DELETE" || no "delete effect" "token still present: $GONE"

  # Invalid platform → 422
  C4=$(http_code POST /me/device-tokens '{"token":"x","platform":"windows"}' "$TOKEN")
  [ "$C4" = "422" ] && ok "invalid platform → 422" || no "platform validation" "expected 422, got $C4"

  # Empty token → 422
  C5=$(http_code POST /me/device-tokens '{"token":"","platform":"ios"}' "$TOKEN")
  [ "$C5" = "422" ] && ok "empty token → 422" || no "token validation" "expected 422, got $C5"
fi

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "── Summary: $PASS passed, $FAIL failed, $SKIP skipped ──"
[ "$FAIL" -eq 0 ] || exit 1
echo "Smoke OK for PR #354 (PUSH-2)."
