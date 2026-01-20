from datetime import datetime, timezone

from functions.match_triggers.upcoming_cache import apply_completion_cache_migration


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_migration_removes_from_upcoming_and_adds_to_completed() -> None:
    upcoming = [
        {"matchId": "m1", "scheduledAt": _utc(2030, 1, 1, 10, 0)},
        {"matchId": "m2", "scheduledAt": _utc(2030, 1, 2, 10, 0)},
    ]
    completed = []

    updated_upcoming, updated_completed = apply_completion_cache_migration(
        upcoming_cache=upcoming,
        completed_cache=completed,
        match_id="m1",
        finished_at=_utc(2030, 1, 1, 12, 0),
        cap=10,
        extra_fields={"sport": "padel"},
    )

    assert [item["matchId"] for item in updated_upcoming] == ["m2"]
    assert [item["matchId"] for item in updated_completed] == ["m1"]


def test_migration_upcoming_without_match_is_unchanged() -> None:
    upcoming = [
        {"matchId": "m2", "scheduledAt": _utc(2030, 1, 2, 10, 0)},
    ]
    completed: list[dict[str, object]] = []

    updated_upcoming, _ = apply_completion_cache_migration(
        upcoming_cache=upcoming,
        completed_cache=completed,
        match_id="m1",
        finished_at=_utc(2030, 1, 1, 12, 0),
        cap=10,
        extra_fields=None,
    )

    assert [item["matchId"] for item in updated_upcoming] == ["m2"]


def test_migration_inserts_when_missing_in_completed() -> None:
    _, updated_completed = apply_completion_cache_migration(
        upcoming_cache=[],
        completed_cache=[],
        match_id="m1",
        finished_at=_utc(2030, 1, 1, 12, 0),
        cap=10,
        extra_fields=None,
    )

    assert [item["matchId"] for item in updated_completed] == ["m1"]


def test_migration_dedupes_on_repeat() -> None:
    completed = [
        {"matchId": "m1", "finishedAt": _utc(2030, 1, 1, 12, 0)},
    ]

    _, updated_completed = apply_completion_cache_migration(
        upcoming_cache=[],
        completed_cache=completed,
        match_id="m1",
        finished_at=_utc(2030, 1, 1, 12, 0),
        cap=10,
        extra_fields=None,
    )

    assert [item["matchId"] for item in updated_completed] == ["m1"]


def test_migration_orders_completed_desc() -> None:
    completed = [
        {"matchId": "m1", "finishedAt": _utc(2030, 1, 1, 12, 0)},
        {"matchId": "m2", "finishedAt": _utc(2030, 1, 2, 12, 0)},
    ]

    _, updated_completed = apply_completion_cache_migration(
        upcoming_cache=[],
        completed_cache=completed,
        match_id="m3",
        finished_at=_utc(2030, 1, 3, 12, 0),
        cap=10,
        extra_fields=None,
    )

    assert [item["matchId"] for item in updated_completed] == ["m3", "m2", "m1"]


def test_migration_caps_completed_at_ten() -> None:
    completed = [
        {"matchId": f"m{i}", "finishedAt": _utc(2030, 1, i, 12, 0)}
        for i in range(1, 11)
    ]

    _, updated_completed = apply_completion_cache_migration(
        upcoming_cache=[],
        completed_cache=completed,
        match_id="m11",
        finished_at=_utc(2030, 1, 11, 12, 0),
        cap=10,
        extra_fields=None,
    )

    assert len(updated_completed) == 10
    assert [item["matchId"] for item in updated_completed] == [
        "m11",
        "m10",
        "m9",
        "m8",
        "m7",
        "m6",
        "m5",
        "m4",
        "m3",
        "m2",
    ]


def test_migration_retry_does_not_duplicate_or_readd_upcoming() -> None:
    upcoming = [{"matchId": "m1", "scheduledAt": _utc(2030, 1, 1, 10, 0)}]
    completed: list[dict[str, object]] = []

    first_upcoming, first_completed = apply_completion_cache_migration(
        upcoming_cache=upcoming,
        completed_cache=completed,
        match_id="m1",
        finished_at=_utc(2030, 1, 1, 12, 0),
        cap=10,
        extra_fields=None,
    )
    second_upcoming, second_completed = apply_completion_cache_migration(
        upcoming_cache=first_upcoming,
        completed_cache=first_completed,
        match_id="m1",
        finished_at=_utc(2030, 1, 1, 12, 0),
        cap=10,
        extra_fields=None,
    )

    assert [item["matchId"] for item in second_upcoming] == []
    assert [item["matchId"] for item in second_completed] == ["m1"]
