#!/usr/bin/env bash
# Smoke test for PR #354 / PUSH-3 (#345) — FCM sender utility.
#
# fcm_sender.send() is a pure, mockable wrapper over firebase_admin.messaging with
# NO live provider call and NO Firestore I/O, so this smoke exercises the contract
# in-process with a stubbed `messaging` module (mirrors how PUSH-4 will mock it).
#
# Usage: bash tests/smoke/pr-354-push3.sh
# Requires: the repo venv (no emulator, no API, no network).

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
if [ -f "$REPO_ROOT/.venv/bin/python" ]; then
  PY="$REPO_ROOT/.venv/bin/python"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null | awk '/^worktree / {print $2; exit}')
  PY="$MAIN_WT/.venv/bin/python"
fi
[ -x "$PY" ] || { echo "ABORT: no venv python found"; exit 1; }

echo "── PR #354 / PUSH-3 smoke — fcm_sender.send() contract ──"

PYTHONPATH="$REPO_ROOT/api:$REPO_ROOT" "$PY" - <<'PYEOF'
import sys
from unittest.mock import patch, MagicMock

from functions.notification_triggers import fcm_sender
from firebase_admin import messaging

fails = 0
def check(name, cond):
    global fails
    print(f"  {'✓' if cond else '✗'} {name}")
    if not cond:
        fails += 1

def _resp(success, exc=None):
    r = MagicMock()
    r.success = success
    r.exception = exc
    return r

def _batch(success_count, responses):
    b = MagicMock(); b.success_count = success_count; b.responses = responses
    return b

# Patch ONLY the network call on the real messaging module so real exception
# types (UnregisteredError) stay intact for isinstance checks.
P = "functions.notification_triggers.fcm_sender.messaging.send_each_for_multicast"

# 1) all-success → (N, [])
with patch(P) as send_mock:
    send_mock.return_value = _batch(2, [_resp(True), _resp(True)])
    sc, invalid = fcm_sender.send(["a", "b"], "t", "b")
    check("all-success returns (2, [])", sc == 2 and invalid == [])

# 2) partial-invalid: one UNREGISTERED, one transient UNAVAILABLE
with patch(P) as send_mock:
    unreg = messaging.UnregisteredError("gone")
    transient = Exception("nope"); transient.code = "UNAVAILABLE"
    send_mock.return_value = _batch(1, [_resp(True), _resp(False, unreg), _resp(False, transient)])
    sc, invalid = fcm_sender.send(["ok", "stale", "flaky"], "t", "b")
    check("prunes UNREGISTERED only, keeps transient", invalid == ["stale"])

# 3) INVALID_ARGUMENT is prunable
with patch(P) as send_mock:
    bad = Exception("bad"); bad.code = "INVALID_ARGUMENT"
    send_mock.return_value = _batch(0, [_resp(False, bad)])
    sc, invalid = fcm_sender.send(["bad"], "t", "b")
    check("prunes INVALID_ARGUMENT", invalid == ["bad"])

# 4) empty tokens → (0, []) and provider NOT called
with patch(P) as send_mock:
    sc, invalid = fcm_sender.send([], "t", "b")
    check("empty tokens short-circuits without provider call",
          sc == 0 and invalid == [] and not send_mock.called)

print(f"\n── {'PASS' if fails == 0 else 'FAIL'}: {fails} failed ──")
sys.exit(1 if fails else 0)
PYEOF
RC=$?
[ "$RC" -eq 0 ] && echo "Smoke OK for PR #354 / PUSH-3." || echo "Smoke FAILED for PR #354 / PUSH-3."
exit $RC
