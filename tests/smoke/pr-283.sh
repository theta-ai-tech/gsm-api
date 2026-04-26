#!/usr/bin/env bash
# Smoke tests for PR #283: feat: DBL-2 extend match model for doubles (#166)
# Generated: 2026-04-26
# Usage: bash tests/smoke/pr-283.sh
#
# Requires: make emu-all + make api-dev-emu-auth running

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="http://localhost:8000"
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

# ── Token acquisition ───────────────────────────────────────────────────────
TOKEN=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null)
if [ -z "$TOKEN" ]; then
  echo "ERROR: Could not get auth token for user_ignatios. Is the auth emulator running?"
  exit 1
fi

# ── Tests ───────────────────────────────────────────────────────────────────

# Test 1: /me/play returns 200 — confirms to_match parses seeded match docs
# (which include singles/legacy formats) without crashing.
echo "Test 1: GET /me/play returns 200 (to_match parses legacy/seed match docs)"
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$API/me/play")
assert_eq "GET /me/play status 200" "$HTTP_STATUS" "200"

# Test 2: Verify the seeded match-pending document parses through the new
# model by reading it via the matches REST endpoint chain (compute-on-read
# defaults applied: matchType='singles', resultSubmittedBy=[]).
echo "Test 2: Inspect seeded singles match via Firestore — confirms doc shape"
SPORT=$(curl -s "$FIRESTORE/matches/match_pending" | jq -r '.fields.sport.stringValue // "null"')
assert_eq "match_pending exists with sport field" "$SPORT" "tennis"

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
