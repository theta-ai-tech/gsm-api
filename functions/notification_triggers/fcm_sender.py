"""
PUSH-3 — FCM sender utility with invalid-token detection.

send() delivers a notification to a list of device tokens via FCM multicast and
reports which tokens are permanently invalid so the caller (PUSH-4) can prune
them. Permanently invalid (prunable) tokens are those whose per-token failure is
UNREGISTERED or INVALID_ARGUMENT. Transient failures (e.g. UNAVAILABLE) are
logged but never reported as invalid, so they are retried rather than pruned.
"""

from __future__ import annotations

from firebase_admin import messaging

from functions.logging_utils import log_event

_TRIGGER = "PUSH3.fcmSender"

# Per-token failure codes that mean the token is permanently invalid and should
# be pruned. Everything else is treated as transient and left intact.
_PRUNABLE_CODES = frozenset({"UNREGISTERED", "INVALID_ARGUMENT"})


def _is_prunable(exc: BaseException | None) -> bool:
    """True if the per-token send failure means the token is permanently invalid."""
    if exc is None:
        return False
    if isinstance(exc, messaging.UnregisteredError):
        return True
    code = getattr(exc, "code", None)
    return code in _PRUNABLE_CODES


def send(
    tokens: list[str],
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> tuple[int, list[str]]:
    """
    Send a notification to ``tokens`` and report invalid tokens.

    Returns ``(success_count, invalid_tokens)`` where ``invalid_tokens`` are the
    subset of ``tokens`` that failed with a prunable error (UNREGISTERED /
    INVALID_ARGUMENT). Transient failures are logged but not returned as invalid.

    An empty ``tokens`` list short-circuits to ``(0, [])`` without calling FCM.
    """
    if not tokens:
        return 0, []

    message = messaging.MulticastMessage(
        tokens=tokens,
        notification=messaging.Notification(title=title, body=body),
        data=data or {},
    )

    batch = messaging.send_each_for_multicast(message)

    invalid_tokens: list[str] = []
    transient_count = 0
    for token, response in zip(tokens, batch.responses):
        if response.success:
            continue
        exc = response.exception
        if _is_prunable(exc):
            invalid_tokens.append(token)
        else:
            transient_count += 1

    log_event(
        trigger=_TRIGGER,
        action="send",
        tokens_count=len(tokens),
        success_count=batch.success_count,
        invalid_count=len(invalid_tokens),
        transient_count=transient_count,
    )

    return batch.success_count, invalid_tokens
