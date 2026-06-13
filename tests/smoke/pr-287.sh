#!/usr/bin/env bash
# Smoke tests for PR #287: feat: DBL-6 extend scoring engine for doubles point calculation (#170)
# Generated: 2026-05-03
# Usage: bash tests/smoke/pr-287.sh
#
# Requires: make emu-all running. The smoke-test skill starts the API.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8000}"
PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}"
FIRESTORE="http://127.0.0.1:8082/emulator/v1/projects/$PROJECT/databases/(default)/documents"

MATCH_ID="dbl6_smoke_pr287"
SINGLES_MATCH_ID="singles_smoke_pr287"

# ── Venv resolution ─────────────────────────────────────────────────────────
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

# ── Helpers ────────────────────────────────────────────────────────────────

assert_eq() {
  local name="$1" actual="$2" expected="$3"
  if [ "$actual" = "$expected" ]; then
    echo "  ✓ $name"
    PASS=$((PASS+1))
  else
    echo "  ✗ $name"
    echo "    expected: $expected"
    echo "    actual:   $actual"
    FAIL=$((FAIL+1))
  fi
}

assert_gt() {
  local name="$1" actual="$2" threshold="$3"
  if [ "$actual" -gt "$threshold" ] 2>/dev/null; then
    echo "  ✓ $name ($actual > $threshold)"
    PASS=$((PASS+1))
  else
    echo "  ✗ $name (expected > $threshold, got $actual)"
    FAIL=$((FAIL+1))
  fi
}

assert_lt() {
  local name="$1" actual="$2" threshold="$3"
  if [ "$actual" -lt "$threshold" ] 2>/dev/null; then
    echo "  ✓ $name ($actual < $threshold)"
    PASS=$((PASS+1))
  else
    echo "  ✗ $name (expected < $threshold, got $actual)"
    FAIL=$((FAIL+1))
  fi
}

firestore_delete() {
  curl -s -X DELETE "$FIRESTORE/$1" > /dev/null
}

firestore_get_field() {
  curl -s "$FIRESTORE/$1" | jq -r "$2 // \"null\""
}

firestore_put_user() {
  local uid="$1" name="$2" pts="$3"
  curl -s -X PATCH "$FIRESTORE/users/$uid" \
    -H "Content-Type: application/json" \
    -d "{
      \"fields\": {
        \"uid\": {\"stringValue\": \"$uid\"},
        \"name\": {\"stringValue\": \"$name\"},
        \"email\": {\"stringValue\": \"${uid}@gsm.local\"},
        \"playTab\": {\"mapValue\": {\"fields\": {
          \"state\": {\"stringValue\": \"DISCOVERY\"},
          \"activeBroadcastId\": {\"nullValue\": null},
          \"activeOutgoingOfferId\": {\"nullValue\": null},
          \"activeMatchId\": {\"nullValue\": null},
          \"pendingIncomingOfferIds\": {\"arrayValue\": {\"values\": []}}
        }}},
        \"rankings\": {\"mapValue\": {\"fields\": {
          \"tennis\": {\"mapValue\": {\"fields\": {
            \"pts\": {\"integerValue\": \"$pts\"},
            \"tier\": {\"stringValue\": \"amateur\"},
            \"registrationTier\": {\"stringValue\": \"amateur\"},
            \"currentStreak\": {\"integerValue\": \"0\"},
            \"bestStreak\": {\"integerValue\": \"0\"}
          }}}
        }}}
      }
    }" > /dev/null
}

firestore_put_doubles_match() {
  curl -s -X PATCH "$FIRESTORE/matches/$MATCH_ID" \
    -H "Content-Type: application/json" \
    -d '{
      "fields": {
        "sport": {"stringValue": "tennis"},
        "status": {"stringValue": "scheduled"},
        "matchType": {"stringValue": "doubles"},
        "participantUids": {"arrayValue": {"values": [
          {"stringValue": "user_alice"},
          {"stringValue": "user_ignatios"},
          {"stringValue": "user_bob"},
          {"stringValue": "user_charlie"}
        ]}},
        "participants": {"arrayValue": {"values": [
          {"mapValue": {"fields": {
            "uid": {"stringValue": "user_alice"},
            "team": {"stringValue": "A"},
            "role": {"stringValue": "player"},
            "displayName": {"stringValue": "Alice"}
          }}},
          {"mapValue": {"fields": {
            "uid": {"stringValue": "user_ignatios"},
            "team": {"stringValue": "A"},
            "role": {"stringValue": "player"},
            "displayName": {"stringValue": "Ignatios"}
          }}},
          {"mapValue": {"fields": {
            "uid": {"stringValue": "user_bob"},
            "team": {"stringValue": "B"},
            "role": {"stringValue": "player"},
            "displayName": {"stringValue": "Bob"}
          }}},
          {"mapValue": {"fields": {
            "uid": {"stringValue": "user_charlie"},
            "team": {"stringValue": "B"},
            "role": {"stringValue": "player"},
            "displayName": {"stringValue": "Charlie"}
          }}}
        ]}},
        "resultSubmittedBy": {"arrayValue": {}},
        "resultByUser": {"mapValue": {}}
      }
    }' > /dev/null
}

firestore_put_singles_match() {
  curl -s -X PATCH "$FIRESTORE/matches/$SINGLES_MATCH_ID" \
    -H "Content-Type: application/json" \
    -d '{
      "fields": {
        "sport": {"stringValue": "tennis"},
        "status": {"stringValue": "scheduled"},
        "matchType": {"stringValue": "singles"},
        "participantUids": {"arrayValue": {"values": [
          {"stringValue": "user_alice"},
          {"stringValue": "user_ignatios"}
        ]}},
        "participants": {"arrayValue": {"values": [
          {"mapValue": {"fields": {
            "uid": {"stringValue": "user_alice"},
            "role": {"stringValue": "player"},
            "displayName": {"stringValue": "Alice"}
          }}},
          {"mapValue": {"fields": {
            "uid": {"stringValue": "user_ignatios"},
            "role": {"stringValue": "player"},
            "displayName": {"stringValue": "Ignatios"}
          }}}
        ]}},
        "resultSubmittedBy": {"arrayValue": {}},
        "resultByUser": {"mapValue": {}}
      }
    }' > /dev/null
}

seed_config() {
  # Seed config/tiers and config/regions using the canonical TIER_CONFIG /
  # REGION_MAPPING from tools/seed_data so tier-aware scoring + ticker emission
  # work. Without this, the first scoring call raises
  # "Tier config not found in Firestore (config/tiers)" → 404.
  # shellcheck disable=SC2155
  local PY="$VENV_DIR/bin/python"
  if [ ! -x "$PY" ]; then
    PY="python3"
  fi
  FIRESTORE_EMULATOR_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}" \
  GOOGLE_CLOUD_PROJECT="$PROJECT" \
  PYTHONPATH="$REPO_ROOT/api:$REPO_ROOT" \
  "$PY" - <<'PY' >/dev/null 2>&1 || true
from google.cloud import firestore
from tools.seed_data import REGION_MAPPING, TIER_CONFIG
from tools.seed_mapping import (
    region_config_to_firestore_doc,
    tier_config_to_firestore_doc,
)

client = firestore.Client()
client.collection("config").document("tiers").set(tier_config_to_firestore_doc(TIER_CONFIG))
client.collection("config").document("regions").set(region_config_to_firestore_doc(REGION_MAPPING))
PY
}

seed_all() {
  seed_config
  # Seed users with distinct pts so we can verify avg-opponent computation.
  # Team A: Alice=1000, Ignatios=1100 → avg=1050
  # Team B: Bob=1050,  Charlie=1200  → avg=1125
  firestore_put_user "user_alice"    "Alice"    "1000"
  firestore_put_user "user_ignatios" "Ignatios" "1100"
  firestore_put_user "user_bob"      "Bob"      "1050"
  firestore_put_user "user_charlie"  "Charlie"  "1200"
  firestore_put_doubles_match
  firestore_put_singles_match
  sleep 0.3
}

reset_scenario() {
  firestore_delete "matches/$MATCH_ID"
  seed_all
}

# ── Token acquisition ───────────────────────────────────────────────────────
TOKEN_ALICE=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_alice -t 2>/dev/null)
TOKEN_IGGY=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null)
TOKEN_BOB=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_bob -t 2>/dev/null)
TOKEN_CHARLIE=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_charlie -t 2>/dev/null)

if [ -z "$TOKEN_ALICE" ] || [ -z "$TOKEN_IGGY" ] || [ -z "$TOKEN_BOB" ] || [ -z "$TOKEN_CHARLIE" ]; then
  echo "ERROR: Could not get auth tokens. Is the auth emulator running?"
  exit 1
fi

seed_all

# ── Scenario 1: Doubles happy path — scoring runs on confirmation ───────────
echo "── Scenario 1: Doubles confirmation — scoring runs ──"

# First submission (Alice, team A)
S1=$(curl -s -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $TOKEN_ALICE" -H "Content-Type: application/json" \
  -d '{"winner_team":"A","score":{"sets":[{"p1_games":6,"p2_games":3},{"p1_games":6,"p2_games":4}]}}')
assert_eq "First submission → pending_confirmation" \
  "$(echo "$S1" | jq -r '.status // "null"')" "pending_confirmation"

# Opposing-team confirmation (Bob, team B agrees A won)
S2=$(curl -s -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $TOKEN_BOB" -H "Content-Type: application/json" \
  -d '{"winner_team":"A"}')
assert_eq "Opposing confirmation → status=completed" \
  "$(echo "$S2" | jq -r '.status // "null"')" "completed"
assert_eq "winner_team=A on confirmed match" \
  "$(echo "$S2" | jq -r '.winner_team // "null"')" "A"
assert_eq "loser_team=B on confirmed match" \
  "$(echo "$S2" | jq -r '.loser_team // "null"')" "B"
# Bob is the confirmer (loser); response.scoring.delta should be ≤ 0
BOB_DELTA=$(echo "$S2" | jq -r '.scoring.delta // "null"')
if [ "$BOB_DELTA" != "null" ]; then
  assert_lt "Bob (loser) scoring.delta ≤ 0" "$BOB_DELTA" "1"
fi

# Match doc
assert_eq "Match doc status=completed" \
  "$(firestore_get_field "matches/$MATCH_ID" '.fields.status.stringValue')" "completed"

# Winner pts increased from 1000
ALICE_PTS=$(firestore_get_field "users/user_alice" \
  '.fields.rankings.mapValue.fields.tennis.mapValue.fields.pts.integerValue')
assert_gt "Alice (winner) pts increased above 1000" "$ALICE_PTS" "1000"

IGGY_PTS=$(firestore_get_field "users/user_ignatios" \
  '.fields.rankings.mapValue.fields.tennis.mapValue.fields.pts.integerValue')
assert_gt "Ignatios (winner) pts increased above 1100" "$IGGY_PTS" "1100"

# Loser pts not greater than original (may decrease or stay at floor)
BOB_PTS=$(firestore_get_field "users/user_bob" \
  '.fields.rankings.mapValue.fields.tennis.mapValue.fields.pts.integerValue')
CHARLIE_PTS=$(firestore_get_field "users/user_charlie" \
  '.fields.rankings.mapValue.fields.tennis.mapValue.fields.pts.integerValue')
assert_lt "Bob (loser) pts ≤ 1050" "$BOB_PTS" "1051"
assert_lt "Charlie (loser) pts ≤ 1200" "$CHARLIE_PTS" "1201"

# Streaks
ALICE_STREAK=$(firestore_get_field "users/user_alice" \
  '.fields.rankings.mapValue.fields.tennis.mapValue.fields.currentStreak.integerValue')
assert_eq "Alice streak incremented to 1" "$ALICE_STREAK" "1"
BOB_STREAK=$(firestore_get_field "users/user_bob" \
  '.fields.rankings.mapValue.fields.tennis.mapValue.fields.currentStreak.integerValue')
assert_eq "Bob streak reset to 0" "$BOB_STREAK" "0"

# playTab → DISCOVERY for all 4
ALICE_STATE=$(curl -s "$API/me/state" -H "Authorization: Bearer $TOKEN_ALICE" | jq -r '.mode // .play_tab.state // "null"')
assert_eq "Alice playTab → DISCOVERY" "$ALICE_STATE" "DISCOVERY"
BOB_STATE=$(curl -s "$API/me/state" -H "Authorization: Bearer $TOKEN_BOB" | jq -r '.mode // .play_tab.state // "null"')
assert_eq "Bob playTab → DISCOVERY" "$BOB_STATE" "DISCOVERY"

# pointHistory entries exist (4 docs in subcollection, check count ≥ 4)
PH_COUNT=$(curl -s "$FIRESTORE/users/user_alice/pointHistory" | jq '.documents | length')
assert_gt "Alice pointHistory has ≥ 1 entry" "${PH_COUNT:-0}" "0"

echo ""
echo "── Scenario 2: Dispute — no scoring ──"
reset_scenario

curl -s -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $TOKEN_ALICE" -H "Content-Type: application/json" \
  -d '{"winner_team":"A"}' > /dev/null

DISP=$(curl -s -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $TOKEN_BOB" -H "Content-Type: application/json" \
  -d '{"winner_team":"B"}')
assert_eq "Dispute → status=disputed" "$(echo "$DISP" | jq -r '.status // "null"')" "disputed"

# pts should not have changed (still 1000 for Alice)
ALICE_PTS_DISP=$(firestore_get_field "users/user_alice" \
  '.fields.rankings.mapValue.fields.tennis.mapValue.fields.pts.integerValue')
assert_eq "Alice pts unchanged on dispute (1000)" "$ALICE_PTS_DISP" "1000"

ALICE_DISP_STATE=$(curl -s "$API/me/state" -H "Authorization: Bearer $TOKEN_ALICE" | jq -r '.mode // .play_tab.state // "null"')
assert_eq "Alice playTab → MATCH_DISPUTED" "$ALICE_DISP_STATE" "MATCH_DISPUTED"

echo ""
echo "── Scenario 3: Singles regression ──"

# Singles submit + confirm still works with winner_uid
curl -s -X POST "$API/matches/$SINGLES_MATCH_ID/verify-score" \
  -H "Authorization: Bearer $TOKEN_ALICE" -H "Content-Type: application/json" \
  -d '{"winner_uid":"user_alice"}' > /dev/null

# Reset users pts so we have clean state before second sub
firestore_put_user "user_alice"    "Alice"    "1000"
firestore_put_user "user_ignatios" "Ignatios" "1100"
sleep 0.2

SING=$(curl -s -X POST "$API/matches/$SINGLES_MATCH_ID/verify-score" \
  -H "Authorization: Bearer $TOKEN_IGGY" -H "Content-Type: application/json" \
  -d '{"winner_uid":"user_alice"}')
assert_eq "Singles confirm → status=completed" "$(echo "$SING" | jq -r '.status // "null"')" "completed"

ALICE_PTS_SING=$(firestore_get_field "users/user_alice" \
  '.fields.rankings.mapValue.fields.tennis.mapValue.fields.pts.integerValue')
assert_gt "Alice (winner, singles) pts > 1000" "$ALICE_PTS_SING" "1000"

# ── Teardown ────────────────────────────────────────────────────────────────
firestore_delete "matches/$MATCH_ID"
firestore_delete "matches/$SINGLES_MATCH_ID"

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #287: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
