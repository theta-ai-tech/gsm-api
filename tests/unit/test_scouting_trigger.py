"""Unit tests for the scouting journal trigger (D4.3 / D4.4)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from functions.journal_triggers.scouting import (
    handle_scouting_delete,
    handle_scouting_upsert,
    make_dedup_key,
    resolve_opponent_uid,
)

_NOW = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# resolve_opponent_uid
# ---------------------------------------------------------------------------


def test_resolve_opponent_uid_two_players() -> None:
    assert resolve_opponent_uid("u1", ["u1", "u2"]) == "u2"
    assert resolve_opponent_uid("u2", ["u1", "u2"]) == "u1"


def test_resolve_opponent_uid_single_player_returns_none() -> None:
    assert resolve_opponent_uid("u1", ["u1"]) is None


def test_resolve_opponent_uid_three_players_returns_none() -> None:
    assert resolve_opponent_uid("u1", ["u1", "u2", "u3"]) is None


def test_resolve_opponent_uid_empty_returns_none() -> None:
    assert resolve_opponent_uid("u1", []) is None


def test_resolve_opponent_uid_reporter_not_in_list() -> None:
    # If reporter is not in the list, both are "others" but len != 2 check
    # already filters. With exactly 2 participants where reporter is absent:
    result = resolve_opponent_uid("u3", ["u1", "u2"])
    # Returns u1 (first non-reporter) since u3 != u1 and u3 != u2
    assert result == "u1"


# ---------------------------------------------------------------------------
# make_dedup_key
# ---------------------------------------------------------------------------


def test_make_dedup_key() -> None:
    assert make_dedup_key("match1", "user1") == "match1_user1"


def test_make_dedup_key_deterministic() -> None:
    k1 = make_dedup_key("m1", "u1")
    k2 = make_dedup_key("m1", "u1")
    assert k1 == k2


# ---------------------------------------------------------------------------
# handle_scouting_upsert — ignored cases
# ---------------------------------------------------------------------------


def test_upsert_ignores_when_no_sport() -> None:
    client = MagicMock()
    result = handle_scouting_upsert(
        client=client,
        uid="u1",
        entry_id="e1",
        after={"matchId": "m1", "reflection": {"opponentWeak": ["backhand"]}},
    )
    assert result is False
    client.collection.assert_not_called()


def test_upsert_ignores_when_no_match_id() -> None:
    client = MagicMock()
    result = handle_scouting_upsert(
        client=client,
        uid="u1",
        entry_id="e1",
        after={"sport": "tennis", "reflection": {"opponentWeak": ["backhand"]}},
    )
    assert result is False


def test_upsert_ignores_when_no_opponent_tags() -> None:
    client = MagicMock()
    result = handle_scouting_upsert(
        client=client,
        uid="u1",
        entry_id="e1",
        after={
            "sport": "tennis",
            "matchId": "m1",
            "reflection": {"wentWell": ["first_serve"]},
        },
    )
    assert result is False


def test_upsert_ignores_when_no_reflection() -> None:
    client = MagicMock()
    result = handle_scouting_upsert(
        client=client,
        uid="u1",
        entry_id="e1",
        after={"sport": "tennis", "matchId": "m1"},
    )
    assert result is False


def test_upsert_ignores_when_match_not_found() -> None:
    client = MagicMock()
    match_snap = MagicMock()
    match_snap.exists = False
    client.collection.return_value.document.return_value.get.return_value = match_snap

    result = handle_scouting_upsert(
        client=client,
        uid="u1",
        entry_id="e1",
        after={
            "sport": "tennis",
            "matchId": "m1",
            "reflection": {"opponentWeak": ["backhand"]},
        },
    )
    assert result is False


def test_upsert_ignores_when_cannot_resolve_opponent() -> None:
    client = MagicMock()
    match_snap = MagicMock()
    match_snap.exists = True
    match_snap.to_dict.return_value = {"participantUids": ["u1"]}
    client.collection.return_value.document.return_value.get.return_value = match_snap

    result = handle_scouting_upsert(
        client=client,
        uid="u1",
        entry_id="e1",
        after={
            "sport": "tennis",
            "matchId": "m1",
            "reflection": {"opponentWeak": ["backhand"]},
        },
    )
    assert result is False


# ---------------------------------------------------------------------------
# handle_scouting_upsert — happy path
# ---------------------------------------------------------------------------


@patch("functions.journal_triggers.scouting._write_scouting_tags")
def test_upsert_happy_path(mock_write: MagicMock) -> None:
    mock_write.return_value = True

    client = MagicMock()
    match_snap = MagicMock()
    match_snap.exists = True
    match_snap.to_dict.return_value = {"participantUids": ["u1", "u2"]}
    client.collection.return_value.document.return_value.get.return_value = match_snap

    result = handle_scouting_upsert(
        client=client,
        uid="u1",
        entry_id="e1",
        after={
            "sport": "tennis",
            "matchId": "m1",
            "reflection": {
                "opponentWeak": ["backhand", "footwork"],
                "opponentStrong": ["serve"],
            },
        },
    )

    assert result is True
    mock_write.assert_called_once()
    call_kwargs = mock_write.call_args
    assert call_kwargs[1]["opponent_uid"] == "u2"
    assert call_kwargs[1]["sport"] == "tennis"
    assert call_kwargs[1]["weak_tags"] == ["backhand", "footwork"]
    assert call_kwargs[1]["strong_tags"] == ["serve"]
    assert call_kwargs[1]["dedup_key"] == "m1_u1"


@patch("functions.journal_triggers.scouting._write_scouting_tags")
def test_upsert_dedup_returns_false(mock_write: MagicMock) -> None:
    mock_write.return_value = False  # already processed

    client = MagicMock()
    match_snap = MagicMock()
    match_snap.exists = True
    match_snap.to_dict.return_value = {"participantUids": ["u1", "u2"]}
    client.collection.return_value.document.return_value.get.return_value = match_snap

    result = handle_scouting_upsert(
        client=client,
        uid="u1",
        entry_id="e1",
        after={
            "sport": "tennis",
            "matchId": "m1",
            "reflection": {"opponentWeak": ["backhand"]},
        },
    )
    assert result is False


# ---------------------------------------------------------------------------
# handle_scouting_delete — ignored cases
# ---------------------------------------------------------------------------


def test_delete_ignores_when_no_sport() -> None:
    client = MagicMock()
    result = handle_scouting_delete(
        client=client,
        uid="u1",
        entry_id="e1",
        before={"matchId": "m1", "reflection": {"opponentWeak": ["backhand"]}},
    )
    assert result is False


def test_delete_ignores_when_no_match_id() -> None:
    client = MagicMock()
    result = handle_scouting_delete(
        client=client,
        uid="u1",
        entry_id="e1",
        before={"sport": "tennis", "reflection": {"opponentWeak": ["backhand"]}},
    )
    assert result is False


def test_delete_ignores_when_no_opponent_tags() -> None:
    client = MagicMock()
    result = handle_scouting_delete(
        client=client,
        uid="u1",
        entry_id="e1",
        before={
            "sport": "tennis",
            "matchId": "m1",
            "reflection": {"wentWell": ["serve"]},
        },
    )
    assert result is False


# ---------------------------------------------------------------------------
# handle_scouting_delete — happy path
# ---------------------------------------------------------------------------


@patch("functions.journal_triggers.scouting._remove_scouting_tags")
def test_delete_happy_path(mock_remove: MagicMock) -> None:
    mock_remove.return_value = True

    client = MagicMock()
    match_snap = MagicMock()
    match_snap.exists = True
    match_snap.to_dict.return_value = {"participantUids": ["u1", "u2"]}
    client.collection.return_value.document.return_value.get.return_value = match_snap

    result = handle_scouting_delete(
        client=client,
        uid="u1",
        entry_id="e1",
        before={
            "sport": "tennis",
            "matchId": "m1",
            "reflection": {
                "opponentWeak": ["backhand"],
                "opponentStrong": ["serve"],
            },
        },
    )

    assert result is True
    mock_remove.assert_called_once()
    call_kwargs = mock_remove.call_args
    assert call_kwargs[1]["opponent_uid"] == "u2"
    assert call_kwargs[1]["dedup_key"] == "m1_u1"


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------


def test_scouting_upsert_noops_when_disabled(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from functions.journal_triggers.main import handle_journal_entry_write_upsert

    monkeypatch.setenv("GSM_TRIGGERS_ENABLED", "false")

    called = {"value": False}

    def _should_not_call(**kwargs):  # type: ignore[no-untyped-def]
        called["value"] = True
        return True

    monkeypatch.setattr(
        "functions.journal_triggers.main.handle_scouting_upsert", _should_not_call
    )

    handle_journal_entry_write_upsert(
        client=object(),  # type: ignore[arg-type]
        uid="u1",
        entry_id="e1",
        before=None,
        after={
            "sport": "tennis",
            "matchId": "m1",
            "reflection": {"opponentWeak": ["backhand"]},
            "createdAt": _NOW,
            "title": "Test",
        },
    )

    assert called["value"] is False


def test_scouting_delete_noops_when_disabled(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from functions.journal_triggers.main import handle_journal_entry_write_remove

    monkeypatch.setenv("GSM_TRIGGERS_ENABLED", "false")

    called = {"value": False}

    def _should_not_call(**kwargs):  # type: ignore[no-untyped-def]
        called["value"] = True
        return True

    monkeypatch.setattr(
        "functions.journal_triggers.main.handle_scouting_delete", _should_not_call
    )

    handle_journal_entry_write_remove(
        client=object(),  # type: ignore[arg-type]
        uid="u1",
        entry_id="e1",
        before={
            "sport": "tennis",
            "matchId": "m1",
            "reflection": {"opponentWeak": ["backhand"]},
        },
        after=None,
    )

    assert called["value"] is False
