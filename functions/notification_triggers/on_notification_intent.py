"""
PUSH-4 — notificationIntents Firestore trigger → FCM delivery.

Fires when a ``users/{uid}/notificationIntents/{intentId}`` document is created
(see ``api/app/repos/notification_intent_repo.py`` for the writer). Reads the
target user's device tokens, builds an FCM payload, and delivers it via the
PUSH-3 sender. Delivery is best-effort and decoupled: a send or prune failure is
logged but never raised, so it can never roll back the business transaction that
produced the intent.

Idempotency (skip/stamp via ``deliveredAt``) is intentionally OUT OF SCOPE here —
that is PUSH-5. Only a comment hook is left below.
"""

from __future__ import annotations

from typing import Any

from google.cloud import firestore  # type: ignore[import-untyped]

from functions.logging_utils import log_event
from functions.notification_triggers import fcm_sender
from functions.runtime_flags import triggers_enabled

_TRIGGER = "onNotificationIntentCreated"

# Optional intent fields that map straight into the FCM data payload (as strings).
_OPTIONAL_DATA_KEYS = ("offerId", "matchId", "broadcastId")


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

    # PUSH-5: skip if intent.get("deliveredAt") is already set (idempotency guard).

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
