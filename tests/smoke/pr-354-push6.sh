#!/usr/bin/env bash
# Smoke test for PUSH-6 (#348): notification delivery proof against the Firestore emulator.
# Generated: 2026-06-26
# Usage:
#   FIRESTORE_EMULATOR_HOST=127.0.0.1:8082 GOOGLE_CLOUD_PROJECT=gsm-dev-f70d0 \
#     bash tests/smoke/pr-354-push6.sh
#
# Requires: the Firestore emulator running at 127.0.0.1:8082 (e.g. `make emu-firestore`).
# FCM is mocked in-process — no real push backend is contacted.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

export FIRESTORE_EMULATOR_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}"
export GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}"

# ── Venv resolution ─────────────────────────────────────────────────────────
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  VENV_DIR="$REPO_ROOT/.venv"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null \
    | awk '/^worktree / {print $2 ; exit}')
  VENV_DIR="$MAIN_WT/.venv"
fi
if [ ! -f "$VENV_DIR/bin/activate" ]; then
  echo "ABORT: no venv found at $VENV_DIR. Run 'make venv && make install' in the main checkout."
  exit 1
fi
export PYTHONPATH="$REPO_ROOT/api${PYTHONPATH:+:$PYTHONPATH}"

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

"$VENV_DIR/bin/python" - <<'PY'
import sys
import time
from unittest.mock import MagicMock, patch

from firebase_admin import messaging
from google.cloud import firestore

from functions.notification_triggers.on_notification_intent import (
    deliver_notification_intent,
)

SEND = "functions.notification_triggers.fcm_sender.messaging.send_each_for_multicast"
INTENTS = "notificationIntents"

uid = f"smoke_push6_{int(time.time() * 1000)}"
intent_id = "smoke_intent"

client = firestore.Client(project="gsm-dev-f70d0")
users = client.collection("users")
intent_ref = users.document(uid).collection(INTENTS).document(intent_id)

passed = 0
failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"PASS: {name}")
    else:
        failed += 1
        print(f"FAIL: {name}")


def response(success, exception=None):
    r = MagicMock()
    r.success = success
    r.exception = exception
    return r


def batch(responses):
    b = MagicMock()
    b.responses = responses
    b.success_count = sum(1 for r in responses if r.success)
    return b


def read_user_tokens():
    doc = users.document(uid).get().to_dict() or {}
    return [
        e["token"]
        for e in doc.get("deviceTokens", [])
        if isinstance(e, dict) and e.get("token")
    ]


def read_intent():
    return intent_ref.get().to_dict() or {}


base_intent = {
    "type": "match_confirmed",
    "title": "Match confirmed",
    "body": "You're on for padel",
    "matchId": "m_smoke",
    "deliveryStatus": "pending",
}

try:
    # Seed: user with one valid + one invalid token, and a pending intent doc.
    users.document(uid).set(
        {
            "displayName": "Smoke Push6",
            "deviceTokens": [
                {"token": "tok_good", "platform": "ios"},
                {"token": "tok_bad", "platform": "android"},
            ],
        }
    )
    intent_ref.set(dict(base_intent))

    # First delivery: 1 success + 1 UnregisteredError.
    with patch(SEND) as send_mock:
        send_mock.return_value = batch(
            [
                response(True),
                response(False, messaging.UnregisteredError("token gone")),
            ]
        )
        deliver_notification_intent(client, uid, intent_id, dict(base_intent))

    check("send called exactly once", send_mock.call_count == 1)
    message = send_mock.call_args[0][0]
    check("multicast carried both tokens", list(message.tokens) == ["tok_good", "tok_bad"])
    check("invalid token pruned from user doc", read_user_tokens() == ["tok_good"])

    stamped = read_intent()
    check("intent stamped delivered", stamped.get("deliveryStatus") == "delivered")
    check("intent has deliveredAt", stamped.get("deliveredAt") is not None)

    # Second delivery (at-least-once): pass the now-stamped intent dict → no re-send.
    with patch(SEND) as send_mock2:
        deliver_notification_intent(client, uid, intent_id, read_intent())
    check("idempotent re-delivery does not re-send", send_mock2.call_count == 0)

finally:
    # Cleanup: subcollection then user doc.
    for d in users.document(uid).collection(INTENTS).stream():
        users.document(uid).collection(INTENTS).document(d.id).delete()
    users.document(uid).delete()

print()
print(f"TOTAL: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
PY
