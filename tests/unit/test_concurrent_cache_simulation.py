from datetime import datetime, timezone

from functions.match_triggers.upcoming_cache import apply_completion_cache_migration
from tests.helpers.cache_invariants import assert_summary_list_ordered


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _apply(
    upcoming: list[dict],
    completed: list[dict],
    match_id: str,
    finished_at: datetime,
) -> tuple[list[dict], list[dict]]:
    return apply_completion_cache_migration(
        upcoming_cache=upcoming,
        completed_cache=completed,
        match_id=match_id,
        finished_at=finished_at,
        cap=10,
        extra_fields={"sport": "padel"},
    )


def test_completion_updates_commute_for_distinct_matches() -> None:
    upcoming: list[dict] = []
    completed: list[dict] = []
    match_a = ("m_a", _utc(2020, 12, 31, 10, 0))
    match_b = ("m_b", _utc(2020, 12, 30, 10, 0))

    up_ab, comp_ab = _apply(upcoming, completed, *match_a)
    up_ab, comp_ab = _apply(up_ab, comp_ab, *match_b)

    up_ba, comp_ba = _apply(upcoming, completed, *match_b)
    up_ba, comp_ba = _apply(up_ba, comp_ba, *match_a)

    assert_summary_list_ordered(
        name="completedMatches",
        items=comp_ab,
        key="finishedAt",
        reverse=True,
        cap=10,
        id_key="matchId",
    )
    assert comp_ab == comp_ba
