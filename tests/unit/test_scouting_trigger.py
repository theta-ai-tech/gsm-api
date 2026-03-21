"""Unit tests for the scouting journal trigger (D4.3 / D4.4)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from functions.journal_triggers.scouting import (
    compute_tag_delta,
    handle_scouting_delete,
    handle_scouting_upsert,
    hash_dedup_key,
    hash_reporter,
    make_tag_sig,
    parse_tag_sig,
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
    result = resolve_opponent_uid("u3", ["u1", "u2"])
    assert result == "u1"


# ---------------------------------------------------------------------------
# hash_dedup_key / hash_reporter
# ---------------------------------------------------------------------------


def test_hash_dedup_key_deterministic() -> None:
    k1 = hash_dedup_key("m1", "u1")
    k2 = hash_dedup_key("m1", "u1")
    assert k1 == k2


def test_hash_dedup_key_no_raw_uid() -> None:
    h = hash_dedup_key("match1", "user1")
    assert "user1" not in h
    assert "match1" not in h
    assert len(h) == 64  # SHA-256 hex


def test_hash_reporter_deterministic() -> None:
    assert hash_reporter("u1") == hash_reporter("u1")


def test_hash_reporter_no_raw_uid() -> None:
    h = hash_reporter("user_alice")
    assert "user_alice" not in h
    assert len(h) == 64


# ---------------------------------------------------------------------------
# make_tag_sig / parse_tag_sig
# ---------------------------------------------------------------------------


def test_make_tag_sig_sorted() -> None:
    sig = make_tag_sig(["footwork", "backhand"], ["serve"])
    assert sig == "backhand,footwork|serve"


def test_parse_tag_sig_roundtrip() -> None:
    weak = ["backhand", "footwork"]
    strong = ["serve"]
    sig = make_tag_sig(weak, strong)
    parsed_w, parsed_s = parse_tag_sig(sig)
    assert sorted(parsed_w) == sorted(weak)
    assert sorted(parsed_s) == sorted(strong)


def test_parse_tag_sig_empty() -> None:
    sig = make_tag_sig([], [])
    w, s = parse_tag_sig(sig)
    assert w == []
    assert s == []


# ---------------------------------------------------------------------------
# compute_tag_delta
# ---------------------------------------------------------------------------


def test_compute_tag_delta_add_new_tags() -> None:
    wd, sd = compute_tag_delta([], [], ["backhand"], ["serve"])
    assert wd == {"backhand": 1}
    assert sd == {"serve": 1}


def test_compute_tag_delta_remove_old_tags() -> None:
    wd, sd = compute_tag_delta(["backhand"], ["serve"], [], [])
    assert wd == {"backhand": -1}
    assert sd == {"serve": -1}


def test_compute_tag_delta_swap_tags() -> None:
    wd, sd = compute_tag_delta(
        ["backhand"],
        ["serve"],
        ["footwork"],
        ["volley"],
    )
    assert wd == {"backhand": -1, "footwork": 1}
    assert sd == {"serve": -1, "volley": 1}


def test_compute_tag_delta_no_change() -> None:
    wd, sd = compute_tag_delta(["backhand"], ["serve"], ["backhand"], ["serve"])
    assert wd == {}
    assert sd == {}


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


@patch("functions.journal_triggers.scouting._remove_scouting")
def test_upsert_clears_when_no_opponent_tags(mock_remove: MagicMock) -> None:
    mock_remove.return_value = False  # no previous report to remove

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
            "reflection": {"wentWell": ["first_serve"]},
        },
    )
    assert result is False
    mock_remove.assert_called_once()


@patch("functions.journal_triggers.scouting._remove_scouting")
def test_upsert_clears_when_no_reflection(mock_remove: MagicMock) -> None:
    mock_remove.return_value = False

    client = MagicMock()
    match_snap = MagicMock()
    match_snap.exists = True
    match_snap.to_dict.return_value = {"participantUids": ["u1", "u2"]}
    client.collection.return_value.document.return_value.get.return_value = match_snap

    result = handle_scouting_upsert(
        client=client,
        uid="u1",
        entry_id="e1",
        after={"sport": "tennis", "matchId": "m1"},
    )
    assert result is False
    mock_remove.assert_called_once()


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


@patch("functions.journal_triggers.scouting._upsert_scouting")
def test_upsert_happy_path(mock_upsert: MagicMock) -> None:
    mock_upsert.return_value = True

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
    mock_upsert.assert_called_once()
    call_kwargs = mock_upsert.call_args[1]
    assert call_kwargs["opponent_uid"] == "u2"
    assert call_kwargs["sport"] == "tennis"
    assert call_kwargs["weak_tags"] == ["backhand", "footwork"]
    assert call_kwargs["strong_tags"] == ["serve"]
    assert call_kwargs["dedup_hash"] == hash_dedup_key("m1", "u1")
    assert call_kwargs["reporter_hash"] == hash_reporter("u1")


@patch("functions.journal_triggers.scouting._upsert_scouting")
def test_upsert_dedup_returns_false(mock_upsert: MagicMock) -> None:
    mock_upsert.return_value = False  # idempotent — same tags

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
# handle_scouting_upsert — tags cleared (regression: had tags -> now empty)
# ---------------------------------------------------------------------------


@patch("functions.journal_triggers.scouting._remove_scouting")
def test_upsert_reverses_previous_report_when_tags_cleared(
    mock_remove: MagicMock,
) -> None:
    """When a journal entry is edited to remove all opponent tags, the old
    scouting contribution must be reversed via _remove_scouting."""
    mock_remove.return_value = True

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
            "reflection": {"opponentWeak": [], "opponentStrong": []},
        },
    )

    assert result is True
    mock_remove.assert_called_once()
    call_kwargs = mock_remove.call_args[1]
    assert call_kwargs["opponent_uid"] == "u2"
    assert call_kwargs["sport"] == "tennis"
    assert call_kwargs["dedup_hash"] == hash_dedup_key("m1", "u1")


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


def test_delete_ignores_when_match_not_found() -> None:
    client = MagicMock()
    match_snap = MagicMock()
    match_snap.exists = False
    client.collection.return_value.document.return_value.get.return_value = match_snap

    result = handle_scouting_delete(
        client=client,
        uid="u1",
        entry_id="e1",
        before={
            "sport": "tennis",
            "matchId": "m1",
            "reflection": {"opponentWeak": ["backhand"]},
        },
    )
    assert result is False


# ---------------------------------------------------------------------------
# handle_scouting_delete — happy path
# ---------------------------------------------------------------------------


@patch("functions.journal_triggers.scouting._remove_scouting")
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
    call_kwargs = mock_remove.call_args[1]
    assert call_kwargs["opponent_uid"] == "u2"
    assert call_kwargs["dedup_hash"] == hash_dedup_key("m1", "u1")


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
