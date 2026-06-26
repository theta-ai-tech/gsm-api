#!/usr/bin/env bash
# Smoke test for PR #354 / PUSH-5 (#347) — delivery idempotency.
#
# Drives deliver_notification_intent() in-process with a fake Firestore client that
# distinguishes the USER doc (read + prune) from the INTENT subcollection doc (stamp),
# proving: (a) an intent already carrying deliveredAt is NOT re-sent and NOT re-stamped;
# (b) a successful send stamps deliveryStatus=delivered; (c) no-tokens stamps no_tokens;
# (d) a send error stamps failed. No emulator / no network.
#
# Usage: bash tests/smoke/pr-354-push5.sh

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
if [ -f "$REPO_ROOT/.venv/bin/python" ]; then
  PY="$REPO_ROOT/.venv/bin/python"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null | awk '/^worktree / {print $2; exit}')
  PY="$MAIN_WT/.venv/bin/python"
fi
[ -x "$PY" ] || { echo "ABORT: no venv python found"; exit 1; }

echo "── PR #354 / PUSH-5 smoke — delivery idempotency ──"

PYTHONPATH="$REPO_ROOT/api:$REPO_ROOT" "$PY" - <<'PYEOF'
import sys
from unittest.mock import MagicMock, patch

from functions.notification_triggers import on_notification_intent as h

fails = 0
def check(name, cond):
    global fails
    print(f"  {'✓' if cond else '✗'} {name}")
    if not cond:
        fails += 1

def fake_client(device_tokens, exists=True):
    client = MagicMock()
    snap = MagicMock()
    snap.exists = exists
    snap.to_dict.return_value = {"deviceTokens": device_tokens} if device_tokens is not None else {}
    user_doc = client.collection.return_value.document.return_value
    user_doc.get.return_value = snap
    intent_doc = user_doc.collection.return_value.document.return_value
    return client, user_doc, intent_doc

BASE = {"type": "INCOMING_OFFER", "title": "New offer", "body": "Tap", "offerId": "off_1"}

# (a) already-delivered → no send, no stamp, no read
client, user_doc, intent_doc = fake_client([{"token": "tok_a"}])
with patch.object(h.fcm_sender, "send") as send_mock, patch.object(h, "triggers_enabled", return_value=True):
    h.deliver_notification_intent(client, "u1", "i1", {**BASE, "deliveredAt": "2026-06-26T00:00:00Z"})
    check("already-delivered: send not called", not send_mock.called)
    check("already-delivered: no stamp write", not intent_doc.update.called)
    check("already-delivered: no user read", not client.collection.called)

# (b) success → intent stamped delivered
client, user_doc, intent_doc = fake_client([{"token": "tok_a"}, {"token": "tok_b"}])
with patch.object(h.fcm_sender, "send", return_value=(2, [])), patch.object(h, "triggers_enabled", return_value=True):
    h.deliver_notification_intent(client, "u1", "i1", dict(BASE))
    stamped = intent_doc.update.call_args.args[0] if intent_doc.update.called else {}
    check("success: intent stamped delivered",
          intent_doc.update.call_count == 1 and stamped.get("deliveryStatus") == "delivered" and "deliveredAt" in stamped)

# (c) no tokens → stamped no_tokens, no send
client, user_doc, intent_doc = fake_client([])
with patch.object(h.fcm_sender, "send") as send_mock, patch.object(h, "triggers_enabled", return_value=True):
    h.deliver_notification_intent(client, "u1", "i1", dict(BASE))
    stamped = intent_doc.update.call_args.args[0] if intent_doc.update.called else {}
    check("no-tokens: stamped no_tokens, no send",
          not send_mock.called and stamped.get("deliveryStatus") == "no_tokens")

# (d) send error → stamped failed
client, user_doc, intent_doc = fake_client([{"token": "tok_a"}])
with patch.object(h.fcm_sender, "send", side_effect=RuntimeError("down")), patch.object(h, "triggers_enabled", return_value=True):
    h.deliver_notification_intent(client, "u1", "i1", dict(BASE))
    stamped = intent_doc.update.call_args.args[0] if intent_doc.update.called else {}
    check("send-error: stamped failed", stamped.get("deliveryStatus") == "failed")

print(f"\n── {'PASS' if fails == 0 else 'FAIL'}: {fails} failed ──")
sys.exit(1 if fails else 0)
PYEOF
RC=$?
[ "$RC" -eq 0 ] && echo "Smoke OK for PR #354 / PUSH-5." || echo "Smoke FAILED for PR #354 / PUSH-5."
exit $RC
