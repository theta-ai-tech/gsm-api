from datetime import datetime, timezone

import pytest

from functions.league_triggers.on_league_member_write import upsert_league_summary
from functions.match_triggers.upcoming_cache import (
    apply_completion_cache_migration,
    apply_upcoming_cache_update,
)
from tests.helpers.cache_invariants import (
    assert_invariant_violates_cap,
    assert_summary_list_ordered,
    assert_string_id_list,
)

# Use case: Firestore triggers are at-least-once and can replay events. These tests
# ensure duplicate events do not create duplicates or corrupt ordering/caps.


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_duplicate_completion_event_is_idempotent() -> None:
    upcoming = [{"matchId": "m_101", "scheduledAt": _utc(2030, 1, 1, 10, 0)}]
    recent: list[dict[str, object]] = []

    first_upcoming, first_recent = apply_completion_cache_migration(
        upcoming_cache=upcoming,
        completed_cache=recent,
        match_id="m_101",
        finished_at=_utc(2030, 1, 1, 12, 0),
        cap=10,
        extra_fields=None,
    )
    second_upcoming, second_recent = apply_completion_cache_migration(
        upcoming_cache=first_upcoming,
        completed_cache=first_recent,
        match_id="m_101",
        finished_at=_utc(2030, 1, 1, 12, 0),
        cap=10,
        extra_fields=None,
    )

    assert [item["matchId"] for item in second_upcoming] == []
    assert_summary_list_ordered(
        name="recentCompletedMatches",
        items=second_recent,
        key="finishedAt",
        reverse=True,
        cap=10,
        id_key="matchId",
    )
    assert [item["matchId"] for item in second_recent] == ["m_101"]


def test_duplicate_scheduled_event_is_idempotent() -> None:
    first = apply_upcoming_cache_update(
        current_cache=[],
        match_id="m_102",
        scheduled_at=_utc(2030, 1, 2, 10, 0),
        cap=10,
        extra_fields={"sport": "padel"},
    )
    second = apply_upcoming_cache_update(
        current_cache=first,
        match_id="m_102",
        scheduled_at=_utc(2030, 1, 2, 10, 0),
        cap=10,
        extra_fields={"sport": "padel"},
    )

    assert_summary_list_ordered(
        name="upcomingMatches",
        items=second,
        key="scheduledAt",
        reverse=False,
        cap=10,
        id_key="matchId",
    )
    assert [item["matchId"] for item in second] == ["m_102"]


def test_duplicate_league_upsert_is_idempotent() -> None:
    summary = {
        "leagueId": "l_101",
        "name": "League 101",
        "sport": "padel",
        "status": "active",
        "role": "player",
    }

    first = upsert_league_summary([], summary, cap=20)
    second = upsert_league_summary(first, summary, cap=20)

    assert len(second) == 1
    assert second[0]["leagueId"] == "l_101"


def test_invariant_helpers_catch_cap_violation() -> None:
    values = [f"m{i}" for i in range(11)]
    with pytest.raises(AssertionError):
        assert_string_id_list("recentCompletedMatchIds", values, cap=10)
    assert_invariant_violates_cap("recentCompletedMatchIds", values, cap=10)
