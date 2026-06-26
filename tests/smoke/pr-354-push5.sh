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

def fake_client(device_tokens, exists=True, intent_state=None):
    client = MagicMock()
    snap = MagicMock()
    snap.exists = exists
    snap.to_dict.return_value = {"deviceTokens": device_tokens} if device_tokens is not None else {}
    user_doc = client.collection.return_value.document.return_value
    user_doc.get.return_value = snap
    intent_doc = user_doc.collection.return_value.document.return_value
    # The idempotency guard re-reads the CURRENT intent doc; default to pending so it proceeds.
    isnap = MagicMock()
    isnap.exists = True
    isnap.to_dict.return_value = intent_state if intent_state is not None else {"deliveryStatus": "pending"}
    intent_doc.get.return_value = isnap
    return client, user_doc, intent_doc

BASE = {"type": "INCOMING_OFFER", "title": "New offer", "body": "Tap", "offerId": "off_1"}

# (a) already-delivered (per the CURRENT intent doc) → no send, no stamp.
# The event payload is the ORIGINAL pending create snapshot — the guard must ignore it and
# trust the re-read instead.
client, user_doc, intent_doc = fake_client(
    [{"token": "tok_a"}],
    intent_state={"deliveryStatus": "delivered", "deliveredAt": "2026-06-26T00:00:00Z"},
)
with patch.object(h.fcm_sender, "send") as send_mock, patch.object(h, "triggers_enabled", return_value=True):
    h.deliver_notification_intent(client, "u1", "i1", dict(BASE))  # pending payload
    check("already-delivered (current doc): send not called", not send_mock.called)
    check("already-delivered (current doc): no stamp write", not intent_doc.update.called)
    check("already-delivered (current doc): no user-token read", not user_doc.get.called)

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

# (e) DUPLICATE EVENT (codex regression): the same ORIGINAL pending payload delivered twice.
# A stateful intent doc reflects the first call's stamp on the second .get(), so the guard
# skips the re-send.
istate = {"deliveryStatus": "pending"}
client = MagicMock()
user_doc = client.collection.return_value.document.return_value
usnap = MagicMock(); usnap.exists = True; usnap.to_dict.return_value = {"deviceTokens": [{"token": "tok_a"}]}
user_doc.get.return_value = usnap
intent_doc = user_doc.collection.return_value.document.return_value
def _iget():
    s = MagicMock(); s.exists = True; s.to_dict.return_value = dict(istate); return s
intent_doc.get.side_effect = _iget
intent_doc.update.side_effect = lambda payload: istate.update(payload)
with patch.object(h.fcm_sender, "send", return_value=(1, [])), patch.object(h, "triggers_enabled", return_value=True):
    h.deliver_notification_intent(client, "u1", "i1", dict(BASE))  # first
    h.deliver_notification_intent(client, "u1", "i1", dict(BASE))  # duplicate event
    check("duplicate event: sent exactly once", h.fcm_sender.send.call_count == 1)
    check("duplicate event: final status delivered", istate.get("deliveryStatus") == "delivered")

print(f"\n── {'PASS' if fails == 0 else 'FAIL'}: {fails} failed ──")
sys.exit(1 if fails else 0)
PYEOF
RC=$?
[ "$RC" -eq 0 ] && echo "Smoke OK for PR #354 / PUSH-5." || echo "Smoke FAILED for PR #354 / PUSH-5."
exit $RC
