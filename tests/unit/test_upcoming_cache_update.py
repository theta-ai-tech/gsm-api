from datetime import datetime, timezone

from functions.match_triggers.upcoming_cache import apply_upcoming_cache_update


def _utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_apply_upcoming_cache_inserts_and_orders() -> None:
    current = [
        {"matchId": "m2", "scheduledAt": _utc(2030, 1, 10, 10, 0), "sport": "padel"},
        {"matchId": "m3", "scheduledAt": _utc(2030, 1, 15, 10, 0), "sport": "padel"},
    ]

    updated = apply_upcoming_cache_update(
        current_cache=current,
        match_id="m1",
        scheduled_at=_utc(2030, 1, 5, 10, 0),
        cap=10,
        extra_fields={"sport": "padel"},
    )

    assert [item["matchId"] for item in updated] == ["m1", "m2", "m3"]


def test_apply_upcoming_cache_inserts_into_empty_list() -> None:
    updated = apply_upcoming_cache_update(
        current_cache=[],
        match_id="m1",
        scheduled_at=_utc(2030, 1, 1, 10, 0),
        cap=10,
        extra_fields={"sport": "padel"},
    )

    assert [item["matchId"] for item in updated] == ["m1"]


def test_apply_upcoming_cache_dedupes_and_updates_timestamp() -> None:
    current = [
        {"matchId": "m1", "scheduledAt": _utc(2030, 1, 10, 10, 0), "sport": "padel"},
        {"matchId": "m2", "scheduledAt": _utc(2030, 1, 15, 10, 0), "sport": "padel"},
    ]

    updated = apply_upcoming_cache_update(
        current_cache=current,
        match_id="m1",
        scheduled_at=_utc(2030, 1, 1, 10, 0),
        cap=10,
        extra_fields={"sport": "padel"},
    )

    assert [item["matchId"] for item in updated] == ["m1", "m2"]
    assert updated[0]["scheduledAt"] == _utc(2030, 1, 1, 10, 0)


def test_apply_upcoming_cache_caps_list() -> None:
    current = [
        {"matchId": "m1", "scheduledAt": _utc(2030, 1, 1, 10, 0), "sport": "padel"},
        {"matchId": "m2", "scheduledAt": _utc(2030, 1, 2, 10, 0), "sport": "padel"},
        {"matchId": "m3", "scheduledAt": _utc(2030, 1, 3, 10, 0), "sport": "padel"},
    ]

    updated = apply_upcoming_cache_update(
        current_cache=current,
        match_id="m4",
        scheduled_at=_utc(2030, 1, 4, 10, 0),
        cap=3,
        extra_fields={"sport": "padel"},
    )

    assert [item["matchId"] for item in updated] == ["m1", "m2", "m3"]


def test_apply_upcoming_cache_dedupes_on_double_insert() -> None:
    current: list[dict[str, object]] = []
    first = apply_upcoming_cache_update(
        current_cache=current,
        match_id="m1",
        scheduled_at=_utc(2030, 1, 1, 10, 0),
        cap=10,
        extra_fields={"sport": "padel"},
    )
    second = apply_upcoming_cache_update(
        current_cache=first,
        match_id="m1",
        scheduled_at=_utc(2030, 1, 1, 10, 0),
        cap=10,
        extra_fields={"sport": "padel"},
    )

    assert [item["matchId"] for item in second] == ["m1"]


def test_apply_upcoming_cache_preserves_sorted_order() -> None:
    current = [
        {"matchId": "m2", "scheduledAt": _utc(2030, 1, 10, 10, 0), "sport": "padel"},
        {"matchId": "m1", "scheduledAt": _utc(2030, 1, 1, 10, 0), "sport": "padel"},
        {"matchId": "m3", "scheduledAt": _utc(2030, 1, 20, 10, 0), "sport": "padel"},
    ]

    updated = apply_upcoming_cache_update(
        current_cache=current,
        match_id="m4",
        scheduled_at=_utc(2030, 1, 5, 10, 0),
        cap=10,
        extra_fields={"sport": "padel"},
    )

    assert [item["matchId"] for item in updated] == ["m1", "m4", "m2", "m3"]


def test_apply_upcoming_cache_caps_at_ten_and_drops_oldest() -> None:
    current = [
        {"matchId": f"m{i}", "scheduledAt": _utc(2030, 1, i, 10, 0), "sport": "padel"}
        for i in range(1, 11)
    ]

    updated = apply_upcoming_cache_update(
        current_cache=current,
        match_id="m11",
        scheduled_at=_utc(2030, 1, 11, 10, 0),
        cap=10,
        extra_fields={"sport": "padel"},
    )

    assert len(updated) == 10
    assert [item["matchId"] for item in updated] == [
        "m2",
        "m3",
        "m4",
        "m5",
        "m6",
        "m7",
        "m8",
        "m9",
        "m10",
        "m11",
    ]
