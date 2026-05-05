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
    doc["resultByUser"] = result_by_user or {WINNER_UID: "win", LOSER_UID: "loss"}
    return doc


def _before(status: str = "pending_confirmation") -> dict:
    return {
        "matchId": MATCH_ID,
        "status": status,
        "participantUids": [WINNER_UID, LOSER_UID],
    }


def _make_member_snap(processed_match_ids: list[str] | None = None) -> MagicMock:
    snap = MagicMock()
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
            client, _before(), _after(result_by_user={LOSER_UID: "loss"}), now=_NOW
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

        updated_fields: list[dict] = []

        def _capture_update(ref: MagicMock, data: dict) -> None:
            updated_fields.append(data)

        client.transaction.return_value.update.side_effect = _capture_update

        with patch(
            "functions.scoring_triggers.league_member_stats.firestore"
        ) as mock_fs:
            mock_fs.transactional = lambda fn: fn
            mock_fs.Increment = lambda n: f"Increment({n})"
            mock_fs.ArrayUnion = lambda v: f"ArrayUnion({v})"
            handle_match_write_update_league_stats(
                client, _before(), _after(), now=_NOW
            )

        fields_written = [list(d.keys()) for d in updated_fields]
        assert any("stats.wins" in keys for keys in fields_written)
        assert any("stats.losses" in keys for keys in fields_written)


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
                WINNER_UID: "win",
                WINNER_UID_2: "win",
                LOSER_UID: "loss",
                LOSER_UID_2: "loss",
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

        updated_fields: list[dict] = []

        def _capture_update(ref: MagicMock, data: dict) -> None:
            updated_fields.append(data)

        client.transaction.return_value.update.side_effect = _capture_update

        with patch(
            "functions.scoring_triggers.league_member_stats.firestore"
        ) as mock_fs:
            mock_fs.transactional = lambda fn: fn
            mock_fs.Increment = lambda n: f"Increment({n})"
            mock_fs.ArrayUnion = lambda v: f"ArrayUnion({v})"
            handle_match_write_update_league_stats(
                client, self._doubles_before(), self._doubles_after(), now=_NOW
            )

        wins_writes = sum(1 for d in updated_fields if "stats.wins" in d)
        losses_writes = sum(1 for d in updated_fields if "stats.losses" in d)
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

        # Transactions run but txn.update should NOT be called (skipped)
        txn = client.transaction.return_value
        txn.update.assert_not_called()
