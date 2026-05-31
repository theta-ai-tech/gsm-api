#!/usr/bin/env bash
# Smoke tests for PR #314: test: SMK-1 add smoke test for doubles match lifecycle (#276)
# Generated: 2026-05-30
# Usage: bash tests/smoke/pr-314.sh
#
# Requires: make emu-all + make api-dev-emu-auth running.
#
# Delegates to the canonical SMK-1 lifecycle script.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
exec bash "$REPO_ROOT/tests/smoke/smk-1-doubles-lifecycle.sh" "$@"
