from functions.league_triggers.on_league_member_write import (
    remove_league_summary,
    upsert_league_summary,
)


def test_remove_existing_league() -> None:
    existing = [
        {"leagueId": "l1", "status": "active"},
        {"leagueId": "l2", "status": "completed"},
    ]

    updated = remove_league_summary(existing, "l1")

    assert [item["leagueId"] for item in updated] == ["l2"]


def test_remove_already_removed_is_no_op() -> None:
    existing = [{"leagueId": "l2", "status": "active"}]

    updated = remove_league_summary(existing, "l1")

    assert updated == existing


def test_join_leave_sequence_is_stable() -> None:
    summary = {
        "leagueId": "l1",
        "name": "League 1",
        "sport": "padel",
        "status": "active",
        "role": "player",
    }
    joined = upsert_league_summary([], summary, cap=20)
    assert [item["leagueId"] for item in joined] == ["l1"]

    left = remove_league_summary(joined, "l1")
    assert left == []

    left_again = remove_league_summary(left, "l1")
    assert left_again == []
