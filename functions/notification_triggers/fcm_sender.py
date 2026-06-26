"""
PUSH-3 — FCM sender utility with invalid-token detection.

send() delivers a notification to a list of device tokens via FCM multicast and
reports which tokens are permanently invalid so the caller (PUSH-4) can prune
them. Permanently invalid (prunable) tokens are those whose per-token failure is
UNREGISTERED or INVALID_ARGUMENT. Transient failures (e.g. UNAVAILABLE) are
logged but never reported as invalid, so they are retried rather than pruned.
"""

from __future__ import annotations

from firebase_admin import exceptions, messaging

from functions.logging_utils import log_event

_TRIGGER = "PUSH3.fcmSender"


def _is_unconditionally_prunable(exc: BaseException | None) -> bool:
    """
    True for per-token failures that ALWAYS mean the token is permanently invalid,
    regardless of how many tokens fail:

    - ``UnregisteredError``      — app uninstalled / token expired (code ``NOT_FOUND``)
    - ``SenderIdMismatchError``  — token belongs to a different FCM sender (code
      ``PERMISSION_DENIED``); it will never be deliverable by us, so prune it.

    Detection is by exception *type*, not ``.code``: ``UnregisteredError.code`` is
    actually ``"NOT_FOUND"`` and ``SenderIdMismatchError.code`` is
    ``"PERMISSION_DENIED"``, so matching on the class is the reliable signal.
    """
    if exc is None:
        return False
    return isinstance(exc, (messaging.UnregisteredError, messaging.SenderIdMismatchError))


def _is_invalid_argument(exc: BaseException | None) -> bool:
    """
    True if the per-token failure is ``INVALID_ARGUMENT``.

    This is *conditionally* prunable: a single token failing with INVALID_ARGUMENT
    is a malformed token, but if EVERY token fails with it the cause is almost
    certainly a malformed shared payload (title/body/data too large), not the
    tokens — see ``send`` for that guard. Transient errors (``UNAVAILABLE``,
    ``INTERNAL``, quota, third-party-auth) are intentionally NOT pruned.
    """
    if exc is None:
        return False
    if isinstance(exc, exceptions.InvalidArgumentError):
        return True
    return getattr(exc, "code", None) == "INVALID_ARGUMENT"


def send(
    tokens: list[str],
    title: str,
    body: str,
    data: dict[str, str] | None = None,
) -> tuple[int, list[str]]:
    """
    Send a notification to ``tokens`` and report invalid tokens.

    Returns ``(success_count, invalid_tokens)`` where ``invalid_tokens`` are the
    subset of ``tokens`` (in input order) that failed with a *prunable* error:

    - ``UnregisteredError`` / ``SenderIdMismatchError`` — always prunable.
    - ``INVALID_ARGUMENT`` — prunable per-token, EXCEPT when every token fails
      with it (a malformed shared payload would otherwise prune all valid tokens);
      in that case nothing is pruned and the batch is treated as a transient/error.

    Transient failures (UNAVAILABLE, INTERNAL, quota, third-party-auth) are logged
    but never returned as invalid, so the caller retries rather than prunes.

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

    # First pass: classify each failed token (preserve input order).
    hard_prunable: list[str] = []
    invalid_arg: list[str] = []
    transient_count = 0
    for token, response in zip(tokens, batch.responses):
        if response.success:
            continue
        exc = response.exception
        if _is_unconditionally_prunable(exc):
            hard_prunable.append(token)
        elif _is_invalid_argument(exc):
            invalid_arg.append(token)
        else:
            transient_count += 1

    # Guard: if every token failed with INVALID_ARGUMENT, the shared payload is the
    # likely culprit, not the tokens — do not prune any of them.
    all_invalid_arg_payload = bool(invalid_arg) and len(invalid_arg) == len(tokens)
    if all_invalid_arg_payload:
        prunable_invalid_arg: list[str] = []
        transient_count += len(invalid_arg)
    else:
        prunable_invalid_arg = invalid_arg

    prunable = set(hard_prunable) | set(prunable_invalid_arg)
    invalid_tokens = [t for t in tokens if t in prunable]

    log_event(
        trigger=_TRIGGER,
        action="send",
        tokens_count=len(tokens),
        success_count=batch.success_count,
        invalid_count=len(invalid_tokens),
        transient_count=transient_count,
        suspected_payload_error=all_invalid_arg_payload,
    )

    return batch.success_count, invalid_tokens
