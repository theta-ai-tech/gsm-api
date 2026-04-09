#!/usr/bin/env bash
# Smoke test for PR #246 — CH-18: integration tests for all feed event types
# Requires: Firestore emulator running on 127.0.0.1:8082
#
# Usage:
#   make emu-firestore   # Terminal 1
#   bash tests/smoke/pr-246.sh   # Terminal 2
set -euo pipefail

export FIRESTORE_EMULATOR_HOST=127.0.0.1:8082
export GOOGLE_CLOUD_PROJECT=gsm-dev-f70d0

echo "=== PR #246 Smoke Test: CH-18 feed event integration tests ==="

# Verify emulator is reachable
if ! curl -sf http://127.0.0.1:8082/ > /dev/null 2>&1; then
  echo "FAIL: Firestore emulator not running on 127.0.0.1:8082"
  exit 1
fi
echo "OK: Firestore emulator is running"

echo ""
echo "--- Running integration tests ---"
if pytest tests/integration/test_clubhouse_feed_integration.py -v; then
  echo ""
  echo "=== PASS: All CH-18 feed event integration tests passed ==="
else
  echo ""
  echo "=== FAIL: Some tests failed ==="
  exit 1
fi
