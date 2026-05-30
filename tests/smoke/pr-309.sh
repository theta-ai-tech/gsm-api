#!/usr/bin/env bash
# Smoke tests for PR #309: docs: OPS-2 add launch operator playbook (#273)
# Generated: 2026-05-27
# Usage: bash tests/smoke/pr-309.sh
#
# Verifies wiki/operator-playbook.md exists and that all scripts it references
# are present in the repo. No emulator or API required.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# ── Helpers ──────────────────────────────────────────────────────────────────

pass() { echo "  ✓ $1"; ((PASS++)) || true; }
fail() { echo "  ✗ $1"; echo "    $2"; ((FAIL++)) || true; }

assert_file_exists() {
  local label="$1" path="$2"
  if [ -f "$path" ]; then
    pass "$label"
  else
    fail "$label" "file not found: $path"
  fi
}

assert_file_contains() {
  local label="$1" path="$2" pattern="$3"
  if grep -q "$pattern" "$path" 2>/dev/null; then
    pass "$label"
  else
    fail "$label" "pattern '$pattern' not found in $path"
  fi
}

assert_dir_not_empty() {
  local label="$1" path="$2"
  if [ -d "$path" ] && [ -n "$(ls -A "$path" 2>/dev/null)" ]; then
    pass "$label"
  else
    fail "$label" "directory empty or missing: $path"
  fi
}

# ── Tests ─────────────────────────────────────────────────────────────────────

echo ""
echo "━━━ Playbook file existence ━━━"
assert_file_exists "wiki/operator-playbook.md exists" "$REPO_ROOT/wiki/operator-playbook.md"

echo ""
echo "━━━ Required sections present ━━━"
assert_file_contains "Section: Prerequisites"       "$REPO_ROOT/wiki/operator-playbook.md" "Prerequisites"
assert_file_contains "Section: Quick Start"         "$REPO_ROOT/wiki/operator-playbook.md" "Quick Start"
assert_file_contains "Section: Demo Users"          "$REPO_ROOT/wiki/operator-playbook.md" "Demo Users"
assert_file_contains "Section: Demo Scenarios"      "$REPO_ROOT/wiki/operator-playbook.md" "Demo Scenarios"
assert_file_contains "Section: Venues"              "$REPO_ROOT/wiki/operator-playbook.md" "Venues"
assert_file_contains "Section: Leagues"             "$REPO_ROOT/wiki/operator-playbook.md" "Leagues"
assert_file_contains "Section: Smoke Tests"         "$REPO_ROOT/wiki/operator-playbook.md" "Smoke Tests"
assert_file_contains "Section: Reset"               "$REPO_ROOT/wiki/operator-playbook.md" "Reset"
assert_file_contains "Section: Manual vs Automated" "$REPO_ROOT/wiki/operator-playbook.md" "Manual vs Automated"

echo ""
echo "━━━ Referenced scripts exist ━━━"
assert_file_exists "scripts/smoke_play.sh"      "$REPO_ROOT/scripts/smoke_play.sh"
assert_file_exists "scripts/smoke_improve.sh"   "$REPO_ROOT/scripts/smoke_improve.sh"
assert_file_exists "scripts/smoke_triggers.sh"  "$REPO_ROOT/scripts/smoke_triggers.sh"
assert_file_exists "scripts/get_emu_token.sh"   "$REPO_ROOT/scripts/get_emu_token.sh"

echo ""
echo "━━━ Referenced make targets exist ━━━"
assert_file_contains "make seed-emu target"           "$REPO_ROOT/ops/Makefile" "seed-emu"
assert_file_contains "make emu-all target"            "$REPO_ROOT/ops/Makefile" "emu-all"
assert_file_contains "make api-dev-emu-auth target"   "$REPO_ROOT/ops/Makefile" "api-dev-emu-auth"
assert_file_contains "make rebuild-caches-emu target" "$REPO_ROOT/ops/Makefile" "rebuild-caches-emu"

echo ""
echo "━━━ Smoke tests directory populated ━━━"
assert_dir_not_empty "tests/smoke/ has scripts" "$REPO_ROOT/tests/smoke"

echo ""
echo "━━━ Playbook references correct seeded IDs ━━━"
assert_file_contains "match_pending (underscore) referenced" "$REPO_ROOT/wiki/operator-playbook.md" "match_pending"
assert_file_contains "padel-local-2025 league referenced"    "$REPO_ROOT/wiki/operator-playbook.md" "padel-local-2025"
assert_file_contains "user_ignatios UID referenced"          "$REPO_ROOT/wiki/operator-playbook.md" "user_ignatios"

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Smoke tests PR #309: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
