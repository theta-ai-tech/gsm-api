"""Unit tests for the PUSH-4 notificationIntents → FCM delivery trigger."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from functions.notification_triggers.on_notification_intent import (
    deliver_notification_intent,
)


def _make_client(
    device_tokens: list[dict[str, Any]] | None, exists: bool = True
) -> MagicMock:
    client = MagicMock()
    user_snap = MagicMock()
    user_snap.exists = exists
    user_snap.to_dict.return_value = (
        {"deviceTokens": device_tokens} if device_tokens is not None else {}
    )
    client.collection.return_value.document.return_value.get.return_value = user_snap
    return client


def _user_doc_ref(client: MagicMock) -> MagicMock:
    return client.collection.return_value.document.return_value


def _intent_doc_ref(client: MagicMock) -> MagicMock:
    # users/{uid}/notificationIntents/{intentId} — the stamp target (subcollection).
    return _user_doc_ref(client).collection.return_value.document.return_value


@patch("functions.notification_triggers.on_notification_intent.fcm_sender.send")
def test_delivers_to_all_tokens_with_payload_mapping(mock_send: MagicMock) -> None:
    mock_send.return_value = (2, [])
    client = _make_client([{"token": "tok_a"}, {"token": "tok_b"}])

    deliver_notification_intent(
        client=client,
        uid="u1",
        intent_id="intent1",
        intent={
            "type": "match_confirmed",
            "title": "Match confirmed",
            "body": "You're on for padel",
            "matchId": "m1",
            "offerId": "o1",
        },
    )

    mock_send.assert_called_once()
    args, _ = mock_send.call_args
    tokens, title, body, data = args
    assert tokens == ["tok_a", "tok_b"]
    assert title == "Match confirmed"
    assert body == "You're on for padel"
    assert data == {"type": "match_confirmed", "offerId": "o1", "matchId": "m1"}


@patch("functions.notification_triggers.on_notification_intent.fcm_sender.send")
def test_data_values_are_all_strings(mock_send: MagicMock) -> None:
    mock_send.return_value = (1, [])
    client = _make_client([{"token": "tok_a"}])

    deliver_notification_intent(
        client=client,
        uid="u1",
        intent_id="intent1",
        intent={"type": "broadcast", "title": "t", "body": "b", "broadcastId": 42},
    )

    _, _, _, data = mock_send.call_args[0]
    assert data == {"type": "broadcast", "broadcastId": "42"}
    assert all(isinstance(value, str) for value in data.values())


@patch("functions.notification_triggers.on_notification_intent.fcm_sender.send")
def test_kill_switch_skips_send(mock_send: MagicMock, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("GSM_TRIGGERS_ENABLED", "false")
    client = _make_client([{"token": "tok_a"}])

    deliver_notification_intent(
        client=client,
        uid="u1",
        intent_id="intent1",
        intent={"type": "match_confirmed", "title": "t", "body": "b"},
    )

    mock_send.assert_not_called()
    client.collection.assert_not_called()


@patch("functions.notification_triggers.on_notification_intent.fcm_sender.send")
def test_no_tokens_skips_send(mock_send: MagicMock) -> None:
    client = _make_client([])

    deliver_notification_intent(
        client=client,
        uid="u1",
        intent_id="intent1",
        intent={"type": "match_confirmed", "title": "t", "body": "b"},
    )

    mock_send.assert_not_called()


@patch("functions.notification_triggers.on_notification_intent.fcm_sender.send")
def test_missing_user_doc_skips_send(mock_send: MagicMock) -> None:
    client = _make_client(None, exists=False)

    deliver_notification_intent(
        client=client,
        uid="u1",
        intent_id="intent1",
        intent={"type": "match_confirmed", "title": "t", "body": "b"},
    )

    mock_send.assert_not_called()


@patch("functions.notification_triggers.on_notification_intent.fcm_sender.send")
def test_prunes_invalid_tokens(mock_send: MagicMock) -> None:
    mock_send.return_value = (1, ["bad_tok"])
    device_tokens = [
        {"token": "good_tok", "platform": "ios"},
        {"token": "bad_tok", "platform": "android"},
    ]
    client = _make_client(device_tokens)

    deliver_notification_intent(
        client=client,
        uid="u1",
        intent_id="intent1",
        intent={"type": "match_confirmed", "title": "t", "body": "b"},
    )

    update = _user_doc_ref(client).update
    update.assert_called_once_with(
        {"deviceTokens": [{"token": "good_tok", "platform": "ios"}]}
    )


@patch("functions.notification_triggers.on_notification_intent.fcm_sender.send")
def test_no_pruning_when_all_tokens_valid(mock_send: MagicMock) -> None:
    mock_send.return_value = (1, [])
    client = _make_client([{"token": "good_tok"}])

    deliver_notification_intent(
        client=client,
        uid="u1",
        intent_id="intent1",
        intent={"type": "match_confirmed", "title": "t", "body": "b"},
    )

    _user_doc_ref(client).update.assert_not_called()


@patch("functions.notification_triggers.on_notification_intent.fcm_sender.send")
def test_send_error_is_swallowed(mock_send: MagicMock) -> None:
    mock_send.side_effect = RuntimeError("fcm down")
    client = _make_client([{"token": "tok_a"}])

    # Must not raise.
    deliver_notification_intent(
        client=client,
        uid="u1",
        intent_id="intent1",
        intent={"type": "match_confirmed", "title": "t", "body": "b"},
    )

    _user_doc_ref(client).update.assert_not_called()


@patch("functions.notification_triggers.on_notification_intent.fcm_sender.send")
def test_prune_error_is_swallowed(mock_send: MagicMock) -> None:
    """A failure while pruning invalid tokens must be logged, not raised (best-effort)."""
    mock_send.return_value = (1, ["tok_bad"])
    client = _make_client([{"token": "tok_good"}, {"token": "tok_bad"}])
    # The prune write blows up.
    _user_doc_ref(client).update.side_effect = RuntimeError("firestore unavailable")

    # Must not raise even though the prune write fails.
    deliver_notification_intent(
        client=client,
        uid="u1",
        intent_id="intent1",
        intent={"type": "match_confirmed", "title": "t", "body": "b"},
    )

    # The prune was attempted exactly once (and swallowed).
    _user_doc_ref(client).update.assert_called_once()


@patch("functions.notification_triggers.on_notification_intent.fcm_sender.send")
def test_skips_when_already_delivered(mock_send: MagicMock) -> None:
    """PUSH-5: a non-null deliveredAt means a prior invocation handled it — do not re-send."""
    client = _make_client([{"token": "tok_a"}])

    deliver_notification_intent(
        client=client,
        uid="u1",
        intent_id="intent1",
        intent={
            "type": "match_confirmed",
            "title": "t",
            "body": "b",
            "deliveredAt": "2026-06-25T10:00:00Z",
            "deliveryStatus": "delivered",
        },
    )

    mock_send.assert_not_called()
    # No user read and no stamp write happened (guard returns before touching the client).
    client.collection.assert_not_called()
    _intent_doc_ref(client).update.assert_not_called()


@patch("functions.notification_triggers.on_notification_intent.fcm_sender.send")
def test_stamps_delivered_after_successful_send(mock_send: MagicMock) -> None:
    mock_send.return_value = (1, [])
    client = _make_client([{"token": "tok_a"}])

    deliver_notification_intent(
        client=client,
        uid="u1",
        intent_id="intent1",
        intent={"type": "match_confirmed", "title": "t", "body": "b"},
    )

    mock_send.assert_called_once()
    _intent_doc_ref(client).update.assert_called_once()
    payload = _intent_doc_ref(client).update.call_args[0][0]
    assert payload["deliveryStatus"] == "delivered"
    assert payload["deliveredAt"] is not None


@patch("functions.notification_triggers.on_notification_intent.fcm_sender.send")
def test_stamps_no_tokens(mock_send: MagicMock) -> None:
    client = _make_client([])

    deliver_notification_intent(
        client=client,
        uid="u1",
        intent_id="intent1",
        intent={"type": "match_confirmed", "title": "t", "body": "b"},
    )

    mock_send.assert_not_called()
    _intent_doc_ref(client).update.assert_called_once()
    payload = _intent_doc_ref(client).update.call_args[0][0]
    assert payload["deliveryStatus"] == "no_tokens"
    assert payload["deliveredAt"] is not None


@patch("functions.notification_triggers.on_notification_intent.fcm_sender.send")
def test_stamps_failed_on_send_error(mock_send: MagicMock) -> None:
    mock_send.side_effect = RuntimeError("fcm down")
    client = _make_client([{"token": "tok_a"}])

    deliver_notification_intent(
        client=client,
        uid="u1",
        intent_id="intent1",
        intent={"type": "match_confirmed", "title": "t", "body": "b"},
    )

    _intent_doc_ref(client).update.assert_called_once()
    payload = _intent_doc_ref(client).update.call_args[0][0]
    assert payload["deliveryStatus"] == "failed"
    assert payload["deliveredAt"] is not None


@patch("functions.notification_triggers.on_notification_intent.fcm_sender.send")
def test_stamp_error_is_swallowed(mock_send: MagicMock) -> None:
    """A failure while stamping the intent doc must be logged, not raised (best-effort)."""
    mock_send.return_value = (1, [])
    client = _make_client([{"token": "tok_a"}])
    _intent_doc_ref(client).update.side_effect = RuntimeError("firestore unavailable")

    # Must not raise even though the stamp write fails.
    deliver_notification_intent(
        client=client,
        uid="u1",
        intent_id="intent1",
        intent={"type": "match_confirmed", "title": "t", "body": "b"},
    )

    _intent_doc_ref(client).update.assert_called_once()
