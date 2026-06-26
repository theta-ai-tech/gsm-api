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
