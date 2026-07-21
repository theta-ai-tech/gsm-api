"""Tests for tools.verify_firestore_indexes — the firestore.indexes.json guard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.verify_firestore_indexes import (
    BROADCASTS_FEED_FIELDS,
    has_index,
    load_indexes,
    verify,
)


def test_repo_indexes_file_parses_and_is_valid() -> None:
    """The committed firestore.indexes.json parses and passes all guards."""
    assert verify() == []


def test_repo_declares_broadcasts_feed_index() -> None:
    """The broadcasts-feed composite index from #290 is present."""
    data = load_indexes()
    assert has_index(data["indexes"], "broadcasts", BROADCASTS_FEED_FIELDS)


def test_verify_flags_missing_broadcasts_index(tmp_path: Path) -> None:
    """A file without the broadcasts-feed index is reported as a problem."""
    stripped = {
        "indexes": [
            {
                "collectionGroup": "matches",
                "queryScope": "COLLECTION",
                "fields": [{"fieldPath": "status", "mode": "ASCENDING"}],
            }
        ],
        "fieldOverrides": [],
    }
    p = tmp_path / "firestore.indexes.json"
    p.write_text(json.dumps(stripped), encoding="utf-8")
    problems = verify(p)
    assert any("broadcasts-feed" in msg for msg in problems)


def test_load_indexes_strips_comments(tmp_path: Path) -> None:
    """Firebase-style // comments are tolerated (json.loads would choke on them)."""
    p = tmp_path / "firestore.indexes.json"
    p.write_text(
        '// a comment\n{"indexes": [], "fieldOverrides": []}\n', encoding="utf-8"
    )
    assert load_indexes(p) == {"indexes": [], "fieldOverrides": []}


def test_load_indexes_raises_on_bad_json(tmp_path: Path) -> None:
    p = tmp_path / "firestore.indexes.json"
    p.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_indexes(p)
