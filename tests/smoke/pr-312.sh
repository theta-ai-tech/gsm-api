#!/usr/bin/env bash
# Smoke tests for PR #312: SMK-2 venue flow and score confirmation (#275)
# Generated: 2026-05-28
# Usage: API_BASE_URL=http://127.0.0.1:8312 bash tests/smoke/pr-312.sh
#
# Requires: make emu-all + make api-dev-emu-auth running (separate terminals).
# Seeds venues, region_config, tier_config, and users via tools.seed_firestore.
#
# Sections:
#   1. Venue lookup (GET /venues)
#   2. Broadcast with venue_ref → offer → accept → venue propagates to match
#   3. Score submission → confirmation → match completed with venue_ref intact
#   4. venue_ref via offer (not broadcast) propagates to match

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8312}"
PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}"
FIRESTORE="http://127.0.0.1:8082/emulator/v1/projects/$PROJECT/databases/(default)/documents"

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

reset_playtab() {
  for uid in user_ignatios user_alice; do
    curl -s -o /dev/null -X PATCH \
      "$FIRESTORE/users/$uid?updateMask.fieldPaths=playTab" \
      -H "Content-Type: application/json" \
      -d '{
        "fields": {
          "playTab": {
            "mapValue": {
              "fields": {
                "state": {"stringValue": "DISCOVERY"},
                "activeBroadcastId": {"nullValue": null},
                "activeOutgoingOfferId": {"nullValue": null},
                "activeMatchId": {"nullValue": null},
                "pendingIncomingOfferIds": {"arrayValue": {"values": []}}
              }
            }
          }
        }
      }' || true
  done
}

MATCH_ID=""

cleanup() {
  curl -s -o /dev/null -X DELETE -H "Authorization: Bearer $IGGY" "$API/me/broadcast" || true
  curl -s -o /dev/null -X DELETE -H "Authorization: Bearer $ALICE" "$API/me/broadcast" || true
  if [ -n "$MATCH_ID" ]; then
    curl -s -X DELETE "$FIRESTORE/matches/$MATCH_ID" > /dev/null || true
    MATCH_ID=""
  fi
  reset_playtab
}

# ── Seed ─────────────────────────────────────────────────────────────────────
echo "Seeding Firestore (venues, configs, users)..."
FIRESTORE_EMULATOR_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}" \
GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}" \
  . "$VENV_DIR/bin/activate" && \
  python3 -m tools.seed_firestore 2>/dev/null || true

# ── Token acquisition ─────────────────────────────────────────────────────────
IGGY=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_ignatios -t 2>/dev/null)
ALICE=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" user_alice -t 2>/dev/null)
if [ -z "$IGGY" ] || [ -z "$ALICE" ]; then
  echo "ERROR: Could not get auth tokens. Is the auth emulator running?"
  exit 1
fi

trap cleanup EXIT
cleanup

# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo "── Section 1: Venue lookup ──────────────────────────────────────────────"
# ═══════════════════════════════════════════════════════════════════════════════

# GET /venues?sport=padel → non-empty results
VENUES_PADEL=$(curl -s -H "Authorization: Bearer $IGGY" "$API/venues?sport=padel")
assert_eq "GET /venues?sport=padel returns non-empty list" \
  "$(echo "$VENUES_PADEL" | jq -r '.venues | length > 0')" "true"
assert_eq "padel venues response has expected shape (venues + nextCursor)" \
  "$(echo "$VENUES_PADEL" | jq 'has("venues") and has("nextCursor")')" "true"
assert_eq "padel venue objects have venueId and name fields" \
  "$(echo "$VENUES_PADEL" | jq -r '.venues[0] | has("venueId") and has("name")')" "true"

# GET /venues?sport=tennis&area=Glyfada → returns glyfada_tennis_club
VENUES_TENNIS=$(curl -s -H "Authorization: Bearer $IGGY" "$API/venues?sport=tennis&area=Glyfada")
assert_eq "GET /venues?sport=tennis&area=Glyfada returns non-empty list" \
  "$(echo "$VENUES_TENNIS" | jq -r '.venues | length > 0')" "true"
GLYFADA_FOUND=$(echo "$VENUES_TENNIS" | jq -r '[.venues[] | select(.venueId == "glyfada_tennis_club")] | length > 0')
assert_eq "tennis+Glyfada filter returns glyfada_tennis_club" "$GLYFADA_FOUND" "true"
assert_eq "all returned venues are in Glyfada area" \
  "$(echo "$VENUES_TENNIS" | jq -r '[.venues[] | select(.area != "Glyfada")] | length == 0')" "true"

# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo "── Section 2: Broadcast with venue_ref → offer → accept → venue in match ─"
# ═══════════════════════════════════════════════════════════════════════════════

cleanup

# Alice broadcasts tennis WITH venue_ref=glyfada_tennis_club
BROADCAST=$(curl -s -X POST "$API/me/broadcast" \
  -H "Authorization: Bearer $ALICE" \
  -H "Content-Type: application/json" \
  -d '{
    "sport": "tennis",
    "availability": "today",
    "court_status": "have_court",
    "expires_at": "2099-01-01T00:00:00Z",
    "location": {"area": 10001},
    "venue_ref": {
      "venueId": "glyfada_tennis_club",
      "name": "Glyfada Tennis Club",
      "coordinates": {"lat": 37.8794, "lng": 23.7541}
    }
  }')
BROADCAST_ID=$(echo "$BROADCAST" | jq -r '.broadcast_id // .id // empty')
assert_eq "Alice creates broadcast with venue_ref" "$([ -n "$BROADCAST_ID" ] && echo true || echo false)" "true"

# Iggy sends offer referencing Alice's broadcast
OFFER=$(curl -s -X POST "$API/me/offers" \
  -H "Authorization: Bearer $IGGY" \
  -H "Content-Type: application/json" \
  -d "{
    \"to_uid\": \"user_alice\",
    \"sport\": \"tennis\",
    \"proposed_time\": \"2099-12-31T18:00:00Z\",
    \"source_broadcast_id\": \"$BROADCAST_ID\"
  }")
OFFER_ID=$(echo "$OFFER" | jq -r '.offer_id // .id // empty')
assert_eq "Iggy sends offer to Alice" "$([ -n "$OFFER_ID" ] && echo true || echo false)" "true"

# Alice accepts the offer → match created
ACCEPT=$(curl -s -X POST "$API/me/offers/$OFFER_ID/accept" \
  -H "Authorization: Bearer $ALICE")
MATCH_ID=$(echo "$ACCEPT" | jq -r '.match_id // empty')
if [ -z "$MATCH_ID" ]; then
  MATCH_ID=$(curl -s -H "Authorization: Bearer $ALICE" "$API/me/state" \
    | jq -r '.payload.active_match_id // empty')
fi
assert_eq "Alice accepts offer → match created" "$([ -n "$MATCH_ID" ] && echo true || echo false)" "true"

# Read match from Firestore → assert venueRef.venueId = "glyfada_tennis_club"
MATCH_DOC=$(curl -s "$FIRESTORE/matches/$MATCH_ID")
VENUE_ID_IN_MATCH=$(echo "$MATCH_DOC" | jq -r '.fields.venueRef.mapValue.fields.venueId.stringValue // empty')
assert_eq "venue_ref from broadcast propagates to match (venueId=glyfada_tennis_club)" \
  "$VENUE_ID_IN_MATCH" "glyfada_tennis_club"

# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo "── Section 3: Score submission → confirmation → completed with venue_ref ─"
# ═══════════════════════════════════════════════════════════════════════════════

# Iggy submits score (first call) → pending_confirmation
SCORE1=$(curl -s -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $IGGY" \
  -H "Content-Type: application/json" \
  -d '{
    "winner_uid": "user_ignatios",
    "score": {"sets": [{"p1_games": 6, "p2_games": 3}, {"p1_games": 6, "p2_games": 4}]}
  }')
assert_eq "Iggy submits score → status=pending_confirmation" \
  "$(echo "$SCORE1" | jq -r '.status // empty')" "pending_confirmation"

# Alice confirms (second call, same winner) → completed
SCORE2=$(curl -s -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $ALICE" \
  -H "Content-Type: application/json" \
  -d '{"winner_uid": "user_ignatios"}')
assert_eq "Alice confirms score → status=completed" \
  "$(echo "$SCORE2" | jq -r '.status // empty')" "completed"

# Read match from Firestore → assert status=completed AND venueRef still set
MATCH_DOC_FINAL=$(curl -s "$FIRESTORE/matches/$MATCH_ID")
assert_eq "final match doc has status=completed" \
  "$(echo "$MATCH_DOC_FINAL" | jq -r '.fields.status.stringValue // empty')" "completed"
assert_eq "final match doc still has venueRef.venueId=glyfada_tennis_club" \
  "$(echo "$MATCH_DOC_FINAL" | jq -r '.fields.venueRef.mapValue.fields.venueId.stringValue // empty')" \
  "glyfada_tennis_club"

# Cleanup between sections
curl -s -X DELETE "$FIRESTORE/matches/$MATCH_ID" > /dev/null || true
MATCH_ID=""
reset_playtab

# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo "── Section 4: venue_ref via offer (not broadcast) propagates to match ────"
# ═══════════════════════════════════════════════════════════════════════════════

cleanup

# Alice broadcasts tennis WITHOUT venue_ref
BROADCAST2=$(curl -s -X POST "$API/me/broadcast" \
  -H "Authorization: Bearer $ALICE" \
  -H "Content-Type: application/json" \
  -d '{
    "sport": "tennis",
    "availability": "today",
    "court_status": "need_court",
    "expires_at": "2099-01-01T00:00:00Z",
    "location": {"area": 10001}
  }')
BROADCAST_ID2=$(echo "$BROADCAST2" | jq -r '.broadcast_id // .id // empty')
assert_eq "Alice creates broadcast without venue_ref" \
  "$([ -n "$BROADCAST_ID2" ] && echo true || echo false)" "true"

# Iggy sends offer WITH venue_ref=athens_tennis_club
OFFER2=$(curl -s -X POST "$API/me/offers" \
  -H "Authorization: Bearer $IGGY" \
  -H "Content-Type: application/json" \
  -d "{
    \"to_uid\": \"user_alice\",
    \"sport\": \"tennis\",
    \"proposed_time\": \"2099-12-31T18:00:00Z\",
    \"source_broadcast_id\": \"$BROADCAST_ID2\",
    \"venue_ref\": {
      \"venueId\": \"athens_tennis_club\",
      \"name\": \"Athens Tennis Club\",
      \"coordinates\": {\"lat\": 37.9695, \"lng\": 23.7333}
    }
  }")
OFFER_ID2=$(echo "$OFFER2" | jq -r '.offer_id // .id // empty')
assert_eq "Iggy sends offer with venue_ref=athens_tennis_club" \
  "$([ -n "$OFFER_ID2" ] && echo true || echo false)" "true"

# Alice accepts → match created
ACCEPT2=$(curl -s -X POST "$API/me/offers/$OFFER_ID2/accept" \
  -H "Authorization: Bearer $ALICE")
MATCH_ID=$(echo "$ACCEPT2" | jq -r '.match_id // empty')
if [ -z "$MATCH_ID" ]; then
  MATCH_ID=$(curl -s -H "Authorization: Bearer $ALICE" "$API/me/state" \
    | jq -r '.payload.active_match_id // empty')
fi
assert_eq "Alice accepts offer with venue_ref on offer → match created" \
  "$([ -n "$MATCH_ID" ] && echo true || echo false)" "true"

# Read match from Firestore → assert venueRef.venueId = "athens_tennis_club"
MATCH_DOC2=$(curl -s "$FIRESTORE/matches/$MATCH_ID")
VENUE_ID_OFFER=$(echo "$MATCH_DOC2" | jq -r '.fields.venueRef.mapValue.fields.venueId.stringValue // empty')
assert_eq "venue_ref from offer propagates to match (venueId=athens_tennis_club)" \
  "$VENUE_ID_OFFER" "athens_tennis_club"

# Quick score cycle: Iggy submits → Alice confirms → completed
curl -s -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $IGGY" \
  -H "Content-Type: application/json" \
  -d '{"winner_uid": "user_ignatios", "score": {"sets": [{"p1_games": 6, "p2_games": 2}]}}' \
  > /dev/null

SCORE_FINAL=$(curl -s -X POST "$API/matches/$MATCH_ID/verify-score" \
  -H "Authorization: Bearer $ALICE" \
  -H "Content-Type: application/json" \
  -d '{"winner_uid": "user_ignatios"}')
assert_eq "Section 4: score confirmed → status=completed" \
  "$(echo "$SCORE_FINAL" | jq -r '.status // empty')" "completed"

# Verify final match doc has venue_ref and completed status
MATCH_DOC2_FINAL=$(curl -s "$FIRESTORE/matches/$MATCH_ID")
assert_eq "Section 4: final match doc status=completed" \
  "$(echo "$MATCH_DOC2_FINAL" | jq -r '.fields.status.stringValue // empty')" "completed"
assert_eq "Section 4: final match doc venueRef.venueId=athens_tennis_club" \
  "$(echo "$MATCH_DOC2_FINAL" | jq -r '.fields.venueRef.mapValue.fields.venueId.stringValue // empty')" \
  "athens_tennis_club"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #312: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
