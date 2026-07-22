"""Validate firestore.indexes.json before deploying it.

Runs in CI (pytest) and in the Firestore deploy workflow as a standalone,
stdlib-only pre-check so a malformed or regressed indexes file fails loudly
*before* `firebase deploy` touches a live project.

Guards:
  1. The file parses (after stripping the JS-style `//` comments Firebase allows).
  2. The broadcasts-feed composite index from #290 is declared — the Play-tab
     broadcasts feed 500s in prod if this index is missing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
INDEXES_PATH = REPO_ROOT / "firestore.indexes.json"


def _strip_line_comments(text: str) -> str:
    """Drop full-line `//` comments (Firebase tolerates them; json.loads does not)."""
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("//")
    )


def load_indexes(path: Path = INDEXES_PATH) -> dict[str, Any]:
    """Parse firestore.indexes.json into a dict, raising ValueError on bad JSON."""
    raw = path.read_text(encoding="utf-8")
    try:
        return json.loads(_strip_line_comments(raw))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} is not valid JSON: {exc}") from exc


def _fields_of(index: dict[str, Any]) -> list[tuple[str, str]]:
    """Return [(fieldPath, mode-or-arrayConfig), ...] for an index definition."""
    out: list[tuple[str, str]] = []
    for f in index.get("fields", []):
        direction = f.get("mode") or f.get("arrayConfig") or ""
        out.append((f.get("fieldPath", ""), direction))
    return out


def has_index(
    indexes: list[dict[str, Any]], collection: str, fields: list[tuple[str, str]]
) -> bool:
    """True if an index on `collection` with exactly `fields` (in order) is declared."""
    for index in indexes:
        if index.get("collectionGroup") != collection:
            continue
        if _fields_of(index) == fields:
            return True
    return False


# The broadcasts-feed composite index from #290: status ASC + createdAt DESC.
BROADCASTS_FEED_FIELDS = [("status", "ASCENDING"), ("createdAt", "DESCENDING")]


def verify(path: Path = INDEXES_PATH) -> list[str]:
    """Return a list of human-readable problems (empty means valid)."""
    problems: list[str] = []
    data = load_indexes(path)
    indexes = data.get("indexes")
    if not isinstance(indexes, list):
        return [f"{path.name}: missing top-level 'indexes' array"]

    if not has_index(indexes, "broadcasts", BROADCASTS_FEED_FIELDS):
        problems.append(
            "broadcasts-feed composite index (#290) is missing: expected "
            "collectionGroup=broadcasts fields=[status ASC, createdAt DESC]"
        )
    return problems


def main() -> int:
    try:
        problems = verify()
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if problems:
        for p in problems:
            print(f"ERROR: {p}", file=sys.stderr)
        return 1
    print("firestore.indexes.json OK (parses; broadcasts-feed index present)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
