"""
Unit tests for handle_match_write_update_league_stats (D5.2 handler)
and increment_member_stats (idempotency logic).

Firestore client is fully mocked; no emulator needed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


from functions.scoring_triggers.main import handle_match_write_update_league_stats

_NOW = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
_FINISHED = datetime(2025, 1, 1, 13, 0, tzinfo=timezone.utc)

LEAGUE_ID = "league_001"
WINNER_UID = "user_winner"
LOSER_UID = "user_loser"
MATCH_ID = "match_001"

# Doubles participants
WINNER_UID_2 = "user_winner2"
LOSER_UID_2 = "user_loser2"


def _after(
    status: str = "completed",
    league_id: str | None = LEAGUE_ID,
    result_by_user: dict | None = None,
) -> dict:
    doc: dict = {
        "matchId": MATCH_ID,
        "status": status,
        "finishedAt": _FINISHED,
        "participantUids": [WINNER_UID, LOSER_UID],
        "sport": "tennis",
    }
    if league_id is not None:
        doc["leagueId"] = league_id
    doc["resultByUser"] = result_by_user or {WINNER_UID: "W", LOSER_UID: "L"}
    return doc


def _before(status: str = "pending_confirmation") -> dict:
    return {
        "matchId": MATCH_ID,
        "status": status,
        "participantUids": [WINNER_UID, LOSER_UID],
    }


def _make_member_snap(
    processed_match_ids: list[str] | None = None, exists: bool = True
) -> MagicMock:
    snap = MagicMock()
    snap.exists = exists
    snap.to_dict.return_value = {"processedMatchIds": processed_match_ids or []}
    return snap


def _make_client(member_snap: MagicMock | None = None) -> MagicMock:
    client = MagicMock()
    if member_snap is not None:
        (
            client.collection.return_value.document.return_value.collection.return_value.document.return_value.get.return_value
        ) = member_snap
    mock_txn = MagicMock()
    client.transaction.return_value = mock_txn
    return client


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------


class TestKillSwitch:
    def test_disabled_returns_early_without_any_writes(self) -> None:
        client = _make_client()
        with patch(
            "functions.scoring_triggers.main.triggers_enabled", return_value=False
        ):
            handle_match_write_update_league_stats(
                client, _before(), _after(), now=_NOW
            )
        client.transaction.assert_not_called()


# ---------------------------------------------------------------------------
# Non-qualifying events
# ---------------------------------------------------------------------------


class TestNonQualifyingEvents:
    def test_already_completed_status_is_skipped(self) -> None:
        client = _make_client()
        handle_match_write_update_league_stats(
            client, _before("completed"), _after("completed"), now=_NOW
        )
        client.transaction.assert_not_called()

    def test_casual_match_without_league_id_is_ignored(self) -> None:
        client = _make_client()
        handle_match_write_update_league_stats(
            client, _before(), _after(league_id=None), now=_NOW
        )
        client.transaction.assert_not_called()

    def test_missing_result_by_user_is_ignored(self) -> None:
        client = _make_client()
        after = _after()
        after["resultByUser"] = {}
        handle_match_write_update_league_stats(client, _before(), after, now=_NOW)
        client.transaction.assert_not_called()

    def test_incomplete_result_by_user_without_winner_is_ignored(self) -> None:
        client = _make_client()
        handle_match_write_update_league_stats(
            client, _before(), _after(result_by_user={LOSER_UID: "L"}), now=_NOW
        )
        client.transaction.assert_not_called()


# ---------------------------------------------------------------------------
# Qualifying events
# ---------------------------------------------------------------------------


class TestQualifyingEvent:
    def _run(self, member_snap: MagicMock | None = None) -> MagicMock:
        if member_snap is None:
            member_snap = _make_member_snap()
        client = _make_client(member_snap)

        with patch(
            "functions.scoring_triggers.league_member_stats.firestore"
        ) as mock_fs:
            mock_fs.transactional = lambda fn: fn
            mock_fs.Increment = MagicMock(side_effect=lambda n: f"Increment({n})")
            mock_fs.ArrayUnion = MagicMock(side_effect=lambda v: f"ArrayUnion({v})")
            handle_match_write_update_league_stats(
                client, _before(), _after(), now=_NOW
            )

        return client

    def test_two_transactions_run_for_winner_and_loser(self) -> None:
        client = self._run()
        # transaction() called once per increment_member_stats call (winner + loser)
        assert client.transaction.call_count == 2

    def test_member_doc_updated_for_winner_with_wins_field(self) -> None:
        snap = _make_member_snap()
        client = _make_client(snap)

        written_data: list[dict] = []

        def _capture_set(ref: MagicMock, data: dict, **kwargs: object) -> None:
            written_data.append(data)

        client.transaction.return_value.set.side_effect = _capture_set

        with patch(
            "functions.scoring_triggers.league_member_stats.firestore"
        ) as mock_fs:
            mock_fs.transactional = lambda fn: fn
            mock_fs.Increment = lambda n: f"Increment({n})"
            mock_fs.ArrayUnion = lambda v: f"ArrayUnion({v})"
            handle_match_write_update_league_stats(
                client, _before(), _after(), now=_NOW
            )

        stats_keys = [set(d.get("stats", {}).keys()) for d in written_data]
        assert any("wins" in keys for keys in stats_keys)
        assert any("losses" in keys for keys in stats_keys)


# ---------------------------------------------------------------------------
# Doubles match — 4 participants
# ---------------------------------------------------------------------------


class TestDoublesMatch:
    """D5.2 must increment stats for every winner and every loser (2+2 for doubles)."""

    def _doubles_after(self) -> dict:
        return {
            "matchId": MATCH_ID,
            "status": "completed",
            "finishedAt": _FINISHED,
            "participantUids": [WINNER_UID, WINNER_UID_2, LOSER_UID, LOSER_UID_2],
            "sport": "padel",
            "leagueId": LEAGUE_ID,
            "resultByUser": {
                WINNER_UID: "W",
                WINNER_UID_2: "W",
                LOSER_UID: "L",
                LOSER_UID_2: "L",
            },
        }

    def _doubles_before(self) -> dict:
        return {
            "matchId": MATCH_ID,
            "status": "pending_confirmation",
            "participantUids": [WINNER_UID, WINNER_UID_2, LOSER_UID, LOSER_UID_2],
        }

    def test_doubles_increments_four_transactions(self) -> None:
        """Four calls to increment_member_stats — one per participant."""
        member_snap = _make_member_snap()
        client = _make_client(member_snap)

        with patch(
            "functions.scoring_triggers.league_member_stats.firestore"
        ) as mock_fs:
            mock_fs.transactional = lambda fn: fn
            mock_fs.Increment = MagicMock(side_effect=lambda n: f"Increment({n})")
            mock_fs.ArrayUnion = MagicMock(side_effect=lambda v: f"ArrayUnion({v})")
            handle_match_write_update_league_stats(
                client, self._doubles_before(), self._doubles_after(), now=_NOW
            )

        # One transaction per participant: 2 winners + 2 losers = 4
        assert client.transaction.call_count == 4

    def test_doubles_writes_wins_for_both_winners(self) -> None:
        """Both winner UIDs receive a 'wins' increment."""
        member_snap = _make_member_snap()
        client = _make_client(member_snap)

        written_data: list[dict] = []

        def _capture_set(ref: MagicMock, data: dict, **kwargs: object) -> None:
            written_data.append(data)

        client.transaction.return_value.set.side_effect = _capture_set

        with patch(
            "functions.scoring_triggers.league_member_stats.firestore"
        ) as mock_fs:
            mock_fs.transactional = lambda fn: fn
            mock_fs.Increment = lambda n: f"Increment({n})"
            mock_fs.ArrayUnion = lambda v: f"ArrayUnion({v})"
            handle_match_write_update_league_stats(
                client, self._doubles_before(), self._doubles_after(), now=_NOW
            )

        wins_writes = sum(1 for d in written_data if "wins" in d.get("stats", {}))
        losses_writes = sum(1 for d in written_data if "losses" in d.get("stats", {}))
        assert wins_writes == 2
        assert losses_writes == 2

    def test_singles_still_produces_exactly_two_transactions(self) -> None:
        """Regression guard: singles match must still produce exactly 2 transactions."""
        member_snap = _make_member_snap()
        client = _make_client(member_snap)

        with patch(
            "functions.scoring_triggers.league_member_stats.firestore"
        ) as mock_fs:
            mock_fs.transactional = lambda fn: fn
            mock_fs.Increment = MagicMock(side_effect=lambda n: f"Increment({n})")
            mock_fs.ArrayUnion = MagicMock(side_effect=lambda v: f"ArrayUnion({v})")
            # Use the standard singles _after() fixture (1 winner, 1 loser)
            handle_match_write_update_league_stats(
                client, _before(), _after(), now=_NOW
            )

        assert client.transaction.call_count == 2


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_already_processed_match_is_skipped(self) -> None:
        # Member snap already has the match in processedMatchIds
        snap = _make_member_snap(processed_match_ids=[MATCH_ID])
        client = _make_client(snap)

        with patch(
            "functions.scoring_triggers.league_member_stats.firestore"
        ) as mock_fs:
            mock_fs.transactional = lambda fn: fn
            mock_fs.Increment = lambda n: f"Increment({n})"
            mock_fs.ArrayUnion = lambda v: f"ArrayUnion({v})"
            handle_match_write_update_league_stats(
                client, _before(), _after(), now=_NOW
            )

        # Transactions run but txn.set should NOT be called (skipped)
        txn = client.transaction.return_value
        txn.set.assert_not_called()


# ---------------------------------------------------------------------------
# Production encoding regression — MatchResultEnum values "W" / "L"
# ---------------------------------------------------------------------------


class TestProductionEncoding:
    """
    Regression guard: confirm that the handler accepts the real MatchResultEnum
    storage values ("W" / "L") written by match_confirmation_service, not the
    legacy strings ("win" / "loss") that only appear in older fixture data.
    """

    def test_singles_with_enum_values_runs_two_transactions(self) -> None:
        """Singles match using "W"/"L" must produce exactly 2 transactions."""
        member_snap = _make_member_snap()
        client = _make_client(member_snap)

        after = _after(result_by_user={WINNER_UID: "W", LOSER_UID: "L"})
        with patch(
            "functions.scoring_triggers.league_member_stats.firestore"
        ) as mock_fs:
            mock_fs.transactional = lambda fn: fn
            mock_fs.Increment = MagicMock(side_effect=lambda n: f"Increment({n})")
            mock_fs.ArrayUnion = MagicMock(side_effect=lambda v: f"ArrayUnion({v})")
            handle_match_write_update_league_stats(client, _before(), after, now=_NOW)

        assert client.transaction.call_count == 2

    def test_doubles_with_enum_values_runs_four_transactions(self) -> None:
        """Doubles match using "W"/"L" must produce exactly 4 transactions."""
        member_snap = _make_member_snap()
        client = _make_client(member_snap)

        after = {
            "matchId": MATCH_ID,
            "status": "completed",
            "finishedAt": _FINISHED,
            "participantUids": [WINNER_UID, WINNER_UID_2, LOSER_UID, LOSER_UID_2],
            "sport": "padel",
            "leagueId": LEAGUE_ID,
            "resultByUser": {
                WINNER_UID: "W",
                WINNER_UID_2: "W",
                LOSER_UID: "L",
                LOSER_UID_2: "L",
            },
        }
        before = {
            "matchId": MATCH_ID,
            "status": "pending_confirmation",
            "participantUids": [WINNER_UID, WINNER_UID_2, LOSER_UID, LOSER_UID_2],
        }
        with patch(
            "functions.scoring_triggers.league_member_stats.firestore"
        ) as mock_fs:
            mock_fs.transactional = lambda fn: fn
            mock_fs.Increment = MagicMock(side_effect=lambda n: f"Increment({n})")
            mock_fs.ArrayUnion = MagicMock(side_effect=lambda v: f"ArrayUnion({v})")
            handle_match_write_update_league_stats(client, before, after, now=_NOW)

        assert client.transaction.call_count == 4

    def test_unknown_result_value_is_ignored(self) -> None:
        """An unrecognized result value ("win" lowercase, "draw", etc.) must not trigger writes."""
        client = _make_client()
        # Payload with only unrecognized values — no "W" winner present
        after = _after(result_by_user={WINNER_UID: "draw", LOSER_UID: "L"})
        handle_match_write_update_league_stats(client, _before(), after, now=_NOW)
        # No winner found → ignored
        client.transaction.assert_not_called()


# ---------------------------------------------------------------------------
# Missing member doc — must never create a partial membership record
# ---------------------------------------------------------------------------


class TestMissingMemberDoc:
    """
    If the league member doc does not exist, increment_member_stats must skip
    the write entirely. Creating a partial doc with only stats/processedMatchIds
    would create a spurious membership record (role_service checks doc existence).
    """

    def test_missing_member_doc_skips_write(self) -> None:
        """A non-existent member doc must produce no txn.set call."""
        snap = _make_member_snap(exists=False)
        client = _make_client(snap)

        with patch(
            "functions.scoring_triggers.league_member_stats.firestore"
        ) as mock_fs:
            mock_fs.transactional = lambda fn: fn
            mock_fs.Increment = MagicMock(side_effect=lambda n: f"Increment({n})")
            mock_fs.ArrayUnion = MagicMock(side_effect=lambda v: f"ArrayUnion({v})")
            handle_match_write_update_league_stats(
                client, _before(), _after(), now=_NOW
            )

        txn = client.transaction.return_value
        txn.set.assert_not_called()

    def test_missing_member_doc_returns_false(self) -> None:
        """increment_member_stats returns False when the member doc does not exist."""
        from functions.scoring_triggers.league_member_stats import (
            increment_member_stats,
        )

        snap = MagicMock()
        snap.exists = False
        client = MagicMock()
        (
            client.collection.return_value.document.return_value.collection.return_value.document.return_value.get.return_value
        ) = snap
        mock_txn = MagicMock()
        client.transaction.return_value = mock_txn

        with patch(
            "functions.scoring_triggers.league_member_stats.firestore"
        ) as mock_fs:
            mock_fs.transactional = lambda fn: fn
            result = increment_member_stats(
                client, "league_001", "unknown_user", "wins", "match_x"
            )

        assert result is False
        mock_txn.set.assert_not_called()
