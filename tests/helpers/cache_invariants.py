from __future__ import annotations

from datetime import datetime


def assert_string_id_list(name: str, values: list, cap: int) -> None:
    assert isinstance(values, list), (
        f"{name}: expected list, got {type(values).__name__}"
    )
    assert len(values) <= cap, f"{name}: length {len(values)} exceeds cap {cap}"
    non_strings = [item for item in values if not isinstance(item, str)]
    assert not non_strings, f"{name}: non-string ids {non_strings}"
    duplicates = _find_duplicates(values)
    assert not duplicates, f"{name}: duplicate ids {duplicates}"


def assert_summary_list_ordered(
    name: str,
    items: list[dict],
    key: str,
    reverse: bool,
    cap: int,
    id_key: str,
) -> None:
    assert isinstance(items, list), f"{name}: expected list, got {type(items).__name__}"
    assert len(items) <= cap, f"{name}: length {len(items)} exceeds cap {cap}"

    ids = [item.get(id_key) for item in items]
    duplicates = _find_duplicates([str(i) for i in ids if i is not None])
    assert not duplicates, f"{name}: duplicate {id_key} values {duplicates}"

    values = [item.get(key) for item in items]
    bad_values = [value for value in values if not isinstance(value, datetime)]
    assert not bad_values, f"{name}: non-datetime {key} values {bad_values}"
    expected = sorted(values, reverse=reverse)
    assert values == expected, f"{name}: {key} order violation: {values}"


def assert_invariant_violates_cap(name: str, values: list, cap: int) -> None:
    assert len(values) > cap, f"{name}: expected values to exceed cap {cap}"


def _find_duplicates(values: list[str]) -> list[str]:
    seen = set()
    duplicates = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates
