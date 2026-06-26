"""Unit tests for the PUSH-3 FCM sender utility.

Only the provider call ``messaging.send_each_for_multicast`` is patched, so the
real ``firebase_admin`` exception classes are used for the ``isinstance``-based
classification in the SUT.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from firebase_admin import exceptions, messaging

from functions.notification_triggers import fcm_sender

_SEND = "functions.notification_triggers.fcm_sender.messaging.send_each_for_multicast"


def _response(success: bool, exception: BaseException | None = None) -> MagicMock:
    """Build a fake SendResponse with .success and .exception."""
    resp = MagicMock()
    resp.success = success
    resp.exception = exception
    return resp


def _batch(responses: list[MagicMock]) -> MagicMock:
    """Build a fake BatchResponse with .responses and .success_count."""
    batch = MagicMock()
    batch.responses = responses
    batch.success_count = sum(1 for r in responses if r.success)
    return batch


def test_all_success_returns_no_invalid_tokens() -> None:
    tokens = ["tok_a", "tok_b", "tok_c"]
    with patch(_SEND) as send_mock:
        send_mock.return_value = _batch(
            [_response(True), _response(True), _response(True)]
        )
        success_count, invalid_tokens = fcm_sender.send(tokens, "Hi", "Body")

    assert success_count == 3
    assert invalid_tokens == []
    send_mock.assert_called_once()


def test_partial_invalid_collects_prunable_tokens() -> None:
    tokens = ["tok_ok", "tok_unregistered", "tok_invalid_arg"]
    unregistered = messaging.UnregisteredError("token gone")
    invalid_arg = exceptions.InvalidArgumentError("bad token")
    with patch(_SEND) as send_mock:
        send_mock.return_value = _batch(
            [
                _response(True),
                _response(False, unregistered),
                _response(False, invalid_arg),
            ]
        )
        success_count, invalid_tokens = fcm_sender.send(tokens, "Hi", "Body")

    assert success_count == 1
    # input order preserved
    assert invalid_tokens == ["tok_unregistered", "tok_invalid_arg"]


def test_sender_id_mismatch_is_pruned() -> None:
    """A token bound to a different FCM sender is permanently invalid -> prune."""
    tokens = ["tok_ok", "tok_wrong_sender"]
    mismatch = messaging.SenderIdMismatchError("wrong sender")
    with patch(_SEND) as send_mock:
        send_mock.return_value = _batch([_response(True), _response(False, mismatch)])
        success_count, invalid_tokens = fcm_sender.send(tokens, "Hi", "Body")

    assert success_count == 1
    assert invalid_tokens == ["tok_wrong_sender"]


def test_transient_error_is_not_pruned() -> None:
    tokens = ["tok_ok", "tok_transient"]
    transient = exceptions.UnavailableError("server unavailable")
    with patch(_SEND) as send_mock:
        send_mock.return_value = _batch([_response(True), _response(False, transient)])
        success_count, invalid_tokens = fcm_sender.send(tokens, "Hi", "Body")

    assert success_count == 1
    assert invalid_tokens == []


def test_all_invalid_argument_is_treated_as_payload_error_not_pruned() -> None:
    """If EVERY token fails with INVALID_ARGUMENT, the shared payload is the likely
    cause — do not prune any tokens (avoid wiping all valid tokens)."""
    tokens = ["tok_a", "tok_b", "tok_c"]
    with patch(_SEND) as send_mock:
        send_mock.return_value = _batch(
            [
                _response(False, exceptions.InvalidArgumentError("payload too big")),
                _response(False, exceptions.InvalidArgumentError("payload too big")),
                _response(False, exceptions.InvalidArgumentError("payload too big")),
            ]
        )
        success_count, invalid_tokens = fcm_sender.send(tokens, "Hi", "Body")

    assert success_count == 0
    assert invalid_tokens == []  # nothing pruned


def test_empty_tokens_short_circuits_without_calling_provider() -> None:
    with patch(_SEND) as send_mock:
        result: tuple[int, list[str]] = fcm_sender.send([], "Hi", "Body")

    assert result == (0, [])
    send_mock.assert_not_called()


def test_data_payload_is_passed_through() -> None:
    tokens = ["tok_a"]
    captured: dict[str, Any] = {}

    def _capture(message: Any) -> MagicMock:
        captured["message"] = message
        return _batch([_response(True)])

    with patch(_SEND) as send_mock:
        send_mock.side_effect = _capture
        success_count, invalid_tokens = fcm_sender.send(
            tokens, "Hi", "Body", data={"k": "v"}
        )

    assert success_count == 1
    assert invalid_tokens == []
    assert captured["message"].data == {"k": "v"}
