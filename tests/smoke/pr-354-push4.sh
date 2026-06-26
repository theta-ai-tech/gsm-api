#!/usr/bin/env bash
# Smoke test for PR #354 / PUSH-4 (#346) — notificationIntents → FCM trigger.
#
# The handler deliver_notification_intent(client, uid, intent_id, intent) is a pure,
# mockable function (Firestore client + FCM sender both injectable/patchable). This
# smoke drives it in-process with a fake Firestore client and a stubbed sender,
# proving: delivery to all tokens + payload mapping, kill switch, no-tokens skip,
# and invalid-token pruning. No emulator / no network.
#
# Usage: bash tests/smoke/pr-354-push4.sh

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
if [ -f "$REPO_ROOT/.venv/bin/python" ]; then
  PY="$REPO_ROOT/.venv/bin/python"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null | awk '/^worktree / {print $2; exit}')
  PY="$MAIN_WT/.venv/bin/python"
fi
[ -x "$PY" ] || { echo "ABORT: no venv python found"; exit 1; }

echo "── PR #354 / PUSH-4 smoke — deliver_notification_intent() ──"

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

def fake_client(device_tokens):
    """A MagicMock firestore client whose users/{uid} doc returns the given deviceTokens."""
    client = MagicMock()
    snap = MagicMock()
    snap.exists = True
    snap.to_dict.return_value = {"deviceTokens": device_tokens}
    doc_ref = MagicMock()
    doc_ref.get.return_value = snap
    client.collection.return_value.document.return_value = doc_ref
    return client, doc_ref

INTENT = {"type": "INCOMING_OFFER", "title": "New offer", "body": "Tap to view", "offerId": "off_1"}

# 1) delivers to all tokens with correct payload mapping
client, doc_ref = fake_client([
    {"token": "tok_a", "platform": "ios"},
    {"token": "tok_b", "platform": "android"},
])
with patch.object(h.fcm_sender, "send", return_value=(2, [])) as send_mock, \
     patch.object(h, "triggers_enabled", return_value=True):
    h.deliver_notification_intent(client, "u1", "i1", INTENT)
    called = send_mock.call_args
    tokens_arg = called.args[0]
    title_arg, body_arg = called.args[1], called.args[2]
    data_arg = called.args[3] if len(called.args) > 3 else called.kwargs.get("data")
    check("sends once to both tokens", send_mock.call_count == 1 and tokens_arg == ["tok_a", "tok_b"])
    check("maps title/body", title_arg == "New offer" and body_arg == "Tap to view")
    check("data has string type + offerId", data_arg.get("type") == "INCOMING_OFFER" and data_arg.get("offerId") == "off_1")
    check("no prune when all valid", not doc_ref.update.called)

# 2) kill switch → no send
client, doc_ref = fake_client([{"token": "tok_a", "platform": "ios"}])
with patch.object(h.fcm_sender, "send") as send_mock, \
     patch.object(h, "triggers_enabled", return_value=False):
    h.deliver_notification_intent(client, "u1", "i1", INTENT)
    check("kill switch suppresses send", not send_mock.called)

# 3) no tokens → no send
client, doc_ref = fake_client([])
with patch.object(h.fcm_sender, "send") as send_mock, \
     patch.object(h, "triggers_enabled", return_value=True):
    h.deliver_notification_intent(client, "u1", "i1", INTENT)
    check("no-tokens path skips send", not send_mock.called)

# 4) invalid token pruned from user doc
client, doc_ref = fake_client([
    {"token": "tok_good", "platform": "ios"},
    {"token": "tok_bad", "platform": "android"},
])
with patch.object(h.fcm_sender, "send", return_value=(1, ["tok_bad"])), \
     patch.object(h, "triggers_enabled", return_value=True):
    h.deliver_notification_intent(client, "u1", "i1", INTENT)
    check("prune writes user doc once", doc_ref.update.call_count == 1)
    written = doc_ref.update.call_args.args[0]["deviceTokens"]
    remaining = [e["token"] for e in written]
    check("pruned tok_bad, kept tok_good", remaining == ["tok_good"])

# 5) sender error is swallowed (best-effort, never raises)
client, doc_ref = fake_client([{"token": "tok_a", "platform": "ios"}])
with patch.object(h.fcm_sender, "send", side_effect=RuntimeError("provider down")), \
     patch.object(h, "triggers_enabled", return_value=True):
    try:
        h.deliver_notification_intent(client, "u1", "i1", INTENT)
        check("send error swallowed (no raise)", True)
    except Exception:
        check("send error swallowed (no raise)", False)

print(f"\n── {'PASS' if fails == 0 else 'FAIL'}: {fails} failed ──")
sys.exit(1 if fails else 0)
PYEOF
RC=$?
[ "$RC" -eq 0 ] && echo "Smoke OK for PR #354 / PUSH-4." || echo "Smoke FAILED for PR #354 / PUSH-4."
exit $RC
