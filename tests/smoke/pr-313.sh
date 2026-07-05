#!/usr/bin/env bash
# Smoke tests for PR #313: docs: OBS-1 define structured launch telemetry schema (#280)
# Generated: 2026-05-30
# Usage: bash tests/smoke/pr-313.sh
#
# Docs-only PR — verifies file existence, content completeness, and formatting.
# No API or Firestore emulator required.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

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
  local name="$1" file="$2" pattern="$3"
  if grep -q "$pattern" "$file" 2>/dev/null; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name"
    echo "    pattern '$pattern' not found in $file"
    ((FAIL++)) || true
  fi
}

assert_file_exists() {
  local name="$1" file="$2"
  if [ -f "$file" ]; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name"
    echo "    file not found: $file"
    ((FAIL++)) || true
  fi
}

echo ""
echo "── Step 1: docs/operations/observability.md exists ───────────────────────────────────────"
TELEMETRY="$REPO_ROOT/docs/operations/observability.md"
assert_file_exists "docs/operations/observability.md exists" "$TELEMETRY"

echo ""
echo "── Step 2: All 8 funnel event names are defined ───────────────────────────"
assert_contains "event: broadcast_created" "$TELEMETRY" "broadcast_created"
assert_contains "event: offer_sent"        "$TELEMETRY" "offer_sent"
assert_contains "event: offer_received"    "$TELEMETRY" "offer_received"
assert_contains "event: offer_accepted"    "$TELEMETRY" "offer_accepted"
assert_contains "event: match_scheduled"   "$TELEMETRY" "match_scheduled"
assert_contains "event: score_submitted"   "$TELEMETRY" "score_submitted"
assert_contains "event: score_confirmed"   "$TELEMETRY" "score_confirmed"
assert_contains "event: match_disputed"    "$TELEMETRY" "match_disputed"

echo ""
echo "── Step 3: Required base fields documented ─────────────────────────────────"
assert_contains "field: event_type"  "$TELEMETRY" "event_type"
assert_contains "field: uid"         "$TELEMETRY" "uid"
assert_contains "field: created_at"  "$TELEMETRY" "created_at"
assert_contains "field: sport"       "$TELEMETRY" "sport"
assert_contains "field: match_type"  "$TELEMETRY" "match_type"
assert_contains "field: region"      "$TELEMETRY" "region"
assert_contains "field: venue_present" "$TELEMETRY" "venue_present"
assert_contains "field: broadcast_id" "$TELEMETRY" "broadcast_id"
assert_contains "field: offer_id"    "$TELEMETRY" "offer_id"
assert_contains "field: match_id"    "$TELEMETRY" "match_id"

echo ""
echo "── Step 4: Computed metrics table present ──────────────────────────────────"
assert_contains "time-to-match metric" "$TELEMETRY" "time-to-match\|Time-to-match\|time_to_match"
assert_contains "time-to-confirm metric" "$TELEMETRY" "time-to-confirm\|Time-to-confirm\|time_to_confirm"

echo ""
echo "── Step 5: Singles + doubles compatibility noted ───────────────────────────"
assert_contains "doubles compatibility section" "$TELEMETRY" "[Dd]oubles"

echo ""
echo "── Step 6: docs/operations/observability.md cross-reference added ─────────────────────"
OBSERVABILITY="$REPO_ROOT/docs/operations/observability.md"
assert_file_exists "docs/operations/observability.md exists" "$OBSERVABILITY"
assert_contains "Funnel Telemetry Events section" "$OBSERVABILITY" "Funnel Telemetry Events"
assert_contains "link to telemetry.md" "$OBSERVABILITY" "telemetry.md"

echo ""
echo "── Step 7: make fmt format type passes ─────────────────────────────────────"
MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null | awk '/^worktree / {print $2; exit}')
VENV_DIR="$MAIN_WT/.venv"
if [ ! -f "$VENV_DIR/bin/activate" ]; then
  VENV_DIR="$REPO_ROOT/.venv"
fi
if make -C "$REPO_ROOT" VENV="$VENV_DIR" fmt format type >/dev/null 2>&1; then
  echo "  ✓ make fmt format type passes"
  ((PASS++)) || true
else
  echo "  ✗ make fmt format type failed"
  make -C "$REPO_ROOT" VENV="$VENV_DIR" fmt format type 2>&1 | tail -10
  ((FAIL++)) || true
fi

echo ""
echo "────────────────────────────────────────────────────────────────────────────"
echo "Smoke tests PR #313: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
