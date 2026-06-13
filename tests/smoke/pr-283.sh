#!/usr/bin/env bash
# Smoke tests for PR #283: feat: DBL-2 extend match model for doubles (#166)
# Generated: 2026-04-26
# Usage: bash tests/smoke/pr-283.sh
#
# Requires: make emu-all + make api-dev-emu-auth running
#
# Self-contained: this script does not depend on `tools/seed_data.py` having
# been run. Test 2 writes a synthetic match doc directly via the Firestore
# emulator REST API and tears it down on exit, so the regression signal is
# always meaningful regardless of the emulator's seed state.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="http://localhost:8000"
FIRESTORE="http://127.0.0.1:8082/emulator/v1/projects/gsm-dev-f70d0/databases/(default)/documents"
SMOKE_MATCH_ID="_smoke_pr283_match"

cleanup() {
  curl -s -o /dev/null -X DELETE "$FIRESTORE/matches/$SMOKE_MATCH_ID" || true
}
trap cleanup EXIT

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

# ── Token acquisition ───────────────────────────────────────────────────────
TOKEN=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null)
if [ -z "$TOKEN" ]; then
  echo "ERROR: Could not get auth token for user_ignatios. Is the auth emulator running?"
  exit 1
fi

# ── Tests ───────────────────────────────────────────────────────────────────

# Test 1: /me/state returns 200 — confirms to_match parses every match doc the
# state hydration path touches (broadcasts, scheduled matches, completed matches)
# without crashing on the new matchType / resultSubmittedBy / participants fields.
echo "Test 1: GET /me/state returns 200 (to_match parses match docs without crashing)"
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$API/me/state")
assert_eq "GET /me/state status 200" "$HTTP_STATUS" "200"

# Test 2: Self-seed a synthetic match doc via Firestore REST, then read it back
# and confirm the fields land on disk in the shape DBL-2 expects (matchType,
# resultSubmittedBy, participants[].displayName). Teardown happens in the EXIT
# trap. This avoids depending on `tools/seed_data.py` being loaded.
echo "Test 2: Self-seed match doc via Firestore REST and confirm DBL-2 shape on disk"
SEED_PAYLOAD=$(cat <<JSON
{
  "writes": [
    {
      "update": {
        "name": "projects/gsm-dev-f70d0/databases/(default)/documents/matches/$SMOKE_MATCH_ID",
        "fields": {
          "sport": {"stringValue": "tennis"},
          "status": {"stringValue": "pending_confirmation"},
          "matchType": {"stringValue": "singles"},
          "participantUids": {"arrayValue": {"values": [
            {"stringValue": "user_alice"},
            {"stringValue": "user_ignatios"}
          ]}},
          "participants": {"arrayValue": {"values": [
            {"mapValue": {"fields": {
              "uid": {"stringValue": "user_alice"},
              "role": {"stringValue": "player"},
              "displayName": {"stringValue": "Alice K."}
            }}},
            {"mapValue": {"fields": {
              "uid": {"stringValue": "user_ignatios"},
              "role": {"stringValue": "player"},
              "displayName": {"stringValue": "Ignatios C."}
            }}}
          ]}},
          "resultSubmittedBy": {"arrayValue": {"values": [
            {"stringValue": "user_alice"}
          ]}}
        }
      }
    }
  ]
}
JSON
)
SEED_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
  -H "Content-Type: application/json" \
  -d "$SEED_PAYLOAD" \
  "$FIRESTORE:commit")
assert_eq "self-seed match doc commits" "$SEED_STATUS" "200"

DOC_JSON=$(curl -s "$FIRESTORE/matches/$SMOKE_MATCH_ID")
SPORT=$(echo "$DOC_JSON" | jq -r '.fields.sport.stringValue // "null"')
MATCH_TYPE=$(echo "$DOC_JSON" | jq -r '.fields.matchType.stringValue // "null"')
SUBMITTED_BY=$(echo "$DOC_JSON" | jq -r '[.fields.resultSubmittedBy.arrayValue.values[]?.stringValue] | sort | join(",")')
DISPLAY_NAMES=$(echo "$DOC_JSON" | jq -r '[.fields.participants.arrayValue.values[]?.mapValue.fields.displayName.stringValue] | sort | join(",")')
assert_eq "seeded doc has sport=tennis"             "$SPORT"         "tennis"
assert_eq "seeded doc has matchType=singles"        "$MATCH_TYPE"    "singles"
assert_eq "seeded doc has resultSubmittedBy=alice"  "$SUBMITTED_BY"  "user_alice"
assert_eq "seeded doc has participant displayNames" "$DISPLAY_NAMES" "Alice K.,Ignatios C."

# Confirm to_match round-trips the on-disk doc (legacy mapper smoke).
PARSED=$(. "$VENV_DIR/bin/activate" && python3 - <<PY
import json, urllib.request
from app.repos.mappers import to_match

with urllib.request.urlopen("$FIRESTORE/matches/$SMOKE_MATCH_ID") as r:
    raw = json.load(r)

def unwrap(v):
    if "stringValue" in v: return v["stringValue"]
    if "integerValue" in v: return int(v["integerValue"])
    if "doubleValue" in v: return float(v["doubleValue"])
    if "booleanValue" in v: return v["booleanValue"]
    if "arrayValue" in v: return [unwrap(x) for x in v["arrayValue"].get("values", [])]
    if "mapValue" in v: return {k: unwrap(x) for k, x in v["mapValue"].get("fields", {}).items()}
    return None

doc = {k: unwrap(v) for k, v in raw["fields"].items()}
m = to_match(doc, match_id="$SMOKE_MATCH_ID")
print(f"{m.match_type.value}|{len(m.participants)}|{','.join(sorted(m.result_submitted_by))}")
PY
)
assert_eq "to_match parses self-seeded doc → singles|2|user_alice" "$PARSED" "singles|2|user_alice"

# Test 3: Verify model parses a legacy doc (no matchType field) via Python
# entrypoint — bypasses the live API entirely and asserts the mapper logic
# on a synthetic legacy payload.
echo "Test 3: Python-level mapper parses legacy match doc with matchType default"
RESULT=$(. "$VENV_DIR/bin/activate" && python3 - <<'PY'
from app.repos.mappers import to_match
doc = {
    "sport": "tennis",
    "status": "scheduled",
    "participantUids": ["u1", "u2"],
}
m = to_match(doc, match_id="legacy_smoke")
print(f"{m.match_type.value}|{len(m.participants)}|{m.result_submitted_by}")
PY
)
assert_eq "legacy doc → match_type=singles, 2 participants, [] result_submitted_by" \
  "$RESULT" "singles|2|[]"

# Test 4: Doubles validation — 4 participants, 2 per team, must succeed
echo "Test 4: Python-level doubles match parses with valid config"
RESULT=$(. "$VENV_DIR/bin/activate" && python3 - <<'PY'
from app.repos.mappers import to_match
doc = {
    "sport": "padel",
    "status": "completed",
    "matchType": "doubles",
    "participantUids": ["u1", "u2", "u3", "u4"],
    "participants": [
        {"uid": "u1", "role": "player", "team": "A"},
        {"uid": "u2", "role": "player", "team": "A"},
        {"uid": "u3", "role": "player", "team": "B"},
        {"uid": "u4", "role": "player", "team": "B"},
    ],
    "resultSubmittedBy": ["u1", "u3"],
}
m = to_match(doc, match_id="doubles_smoke")
print(f"{m.match_type.value}|{len(m.participants)}|{','.join(sorted(m.result_submitted_by))}")
PY
)
assert_eq "doubles doc → match_type=doubles, 4 participants, [u1,u3] result_submitted_by" \
  "$RESULT" "doubles|4|u1,u3"

# Test 5: Invalid doubles (3-A / 1-B) raises ValidationError
echo "Test 5: Doubles validator rejects uneven team distribution"
RESULT=$(. "$VENV_DIR/bin/activate" && python3 - <<'PY' 2>&1
from app.models import Match, MatchParticipant, MatchStatusEnum, MatchTypeEnum, SportEnum
from app.models.enums import ParticipantRoleEnum
try:
    Match(
        match_id="bad",
        sport=SportEnum.PADEL,
        status=MatchStatusEnum.SCHEDULED,
        match_type=MatchTypeEnum.DOUBLES,
        participants=[
            MatchParticipant(uid="u1", role=ParticipantRoleEnum.PLAYER, team="A"),
            MatchParticipant(uid="u2", role=ParticipantRoleEnum.PLAYER, team="A"),
            MatchParticipant(uid="u3", role=ParticipantRoleEnum.PLAYER, team="A"),
            MatchParticipant(uid="u4", role=ParticipantRoleEnum.PLAYER, team="B"),
        ],
        participant_uids=["u1", "u2", "u3", "u4"],
    )
    print("UNEXPECTED_OK")
except Exception as e:
    msg = str(e)
    print("REJECTED" if "exactly 2 participants per team" in msg else "WRONG_ERROR")
PY
)
assert_eq "doubles uneven distribution rejected" "$RESULT" "REJECTED"

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #283: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
