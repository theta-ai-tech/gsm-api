"""
PUSH-4 — notificationIntents Firestore trigger → FCM delivery.

Fires when a ``users/{uid}/notificationIntents/{intentId}`` document is created
(see ``api/app/repos/notification_intent_repo.py`` for the writer). Reads the
target user's device tokens, builds an FCM payload, and delivers it via the
PUSH-3 sender. Delivery is best-effort and decoupled: a send or prune failure is
logged but never raised, so it can never roll back the business transaction that
produced the intent.

Delivery idempotency (PUSH-5): Cloud Functions are at-least-once, so this trigger
can fire more than once for a single intent write. Before sending, we skip any intent
that already carries a ``deliveredAt`` stamp. After every terminal outcome we stamp the
intent doc (``users/{uid}/notificationIntents/{intentId}``) with ``deliveredAt`` and a
``deliveryStatus`` of ``delivered`` / ``no_tokens`` / ``failed``. Stamp writes are
best-effort: a stamp failure is logged, never raised.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore  # type: ignore[import-untyped]

from functions.logging_utils import log_event
from functions.notification_triggers import fcm_sender
from functions.runtime_flags import triggers_enabled

_TRIGGER = "onNotificationIntentCreated"

# Optional intent fields that map straight into the FCM data payload (as strings).
_OPTIONAL_DATA_KEYS = ("offerId", "matchId", "broadcastId")

# Delivery status literals. functions/ must not import api/app, so these are kept
# in sync with api.app.models.enums.DeliveryStatusEnum by hand.
_STATUS_DELIVERED = "delivered"
_STATUS_NO_TOKENS = "no_tokens"
_STATUS_FAILED = "failed"

_INTENTS_SUBCOLLECTION = "notificationIntents"


def _intent_ref(client: firestore.Client, uid: str, intent_id: str) -> Any:
    # The INTENT doc lives in the per-user subcollection, NOT on the user doc.
    return (
        client.collection("users")
        .document(uid)
        .collection(_INTENTS_SUBCOLLECTION)
        .document(intent_id)
    )


def _stamp(client: firestore.Client, uid: str, intent_id: str, status: str) -> None:
    # Best-effort delivery stamp on the INTENT doc (subcollection), not the user doc.
    try:
        _intent_ref(client, uid, intent_id).update(
            {
                "deliveredAt": datetime.now(timezone.utc),
                "deliveryStatus": status,
            }
        )
    except Exception as exc:  # best-effort: a stamp failure must not raise
        log_event(
            trigger=_TRIGGER,
            action="error",
            reason="stamp_failed",
            uid=uid,
            intentId=intent_id,
            deliveryStatus=status,
            error=str(exc),
        )


def _extract_tokens(device_tokens: list[Any]) -> list[str]:
    tokens: list[str] = []
    for entry in device_tokens:
        if isinstance(entry, dict):
            token = entry.get("token")
            if token:
                tokens.append(str(token))
    return tokens


def _build_data(intent: dict[str, Any]) -> dict[str, str]:
    # FCM data maps require string values for every key.
    data: dict[str, str] = {"type": str(intent.get("type", ""))}
    for key in _OPTIONAL_DATA_KEYS:
        value = intent.get(key)
        if value is not None:
            data[key] = str(value)
    return data


def _prune_invalid_tokens(
    client: firestore.Client,
    uid: str,
    device_tokens: list[Any],
    invalid_tokens: list[str],
) -> None:
    # Read-modify-write: drop the invalid entries from the user's deviceTokens array.
    invalid = set(invalid_tokens)
    remaining = [
        entry
        for entry in device_tokens
        if not (isinstance(entry, dict) and entry.get("token") in invalid)
    ]
    client.collection("users").document(uid).update({"deviceTokens": remaining})


def deliver_notification_intent(
    client: firestore.Client,
    uid: str,
    intent_id: str,
    intent: dict[str, Any],
) -> None:
    if not triggers_enabled():
        log_event(
            trigger=_TRIGGER,
            action="ignore",
            reason="triggers_disabled",
            uid=uid,
            intentId=intent_id,
        )
        return

    # PUSH-5 idempotency guard. Cloud Functions are at-least-once, and
    # @on_document_created ALWAYS re-delivers the ORIGINAL create snapshot
    # (deliveryStatus="pending", no deliveredAt). A guard based on the passed-in `intent`
    # payload would therefore never catch a duplicate event. Re-read the CURRENT intent
    # doc and skip if a prior invocation already stamped `deliveredAt`.
    #
    # The stamp happens after the send (see below), so a crash in the narrow send→stamp
    # window can still yield a duplicate push on re-fire, and two genuinely concurrent
    # duplicate events remain a rare race. That is the accepted at-least-once tradeoff:
    # we prefer a duplicate push over a dropped notification (stamping pre-send would drop
    # on send failure). The common case — a sequential retry of the same event — is now
    # correctly deduplicated.
    try:
        current_snap = _intent_ref(client, uid, intent_id).get()
        current = (current_snap.to_dict() or {}) if current_snap.exists else {}
    except Exception as exc:
        # Best-effort: if the current state can't be read, prefer delivering over dropping.
        log_event(
            trigger=_TRIGGER,
            action="error",
            reason="idempotency_read_failed",
            uid=uid,
            intentId=intent_id,
            error=str(exc),
        )
        current = {}
    if current.get("deliveredAt") is not None:
        log_event(
            trigger=_TRIGGER,
            action="skip",
            reason="already_delivered",
            uid=uid,
            intentId=intent_id,
        )
        return

    user_snap = client.collection("users").document(uid).get()
    user = (user_snap.to_dict() or {}) if user_snap.exists else {}
    device_tokens = user.get("deviceTokens") or []
    tokens = _extract_tokens(device_tokens)

    if not tokens:
        log_event(
            trigger=_TRIGGER,
            action="skip",
            reason="no_tokens",
            uid=uid,
            intentId=intent_id,
        )
        _stamp(client, uid, intent_id, _STATUS_NO_TOKENS)
        return

    data = _build_data(intent)
    title = str(intent.get("title", ""))
    body = str(intent.get("body", ""))

    try:
        success_count, invalid_tokens = fcm_sender.send(tokens, title, body, data)
    except Exception as exc:  # best-effort: never raise out of the handler
        log_event(
            trigger=_TRIGGER,
            action="error",
            reason="send_failed",
            uid=uid,
            intentId=intent_id,
            error=str(exc),
        )
        _stamp(client, uid, intent_id, _STATUS_FAILED)
        return

    pruned_count = 0
    if invalid_tokens:
        try:
            _prune_invalid_tokens(client, uid, device_tokens, invalid_tokens)
            pruned_count = len(invalid_tokens)
        except Exception as exc:  # best-effort: pruning failure must not raise
            log_event(
                trigger=_TRIGGER,
                action="error",
                reason="prune_failed",
                uid=uid,
                intentId=intent_id,
                error=str(exc),
            )

    _stamp(client, uid, intent_id, _STATUS_DELIVERED)

    log_event(
        trigger=_TRIGGER,
        action="deliver",
        uid=uid,
        intentId=intent_id,
        type=str(intent.get("type", "")),
        tokens_count=len(tokens),
        success_count=success_count,
        pruned_count=pruned_count,
    )
