"""PUSH-6 — end-to-end notification delivery against the Firestore emulator.

Exercises the real PUSH-4 trigger handler
``functions.notification_triggers.on_notification_intent.deliver_notification_intent``
against the emulator-backed Firestore client. The FCM provider call
(``messaging.send_each_for_multicast``) is ALWAYS mocked — never the real provider —
so the test proves the Firestore side-effects (per-token send, invalid-token prune,
delivery stamp, kill switch, idempotency) without touching Google's push backend.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from firebase_admin import messaging
from google.cloud import firestore

from functions.notification_triggers.on_notification_intent import (
    deliver_notification_intent,
)

pytestmark = pytest.mark.integration

_SEND = "functions.notification_triggers.fcm_sender.messaging.send_each_for_multicast"

_UID = "user_push6"
_INTENT_ID = "intent_push6"
_INTENTS_SUBCOLLECTION = "notificationIntents"


@pytest.fixture(autouse=True)
def _cleanup_intents(db: firestore.Client):
    """Delete the test user's notificationIntents subcollection.

    The autouse ``_cleanup`` in conftest only wipes top-level ``users`` docs, not
    their subcollections, so we remove the intent docs ourselves.
    """
    yield
    for doc in (
        db.collection("users")
        .document(_UID)
        .collection(_INTENTS_SUBCOLLECTION)
        .stream()
    ):
        (
            db.collection("users")
            .document(_UID)
            .collection(_INTENTS_SUBCOLLECTION)
            .document(doc.id)
            .delete()
        )


def _response(success: bool, exception: BaseException | None = None) -> MagicMock:
    """Fake FCM SendResponse with ``.success`` and ``.exception``."""
    resp = MagicMock()
    resp.success = success
    resp.exception = exception
    return resp


def _batch(responses: list[MagicMock]) -> MagicMock:
    """Fake FCM BatchResponse with ``.responses`` and ``.success_count``."""
    batch = MagicMock()
    batch.responses = responses
    batch.success_count = sum(1 for r in responses if r.success)
    return batch


def _seed_user(db: firestore.Client, tokens: list[str]) -> None:
    db.collection("users").document(_UID).set(
        {
            "displayName": "Push Six",
            "deviceTokens": [{"token": tok, "platform": "ios"} for tok in tokens],
        }
    )


def _seed_intent(db: firestore.Client, intent: dict[str, Any]) -> None:
    # The handler stamps via .update, which requires the doc to already exist.
    db.collection("users").document(_UID).collection(_INTENTS_SUBCOLLECTION).document(
        _INTENT_ID
    ).set(intent)


def _read_user(db: firestore.Client) -> dict[str, Any]:
    return db.collection("users").document(_UID).get().to_dict() or {}


def _read_intent(db: firestore.Client) -> dict[str, Any]:
    return (
        db.collection("users")
        .document(_UID)
        .collection(_INTENTS_SUBCOLLECTION)
        .document(_INTENT_ID)
        .get()
        .to_dict()
        or {}
    )


def _user_tokens(db: firestore.Client) -> list[str]:
    user = _read_user(db)
    return [
        entry["token"]
        for entry in user.get("deviceTokens", [])
        if isinstance(entry, dict) and entry.get("token")
    ]


def _base_intent() -> dict[str, Any]:
    return {
        "type": "match_confirmed",
        "title": "Match confirmed",
        "body": "You're on for padel",
        "matchId": "m_push6",
        "deliveryStatus": "pending",
    }


def test_one_send_per_valid_token_and_stamps_delivered(db: firestore.Client) -> None:
    _seed_user(db, ["tok_a", "tok_b"])
    _seed_intent(db, _base_intent())

    with patch(_SEND) as send_mock:
        send_mock.return_value = _batch([_response(True), _response(True)])
        deliver_notification_intent(db, _UID, _INTENT_ID, _base_intent())

    # Exactly one multicast send carrying both valid tokens.
    send_mock.assert_called_once()
    message = send_mock.call_args[0][0]
    assert list(message.tokens) == ["tok_a", "tok_b"]

    # Both tokens preserved on the user doc.
    assert _user_tokens(db) == ["tok_a", "tok_b"]

    # Intent stamped delivered.
    intent = _read_intent(db)
    assert intent["deliveryStatus"] == "delivered"
    assert intent.get("deliveredAt") is not None


def test_invalid_token_is_pruned(db: firestore.Client) -> None:
    _seed_user(db, ["tok_good", "tok_bad"])
    _seed_intent(db, _base_intent())

    with patch(_SEND) as send_mock:
        send_mock.return_value = _batch(
            [
                _response(True),
                _response(False, messaging.UnregisteredError("token gone")),
            ]
        )
        deliver_notification_intent(db, _UID, _INTENT_ID, _base_intent())

    send_mock.assert_called_once()
    # The invalid token was pruned; the valid one kept.
    assert _user_tokens(db) == ["tok_good"]

    intent = _read_intent(db)
    assert intent["deliveryStatus"] == "delivered"
    assert intent.get("deliveredAt") is not None


def test_kill_switch_suppresses_delivery(
    db: firestore.Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GSM_TRIGGERS_ENABLED", "false")
    _seed_user(db, ["tok_a"])
    _seed_intent(db, _base_intent())

    with patch(_SEND) as send_mock:
        deliver_notification_intent(db, _UID, _INTENT_ID, _base_intent())

    # No FCM call, intent untouched (still pending, no deliveredAt).
    send_mock.assert_not_called()
    intent = _read_intent(db)
    assert intent["deliveryStatus"] == "pending"
    assert intent.get("deliveredAt") is None


def test_idempotency_skips_resend_when_already_delivered(
    db: firestore.Client,
) -> None:
    _seed_user(db, ["tok_a"])
    _seed_intent(db, _base_intent())

    # First invocation delivers and stamps.
    with patch(_SEND) as first_send:
        first_send.return_value = _batch([_response(True)])
        deliver_notification_intent(db, _UID, _INTENT_ID, _base_intent())
    first_send.assert_called_once()

    # Second invocation receives the intent dict as it now exists (carrying
    # deliveredAt), simulating an at-least-once redelivery — must not re-send.
    redelivered_intent = _read_intent(db)
    assert redelivered_intent.get("deliveredAt") is not None
    with patch(_SEND) as second_send:
        deliver_notification_intent(db, _UID, _INTENT_ID, redelivered_intent)
    second_send.assert_not_called()


def test_no_tokens_stamps_no_tokens(db: firestore.Client) -> None:
    _seed_user(db, [])
    _seed_intent(db, _base_intent())

    with patch(_SEND) as send_mock:
        deliver_notification_intent(db, _UID, _INTENT_ID, _base_intent())

    send_mock.assert_not_called()
    intent = _read_intent(db)
    assert intent["deliveryStatus"] == "no_tokens"
    assert intent.get("deliveredAt") is not None
